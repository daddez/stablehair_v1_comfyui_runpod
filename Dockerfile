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

# 3. Installazione massiva e blindata
# Il flag extra-index-url è ora integrato nel file di testo
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
RUN pip install --no-cache-dir -r /requirements.txt

# 4. Dipendenze Serverless
RUN pip install --no-cache-dir runpod requests

# 5. Copiamo l'handler
COPY handler.py /handler.py

# 6. Avvio
CMD ["python", "-u", "/handler.py"]
