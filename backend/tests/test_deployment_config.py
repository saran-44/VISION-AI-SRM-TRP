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
    assert "MONGO_DB_NAME=srmtrpai" in config
    assert "MONGO_URI=mongo-uri:latest" in config
