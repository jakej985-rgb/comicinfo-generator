FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    COMICINFO_HOST=0.0.0.0 \
    COMICINFO_PORT=5005 \
    COMICINFO_CONFIG=/config/config.yaml

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    p7zip-full \
    unrar-free \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Create volume mount points
RUN mkdir -p /config /comics /root/.comicinfo

EXPOSE 5005

VOLUME ["/config", "/comics"]

CMD ["python", "main.py", "5005"]
