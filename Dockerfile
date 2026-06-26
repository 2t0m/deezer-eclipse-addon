# Deezer Eclipse Addon - Production Docker Image
FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .

# Expose port
EXPOSE 3000

# Environment variables (override with .env or docker run -e)
ENV DEEZER_ARL=""
ENV API_KEY=""
ENV PORT=3000

# Create deemix temp directory
RUN mkdir -p /tmp/deemix-imgs

# Run with Gunicorn (production WSGI server)
# --workers 2: Two worker processes
# --threads 4: Four threads per worker = 8 concurrent requests
# --timeout 120: Long timeout for streaming
# --access-logfile -: Log HTTP requests to stdout
# --error-logfile -: Log errors to stdout
# --capture-output: Capture print() statements
CMD ["gunicorn", "--bind", "0.0.0.0:3000", "--workers", "2", "--threads", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "--capture-output", "app:app"]
