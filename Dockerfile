# Deezer Eclipse Addon - Production Docker Image
FROM python:3.13-slim

# Build argument to invalidate cache
ARG CACHEBUST=1

WORKDIR /app

# Install Chrome/Chromium and dependencies for Selenium (ARL auto-refresh)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    unzip \
    curl \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Set Chrome binary location for Selenium
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py helpers.py crypto.py arl_manager.py ./
COPY routes/ ./routes/

# Expose port
EXPOSE 3000

# Environment variables (override with .env or docker run -e)
ENV DEEZER_ARL=""
ENV API_KEY=""
ENV PORT=3000

# Create directories
RUN mkdir -p /tmp/deemix-imgs /app/config

# Run with Gunicorn (production WSGI server)
# --workers 1: Single worker process
# --threads 4: Four threads = 4 concurrent requests
# --timeout 120: Long timeout for streaming
# --access-logfile: Enabled in DEBUG mode, disabled in NORMAL mode
# --capture-output: Capture print() statements
CMD if [ "$DEBUG" = "true" ]; then \
      gunicorn --bind 0.0.0.0:3000 --workers 1 --threads 4 --timeout 120 --access-logfile - --error-logfile - --capture-output app:app; \
    else \
      gunicorn --bind 0.0.0.0:3000 --workers 1 --threads 4 --timeout 120 --access-logfile /dev/null --error-logfile - --capture-output app:app; \
    fi
