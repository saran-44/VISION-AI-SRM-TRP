from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_cloud_build_uses_a_manual_submission_safe_image_tag_and_timeout():
    config = (ROOT / "deploy" / "cloudbuild.yaml").read_text()
    lines = config.splitlines()
    assert "timeout: 1800s" in lines
    options = config.split("options:\n", 1)[1].split("\n\n", 1)[0]
    assert "timeout:" not in options

    # BUILD_ID is populated for both manual gcloud builds submit and triggers.
    # The declared image, build step and deployment must reference one tag.
    image = "${_REGION}-docker.pkg.dev/$PROJECT_ID/${_REPOSITORY}/${_SERVICE}:$BUILD_ID"
    assert config.count(image) == 3
    assert "$COMMIT_SHA" not in config
    assert "DATABASE_URL=database-url:latest" in config
    assert "PGSSLROOTCERT=/secrets/supabase-ca.crt" in config
    assert "/secrets/supabase-ca.crt=supabase-ca:latest" in config
    assert "vision-ai-srmtrp.firebasestorage.app" in config
    assert "342e488e0ac2ee75b0f26b" in config


def test_cloud_build_sets_the_secure_first_deployment_path():
    config = (ROOT / "deploy" / "cloudbuild.yaml").read_text()
    assert "serviceAccount: projects/$PROJECT_ID/serviceAccounts/srm-trp-build@$PROJECT_ID.iam.gserviceaccount.com" in config
    assert "--service-account" in config
    assert "srm-trp-run@$PROJECT_ID.iam.gserviceaccount.com" in config
    assert "--network" in config and "srm-trp-vpc" in config
    assert "--subnet" in config and "srm-trp-subnet" in config
    assert "--vpc-egress" in config and "all-traffic" in config
    assert "--startup-probe" in config and "httpGet.path=/api/health" in config
    assert "^|^ENVIRONMENT=production" in config
    assert "FIREBASE_ALLOWED_PROVIDERS=password,google.com" in config
    assert "FIREBASE_AUTO_PROVISION=false" in config
    assert "LEGACY_PASSWORD_LOGIN_ENABLED=false" in config
    dockerfile = (ROOT / "deploy" / "Dockerfile").read_text()
    # Gunicorn must not kill a worker before the bounded PostgreSQL startup retry
    # window has allowed Direct VPC egress and Cloud NAT to become ready.
    assert '"--timeout", "180"' in dockerfile
    assert "periodSeconds=10,failureThreshold=24" in config
    assert "TRUSTED_PROXY_COUNT=0" in config


def test_dockerfile_runs_as_non_root_and_uses_single_worker_with_16_threads():
    dockerfile = (ROOT / "deploy" / "Dockerfile").read_text()
    assert "USER appuser" in dockerfile
    assert '"--workers", "1", "--threads", "16"' in dockerfile
    assert '"--timeout", "180"' in dockerfile
    assert "OMP_NUM_THREADS=1" in dockerfile
    assert "YOLO_CONFIG_DIR=/tmp/Ultralytics" in dockerfile

    render_dockerfile = (ROOT / "deploy" / "render" / "Dockerfile").read_text()
    assert "USER appuser" in render_dockerfile


def test_cloudbuild_sets_concurrency_limit():
    config = (ROOT / "deploy" / "cloudbuild.yaml").read_text()
    assert "--concurrency" in config
    assert '"16"' in config
    assert "SSE_MAX_CONNECTIONS=4" in config
    assert "SSE_MAX_SECONDS=50" in config
