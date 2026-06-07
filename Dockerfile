# 1. Base snella
FROM python:3.12-slim
ENV DEBIAN_FRONTEND=noninteractive

# 2. Librerie di sistema
RUN apt-get update && apt-get install -y \
    git \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# ==========================================
# 3. BLINDATURA PYTORCH (CUDA 12.1 Universale)
# ==========================================
RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 4. Installazione di tutte le altre librerie
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt --extra-index-url https://download.pytorch.org/whl/cu118

# 5. Dipendenze Serverless
RUN pip install --no-cache-dir runpod requests

# 6. Copiamo l'handler
COPY handler.py /handler.py

# 7. Avvio
CMD ["python", "-u", "/handler.py"]
