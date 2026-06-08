FROM python:3.11

# Install system dependencies
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Set chromium/chromedriver paths for the app
ENV CHROMIUM_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Ensure Python output is not buffered (logs visible immediately)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["sh", "-c", "echo '[BOOT] alembic start' && alembic upgrade head 2>&1 && echo '[BOOT] alembic done' && echo '[BOOT] testing import...' && python -c 'from app.main import app; print(\"[BOOT] import OK\")' && echo \"[BOOT] starting uvicorn on port ${PORT:-8080}\" && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
