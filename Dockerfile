# SubStudio: FastAPI backend + React UI + FunASR + ffmpeg in one image.

# ---- web UI ---------------------------------------------------------------------------------
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- runtime --------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm
# Noto fonts cover Lao, Khmer, Myanmar, Thai, Vietnamese (core) and Chinese (cjk) subtitles.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgomp1 fonts-noto-core fonts-noto-cjk fontconfig \
    && rm -rf /var/lib/apt/lists/* && fc-cache -f

WORKDIR /app

# Install Python dependencies (PyTorch CPU wheel + FunASR)
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Custom fonts: Phetsarath OT (Lao), Kantumruy Pro (Khmer)
COPY backend/app/fonts /usr/local/share/fonts/custom
RUN fc-cache -f

# Model directory (persisted via volume mount ./models:/models for fast builds)
ENV MODELS_DIR=/models MODELSCOPE_CACHE=/models
RUN mkdir -p /models

COPY backend/app backend/app
COPY --from=web /web/dist web/dist

ENV DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME ["/data", "/models"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/meta', timeout=4)"
# One worker only: the job queue lives in-process, a second worker would run jobs twice.
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
