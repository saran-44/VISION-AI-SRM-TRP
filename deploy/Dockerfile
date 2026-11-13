# SRM TRP Transport — backend container image
#
# Build:
#   docker build -f deploy/Dockerfile -t srm-trp-transport:latest .
#
# Run:
#   docker run -d --name srm-trp -p 8080:8080 --env-file .env.production \
#       srm-trp-transport:latest

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    HOME=/tmp \
    YOLO_CONFIG_DIR=/tmp/Ultralytics \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1

WORKDIR /app

# libGL is intentionally absent: the image uses opencv-python-headless.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY backend/requirements.txt /tmp/requirements.txt
RUN python -m venv "$VIRTUAL_ENV" \
 && pip install --upgrade pip \
 && pip install -r /tmp/requirements.txt \
 && rm -f /tmp/requirements.txt

# Vision extras are installed in a separate layer so the base image stays
# small when detection is not needed. Set INSTALL_VISION=0 to skip them.
ARG INSTALL_VISION=1
COPY backend/requirements-vision.txt /tmp/requirements-vision.txt
RUN if [ "$INSTALL_VISION" = "1" ]; then \
      pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        -r /tmp/requirements-vision.txt; \
    fi \
 && rm -f /tmp/requirements-vision.txt

COPY --chown=appuser:appuser backend/ /app/backend/
COPY --chown=appuser:appuser frontend/ /app/frontend/
COPY --chown=appuser:appuser best.pt /app/best.pt

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=130s --retries=3 \
  CMD curl -fsS http://localhost:8080/api/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "16", \
     "--worker-tmp-dir", "/dev/shm", "--timeout", "180", "--graceful-timeout", "30", \
     "--keep-alive", "5", "--access-logfile", "-", "backend.app:create_app()"]
