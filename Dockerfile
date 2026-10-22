# SubStudio: FastAPI backend + React UI + whisper.cpp + ffmpeg in one image.

# ---- web UI ---------------------------------------------------------------------------------
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- whisper.cpp (built from source for Linux) ----------------------------------------------
FROM debian:bookworm-slim AS whisper
ARG WHISPER_REF=b5454
# ON = optimise for the CPU of the machine running `docker build` (build on the server itself).
# OFF = portable build using WHISPER_CPU_FLAGS instead, for images built on another machine.
# Note: VMware guests may hide AVX2 even on CPUs that have it (192.168.1.101 shows only AVX/FMA).
ARG WHISPER_NATIVE=ON
ARG WHISPER_CPU_FLAGS="-DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON"
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake git ca-certificates curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch ${WHISPER_REF} https://github.com/ggml-org/whisper.cpp.git /src
WORKDIR /src
RUN if [ "${WHISPER_NATIVE}" = "ON" ]; then CPU="-DGGML_NATIVE=ON"; else CPU="-DGGML_NATIVE=OFF ${WHISPER_CPU_FLAGS}"; fi \
    && cmake -B build -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DWHISPER_BUILD_TESTS=OFF $CPU \
    && cmake --build build -j"$(nproc)" --target whisper-cli whisper-vad-speech-segments \
    && mkdir -p /whisper/bin /whisper/models \
    && cp build/bin/whisper-cli build/bin/whisper-vad-speech-segments /whisper/bin/
RUN curl -fsSL -o /whisper/models/ggml-large-v3-turbo-q5_0.bin \
        https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin \
    && curl -fsSL -o /whisper/models/ggml-silero-v5.1.2.bin \
        https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin

# ---- runtime --------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm
# Noto fonts cover Lao, Khmer, Myanmar, Thai, Vietnamese (core) and Chinese (cjk) subtitles.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libgomp1 fonts-noto-core fonts-noto-cjk fontconfig \
    && rm -rf /var/lib/apt/lists/* && fc-cache -f
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app backend/app
COPY --from=web /web/dist web/dist
COPY --from=whisper /whisper tools/whisper

ENV DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/meta', timeout=4)"
# One worker only: the job queue lives in-process, a second worker would run jobs twice.
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
