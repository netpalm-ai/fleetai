FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN python -c "import pathlib, subprocess, tomllib; subprocess.check_call(['pip', 'install', '--no-cache-dir', *tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['dependencies']])"

COPY api.py config.py connections.py db.py emails.py intakes.py llm.py orchestrator.py parser.py solver.py verifier.py ./
COPY auth ./auth
COPY migrations ./migrations
COPY codebase ./codebase

RUN useradd --create-home --uid 1000 fleetai \
    && mkdir -p /product /projects \
    && chown -R fleetai:fleetai /app /product /projects
USER fleetai

ENV PYTHONUNBUFFERED=1
ENV FLEETAI_PRODUCT_ROOT=/product
ENV FLEETAI_PROJECTS=/projects

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--forwarded-allow-ips", "*"]
