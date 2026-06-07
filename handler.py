import runpod
import subprocess
import time
import requests
import os
import base64
import urllib.request
import urllib.parse
import shutil

# ==========================================
# CONFIGURAZIONE PERCORSI
# ==========================================
COMFYUI_DIR = "/runpod-volume/runpod-slim/ComfyUI"
PYTHON_EXECUTABLE = "python"
COMFYUI_PORT = "8188"
COMFYUI_URL = f"http://127.0.0.1:{COMFYUI_PORT}"

def start_comfyui():
    """Avvia ComfyUI intercettando i log per la diagnostica integrale."""
    print(f"Avvio ComfyUI dalla cartella: {COMFYUI_DIR}...")
    log_file_path = "/tmp/comfyui_startup.log"
    
    # Avviamo il processo incanalando Output ed Errori nel file di log
    log_file = open(log_file_path, "w", encoding="utf-8")
    cmd = [PYTHON_EXECUTABLE, "main.py", "--listen", "127.0.0.1", "--port", COMFYUI_PORT]
    process = subprocess.Popen(cmd, cwd=COMFYUI_DIR, stdout=log_file, stderr=subprocess.STDOUT)

    print("In attesa dell'avvio di ComfyUI locale (Timeout 120s)...")
    for _ in range(120):
        # Controllo se il processo è morto prematuramente (Crash istantaneo)
        if process.poll() is not None:
            log_file.close()
            # Lettura integrale blindata contro i caratteri ANSI anomali
            with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
                error_log = f.read()
            raise RuntimeError(f"ComfyUI si è schiantato in fase di avvio.\n\n=== INIZIO LOG INTEGRALE ===\n{error_log}\n=== FINE LOG INTEGRALE ===")

        # Controllo rete
        try:
            response = requests.get(f"{COMFYUI_URL}/system_stats", timeout=1)
            if response.status_code == 200:
                print("ComfyUI operativo e pronto a elaborare.")
                log_file.close()
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    
    # Se il ciclo finisce, c'è stato un Timeout.
    log_file.close()
    with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
        error_log = f.read()
    raise RuntimeError(f"TIMEOUT CRITICO: Nessuna risposta entro 120s.\n\n=== INIZIO LOG INTEGRALE ===\n{error_log}\n=== FINE LOG INTEGRALE ===")

def get_image(filename, subfolder, folder_type):
    """Scarica l'immagine dalla cache di ComfyUI."""
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen(f"{COMFYUI_URL}/view?{url_values}") as response:
        return response.read()

def handler(job):
    job_input = job['input']
    workflow = job_input.get('workflow', {})
    if not workflow:
         return {"error": "Nessun workflow fornito nell'input."}

    input_images = job_input.get('input_images', {})
    input_dir = os.path.join(COMFYUI_DIR, "input")
    output_dir = os.path.join(COMFYUI_DIR, "output")
    os.makedirs(input_dir, exist_ok=True)
    
    # Registro tracciamento per Garbage Collection
    tracciato_file_generati = []

    try:
        # =======================================================
        # 1. Salvataggio su disco (Cartella nativa)
        # Il client ha già iniettato l'UUID nel nome del file
        # =======================================================
        for filename, b64_data in input_images.items():
            filepath = os.path.join(input_dir, filename)
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(b64_data))
            tracciato_file_generati.append(filepath)

        # =======================================================
        # 2. Trasmissione Payload a ComfyUI
        # =======================================================
        prompt_req = requests.post(f"{COMFYUI_URL}/prompt", json={"prompt": workflow}).json()
        if 'prompt_id' not in prompt_req:
            return {"error": f"Errore API ComfyUI: {prompt_req}"}
            
        prompt_id = prompt_req['prompt_id']

        # =======================================================
        # 3. Intercettazione stato e Anti-Loop
        # =======================================================
        timeout_anomalia = 0
        while True:
            history_req = requests.get(f"{COMFYUI_URL}/history/{prompt_id}").json()
            if prompt_id in history_req:
                history = history_req[prompt_id]
                break
            
            # Verifica integrità della coda
            queue_req = requests.get(f"{COMFYUI_URL}/queue").json()
            pending = [p[1] for p in queue_req.get('queue_pending', [])]
            running = [p[1] for p in queue_req.get('queue_running', [])]
            
            # Condizione di scarto dal motore di inferenza
            if prompt_id not in pending and prompt_id not in running and prompt_id not in history_req:
                timeout_anomalia += 1
                if timeout_anomalia >= 5:
                    return {"error": "Workflow fallito internamente a ComfyUI (possibile nodo o file mancante). Elaborazione interrotta."}
            else:
                timeout_anomalia = 0
                
            time.sleep(1)

        # =======================================================
        # 4. Estrazione ed elaborazione Output
        # =======================================================
        output_images_b64 = []
        for node_id in history['outputs']:
            node_output = history['outputs'][node_id]
            if 'images' in node_output:
                for image in node_output['images']:
                    image_data = get_image(image['filename'], image['subfolder'], image['type'])
                    
                    # Tracciamento file di output per la distruzione
                    sub_dir = image['subfolder'] if image['subfolder'] else ''
                    out_filepath = os.path.join(output_dir, sub_dir, image['filename'])
                    tracciato_file_generati.append(out_filepath)
                    
                    base64_image = base64.b64encode(image_data).decode('utf-8')
                    output_images_b64.append({
                        "filename": image['filename'],
                        "image_base64": base64_image
                    })

        return {"status": "success", "images": output_images_b64}

    except Exception as e:
        return {"error": f"Errore infrastrutturale: {str(e)}"}

    finally:
        # =======================================================
        # 5. Distruzione dei media isolati
        # =======================================================
        for fpath in tracciato_file_generati:
            try:
                if os.path.exists(fpath):
                    os.remove(fpath)
            except OSError:
                pass

# ==========================================
# ESECUZIONE PRINCIPALE E GESTIONE AVARIA
# ==========================================
comfyui_operativo = False
messaggio_avaria = ""

if __name__ == "__main__":
    if not os.path.exists(COMFYUI_DIR):
        messaggio_avaria = f"Volume di rete assente in {COMFYUI_DIR}."
        print(f"ERRORE CRITICO: {messaggio_avaria}")
    else:
        try:
            start_comfyui()
            comfyui_operativo = True
        except Exception as e:
            messaggio_avaria = f"Crash di ComfyUI all'avvio: {str(e)}"
            print(f"ERRORE FATALE INTERCETTATO: {messaggio_avaria}")
            # L'eccezione è isolata. Il processo Python non si interrompe.

    def safe_handler(job):
        """Wrapper di sicurezza: scarta i job se il motore è spento, forzando lo spegnimento del worker."""
        if not comfyui_operativo:
            return {"error": f"Worker in avaria permanente. Elaborazione disabilitata. Dettagli: {messaggio_avaria}"}
        
        # Se tutto funziona, passa il job al tuo handler originale
        return handler(job)

    # Avviamo il listener Serverless agganciandolo al safe_handler
    runpod.serverless.start({"handler": safe_handler})
