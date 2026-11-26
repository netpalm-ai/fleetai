FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY auth/pyproject.toml .
RUN python -c "import pathlib, subprocess, tomllib; subprocess.check_call(['pip', 'install', '--no-cache-dir', *tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['dependencies']])"

COPY backend/db.py backend/emails.py ./
COPY backend/auth ./auth
COPY backend/migrations ./migrations
COPY auth/main.py ./

RUN useradd --create-home --uid 1000 auth \
    && chown -R auth:auth /app
USER auth

ENV PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--forwarded-allow-ips", "*"]
