# VerifyFlow API and processing worker (same image, different command). Build from the repository root:
#   docker build -f backend/Dockerfile -t verifyflow-api:<version> backend
# NOT built or tested in this repository's environment (no container runtime was available); see docs/DEPLOYMENT.md.
FROM python:3.11.9-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Tesseract for OCR of scanned pages (English language data); nothing else from the OS is needed at runtime.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*

# Unprivileged user; document storage is a volume owned by it.
RUN groupadd --system --gid 10001 verifyflow \
 && useradd --system --uid 10001 --gid verifyflow --home-dir /app --shell /usr/sbin/nologin verifyflow \
 && mkdir -p /var/lib/verifyflow/storage \
 && chown -R verifyflow:verifyflow /var/lib/verifyflow

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY --chown=verifyflow:verifyflow alembic.ini ./
COPY --chown=verifyflow:verifyflow alembic ./alembic
COPY --chown=verifyflow:verifyflow app ./app

USER verifyflow
EXPOSE 8000

# Liveness: the process answers. Readiness (/api/v1/health/ready) is for the load balancer.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status == 200 else 1)"

# --proxy-headers with a restricted --forwarded-allow-ips so client IPs (throttling, audit) come from the proxy only.
# Workers: AI rate limits are per process (see README "Known limitations"); size workers to the host.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", \
     "--proxy-headers", "--forwarded-allow-ips", "172.16.0.0/12", "--no-server-header"]
