# VISION AI - SRM TRP — free-tier container image
#
# Small variant of deploy/Dockerfile for free hosts such as Render (512 MB RAM),
# Railway and Koyeb. It is the SAME application code; only the optional vision
# extras are omitted, because CPU torch + Ultralytics + RapidOCR need roughly
# 1.5-2.5 GB and cannot fit in a 512 MB instance.
#
# Detection therefore reports unavailable at GET /api/detection/status, and
# /api/detection/scan returns a clear 503. Every other feature (dashboard,
# logs, analytics, drivers, buses, audit, exports, Firebase sign-in) works.
#
# Local build:
#   docker build -f deploy/render/Dockerfile -t srm-trp-free .
#   docker run --rm -p 10000:10000 --env-file .env -e PORT=10000 srm-trp-free

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=10000

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip \
 && pip install -r /tmp/requirements.txt

COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY deploy/render/entrypoint.sh /app/entrypoint.sh
RUN chmod 755 /app/entrypoint.sh

EXPOSE 10000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS "http://localhost:${PORT}/api/health" || exit 1

CMD ["/app/entrypoint.sh"]
