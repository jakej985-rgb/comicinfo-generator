FROM python:3.11-slim

LABEL org.opencontainers.image.title="ComicInfo Generator & Tagger"
LABEL org.opencontainers.image.description="A web app and CLI tool to scrape comic metadata from Comic Vine and GCP, convert .cbr to .cbz, and embed ComicInfo.xml metadata files."
LABEL org.opencontainers.image.url="https://github.com/jakej985-rgb/comicinfo-generator"
LABEL org.opencontainers.image.source="https://github.com/jakej985-rgb/comicinfo-generator"
LABEL org.opencontainers.image.licenses="MIT"

# Install system utilities for archive extraction (RAR/CBR, ZIP/CBZ)
RUN apt-get update && apt-get install -y --no-install-recommends \
    unar \
    p7zip-full \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . /app/

# Ensure execution permissions on bundled unrar binary if present
RUN chmod +x /app/bin/unrar 2>/dev/null || true

# Default environment port
ENV PORT=5005

EXPOSE 5005

# Run Web UI server on port 5005
CMD ["python", "main.py", "--web", "5005"]
