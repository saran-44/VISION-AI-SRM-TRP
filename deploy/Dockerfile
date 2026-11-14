# VISION AI - SRM TRP — backend container image
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
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# libGL is intentionally absent: the image uses opencv-python-headless.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /tmp/requirements.txt
RUN python -m venv "$VIRTUAL_ENV" \
 && "$VIRTUAL_ENV/bin/python" -m pip install --upgrade pip \
 && "$VIRTUAL_ENV/bin/python" -m pip install -r /tmp/requirements.txt

# Vision extras are installed in a separate layer so the base image stays
# small when detection is not needed. Set INSTALL_VISION=0 to skip them.
ARG INSTALL_VISION=1
COPY backend/requirements-vision.txt /tmp/requirements-vision.txt
RUN if [ "$INSTALL_VISION" = "1" ]; then \
      "$VIRTUAL_ENV/bin/python" -m pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        -r /tmp/requirements-vision.txt; \
    fi

COPY backend/ /app/backend/
COPY frontend/ /app/frontend/
COPY best.pt /app/best.pt
COPY anpr_best.pt /app/anpr_best.pt
COPY scripts/fetch_vehicle_model.py /app/scripts/fetch_vehicle_model.py
RUN if [ "$INSTALL_VISION" = "1" ]; then \
      "$VIRTUAL_ENV/bin/python" /app/scripts/fetch_vehicle_model.py; \
    fi

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:8080/api/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", \
     "--timeout", "180", "--access-logfile", "-", "backend.app:create_app()"]
