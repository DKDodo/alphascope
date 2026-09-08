FROM python:3.12-slim

WORKDIR /app

# build-essential covers any dependency (e.g. curl_cffi, a yfinance
# transitive dep) that doesn't ship a manylinux wheel for this Python/arch
# combination and needs to compile from source.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Lightweight web deploy: no torch/transformers (see requirements-web.txt)
# to fit free-tier RAM/disk. News headlines still work; sentiment scoring
# degrades to UNAVAILABLE. The desktop build (build_exe.bat) uses the full
# requirements.txt with FinBERT and is unaffected by this file.
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY app ./app

# Runtime-only environment: real (delayed) Yahoo Finance data for both
# Global and BIST + news, no API keys, live trading impossible (also
# enforced in app/config.py).
ENV ALPHASCOPE_ENV=production \
    MARKET_DATA_PROVIDER=yfinance \
    PAPER_TRADING_ONLY=true \
    LIVE_TRADING_ENABLED=false \
    PYTHONUNBUFFERED=1

# Most PaaS hosts (Render, Fly.io, etc.) inject their own $PORT; falls back
# to 7860 for hosts that don't (e.g. Hugging Face Spaces' convention).
EXPOSE 7860

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
