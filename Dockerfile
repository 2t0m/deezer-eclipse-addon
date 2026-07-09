# Deezer Eclipse Addon - Production Docker Image
FROM python:3.13-slim

# Build argument to invalidate cache
ARG CACHEBUST=1

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py helpers.py crypto.py ./
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
CMD ["gunicorn", "--bind", "0.0.0.0:3000", "--workers", "1", "--threads", "4", "--timeout", "300", "--access-logfile", "-", "--capture-output", "app:app"]
