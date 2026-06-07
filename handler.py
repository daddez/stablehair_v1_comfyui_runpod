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

# Directory Effimere (RAM/Disco Locale isolato del container)
TEMP_INPUT_DIR = "/tmp/input"
TEMP_OUTPUT_DIR = "/tmp/output"

def start_comfyui():
    """Avvia ComfyUI deviando l'input/output sullo storage temporaneo del container."""
    print(f"Avvio ComfyUI dalla cartella: {COMFYUI_DIR}...")
    
    # Assicura l'esistenza delle directory effimere prima dell'avvio
    os.makedirs(TEMP_INPUT_DIR, exist_ok=True)
    os.makedirs(TEMP_OUTPUT_DIR, exist_ok=True)
    
    # Argomenti CLI aggiunti per dirottare I/O
    cmd = [
        PYTHON_EXECUTABLE, "main.py", 
        "--listen", "127.0.0.1", 
        "--port", COMFYUI_PORT,
        "--input-directory", TEMP_INPUT_DIR,
        "--output-directory", TEMP_OUTPUT_DIR
    ]
    subprocess.Popen(cmd, cwd=COMFYUI_DIR)

    print("In attesa dell'avvio di ComfyUI locale...")
    while True:
        try:
            response = requests.get(f"{COMFYUI_URL}/system_stats", timeout=1)
            if response.status_code == 200:
                print("ComfyUI è operativo e pronto a elaborare.")
                break
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)

def get_image(filename, subfolder, folder_type):
    """Scarica l'immagine appena generata dalla cache di ComfyUI (che ora legge da /tmp/output)."""
    data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
    url_values = urllib.parse.urlencode(data)
    with urllib.request.urlopen(f"{COMFYUI_URL}/view?{url_values}") as response:
        return response.read()

def handler(job):
    """Gestore delle richieste Serverless con pulizia automatica."""
    job_input = job['input']
    
    workflow = job_input.get('workflow', {})
    if not workflow:
         return {"error": "Nessun workflow fornito nell'input."}

    # Assicura l'esistenza delle directory a ogni chiamata (in caso di instabilità del file system)
    os.makedirs(TEMP_INPUT_DIR, exist_ok=True)
    os.makedirs(TEMP_OUTPUT_DIR, exist_ok=True)

    try:
        # =======================================================
        # 0. SALVATAGGIO IMMAGINI IN INGRESSO (IN MEMORIA EFFIMERA)
        # =======================================================
        input_images = job_input.get('input_images', {})
        
        for filename, b64_data in input_images.items():
            filepath = os.path.join(TEMP_INPUT_DIR, filename)
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(b64_data))
            print(f"Immagine di input salvata in effimero: {filename}")

        # =======================================================
        # 1. INVIA WORKFLOW E ATTENDI
        # =======================================================
        print("Inviando il prompt a ComfyUI...")
        prompt_req = requests.post(f"{COMFYUI_URL}/prompt", json={"prompt": workflow}).json()
        
        if 'prompt_id' not in prompt_req:
            return {"error": f"Errore API ComfyUI: {prompt_req}"}
            
        prompt_id = prompt_req['prompt_id']

        print(f"Attendendo il completamento (ID Lavoro: {prompt_id})...")
        while True:
            history_req = requests.get(f"{COMFYUI_URL}/history/{prompt_id}").json()
            if prompt_id in history_req:
                history = history_req[prompt_id]
                break
            time.sleep(1)

        # =======================================================
        # 2. ESTRAI E CODIFICA OUTPUT
        # =======================================================
        output_images = []
        for node_id in history['outputs']:
            node_output = history['outputs'][node_id]
            if 'images' in node_output:
                for image in node_output['images']:
                    image_data = get_image(image['filename'], image['subfolder'], image['type'])
                    base64_image = base64.b64encode(image_data).decode('utf-8')
                    output_images.append({
                        "filename": image['filename'],
                        "image_base64": base64_image
                    })

        # Il return avviene solo dopo che il blocco finally è stato eseguito
        return {"status": "success", "images": output_images}

    except Exception as e:
        return {"error": f"Eccezione durante l'elaborazione: {str(e)}"}

    finally:
        # =======================================================
        # 3. PULIZIA FORZATA (GARBAGE COLLECTION)
        # =======================================================
        # Questo blocco viene eseguito tassativamente alla fine di ogni singola chiamata,
        # indipendentemente dal fatto che l'inferenza abbia avuto successo o generato un errore.
        print("Esecuzione pulizia memoria effimera post-inferenza...")
        for directory in [TEMP_INPUT_DIR, TEMP_OUTPUT_DIR]:
            if os.path.exists(directory):
                for filename in os.listdir(directory):
                    file_path = os.path.join(directory, filename)
                    try:
                        if os.path.isfile(file_path) or os.path.islink(file_path):
                            os.unlink(file_path)
                        elif os.path.isdir(file_path):
                            shutil.rmtree(file_path)
                    except Exception as e:
                        print(f"Impossibile eliminare {file_path}. Motivo: {e}")

# ==========================================
# ESECUZIONE PRINCIPALE
# ==========================================
if __name__ == "__main__":
    if not os.path.exists(COMFYUI_DIR):
        print(f"ERRORE CRITICO: La cartella {COMFYUI_DIR} non esiste.")
        print("Il Network Volume non è montato o il percorso è errato.")
    else:
        start_comfyui()
        runpod.serverless.start({"handler": handler})
