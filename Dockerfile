# 1. Base snella
FROM python:3.12-slim

# ==========================================
# BLINDATURA GLOBALE DEL SISTEMA OPERATIVO
# ==========================================
ENV DEBIAN_FRONTEND=noninteractive
# Costringe qualsiasi processo (incluso ComfyUI-Manager a runtime) a usare CUDA 11.8
ENV PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cu118

# 2. Librerie di sistema
RUN apt-get update && apt-get install -y \
    git \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# 3. Installazione massiva
COPY requirements.txt /requirements.txt
# Installiamo esplicitamente torch bloccando la versione prima dei requisiti custom
RUN pip install --no-cache-dir torch torchvision torchaudio
RUN pip install --no-cache-dir -r /requirements.txt

# 4. Dipendenze Serverless
RUN pip install --no-cache-dir runpod requests

# 5. Copiamo l'handler
COPY handler.py /handler.py

# 6. Avvio
CMD ["python", "-u", "/handler.py"]
