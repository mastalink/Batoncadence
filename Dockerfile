# MCOrchestr8 gateway - runs anywhere a container runs (AWS/GCP/Azure/Fly/K8s).
FROM python:3.11-slim

WORKDIR /app

# Install the package first so layer caching survives doc-only changes.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Non-root runtime user; config/secret store lives in the mounted volume.
RUN useradd --create-home mco
USER mco
ENV HOME=/home/mco

EXPOSE 18789
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://127.0.0.1:18789/healthz', timeout=4).raise_for_status()"

# Credentials come from env (SUPABASE_URL/SUPABASE_KEY/...) or a mounted
# secret store; see docs/DEPLOYMENT.md.
CMD ["mco", "serve", "--host", "0.0.0.0", "--port", "18789"]
