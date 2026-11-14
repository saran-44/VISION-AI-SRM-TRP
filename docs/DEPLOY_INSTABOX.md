# InstaBox full-vision deployment

This deployment runs the complete Flask API, frontend, OCR, sticker detector,
ANPR fallback, and vehicle classifier on one InstaBox Linux sandbox.

## Important limitation

The attached InstaBox guide states that free sandboxes have an 8-hour
continuous runtime limit followed by a 3–5 minute cooldown. Do not use the
keepalive script to bypass that provider limit. This is suitable for testing
or an office shift, not unattended 24/7 production. The Windows gate agent
remains the reliable always-on detector when the cloud sandbox is unavailable.

## Use one sandbox

The 10-node cluster in the guide is unnecessary for this application. One
sandbox with approximately 4 vCPUs and 8 GB RAM is sufficient for the current
CPU vision image.

After connecting to the sandbox:

```bash
git clone https://github.com/saran-44/VISION-AI-SRM-TRP.git
cd VISION-AI-SRM-TRP
cp deploy/instabox/.env.instabox.example deploy/instabox/.env.instabox
chmod 600 deploy/instabox/.env.instabox
# Copy the Supabase CA certificate downloaded from Project Settings here.
cp /path/to/prod-ca-2021.crt deploy/instabox/supabase-ca.crt
chmod 600 deploy/instabox/supabase-ca.crt
```

Edit the private environment file with the Supabase pooler URL, CA certificate
path, Firebase API key, JWT secret, and device key. Never paste those
values into chat or commit the file.

The full image includes the pinned vision dependencies and downloads the
COCO vehicle checkpoint during the Docker build:

```bash
docker compose -f deploy/instabox/docker-compose.yml \
  --env-file deploy/instabox/.env.instabox build
docker compose -f deploy/instabox/docker-compose.yml up -d
curl -fsS http://127.0.0.1:8080/api/health
```

Open port `8080` only through an HTTPS reverse proxy or a protected tunnel.
Do not expose the Flask port directly to the public internet. Configure the
camera HLS/MJPEG URLs in `CAMERA_STREAM_URLS` if browser camera previews are
needed. Raw RTSP still requires a gateway such as MediaMTX or an NVR HLS
output.

Verify that `/api/detection/status` reports Pillow, Torch, Ultralytics,
OpenCV, OCR, `best.pt`, `anpr_best.pt`, and the vehicle model as available
before enabling automatic scans.
