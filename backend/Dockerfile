FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download spaCy Italian model
RUN python -m spacy download it_core_news_sm

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p logs data

# Single worker, up to four pipelines at a time. The slow sync LLM stages run
# in threads, so concurrent pipelines no longer block each other (load test
# of 23/10/2026 on Fascicoli, same pipeline: 4 together take 43-59 s each).
# Both values can be overridden at runtime via env vars.
ENV WORKERS=1
ENV MAX_CONCURRENT_PIPELINES=4

# NOTE: keep 0.0.0.0 — Railway's public edge reaches the container over IPv4;
# binding :: makes the socket IPv6-only here and breaks public routing (502).
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WORKERS}
