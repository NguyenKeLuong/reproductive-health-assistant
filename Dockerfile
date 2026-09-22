# ─────────────────────────────────────────────────────────
# Stage 1: Build React Frontend
# ─────────────────────────────────────────────────────────
FROM node:20-alpine AS frontend-builder
WORKDIR /app/health-chat-companion

# 1a. Install deps (cached as long as package*.json unchanged)
COPY health-chat-companion/package*.json ./
RUN npm ci

# 1b. Copy source + build
COPY health-chat-companion/ ./
ENV VITE_BACKEND_URL="/"
RUN npm run build

# ─────────────────────────────────────────────────────────
# Stage 2: Python backend + serve frontend
# ─────────────────────────────────────────────────────────
FROM python:3.11-slim
WORKDIR /app

# System deps: only ffmpeg (for audio conversion), no build-essential needed
# (torch, ctranslate2, transformers all ship pre-built wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps (heaviest layers first for better cache reuse) ──

# Layer A: CPU-only PyTorch (~200MB) — cached unless this line changes
RUN pip install --no-cache-dir \
    torch \
    --index-url https://download.pytorch.org/whl/cpu

# Layer B: HuggingFace stack
RUN pip install --no-cache-dir \
    transformers>=4.40.0 \
    numpy>=1.24.0

# Layer C: Whisper STT
RUN pip install --no-cache-dir \
    faster-whisper>=1.0.0

# Layer D: Web / app deps (changes most often — put last)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Pre-download model weights into the image at build time ──
# This bakes the models in, so container startup is instant (no cold-download)
RUN python -c "\
from transformers import VitsModel, AutoTokenizer; \
print('Downloading facebook/mms-tts-vie...'); \
VitsModel.from_pretrained('facebook/mms-tts-vie'); \
AutoTokenizer.from_pretrained('facebook/mms-tts-vie'); \
print('TTS model ready.')"

RUN python -c "\
from faster_whisper import WhisperModel; \
print('Downloading faster-whisper base...'); \
WhisperModel('base', device='cpu', compute_type='int8'); \
print('Whisper model ready.')"

# ── Application code (copy last so code changes don't bust model cache) ──
COPY backend/ ./backend/
COPY main.py ./

# ── Frontend static files from Stage 1 ──
COPY --from=frontend-builder /app/health-chat-companion/dist ./health-chat-companion/dist

EXPOSE 8010
ENV PYTHONUNBUFFERED=1

CMD ["python", "main.py"]
