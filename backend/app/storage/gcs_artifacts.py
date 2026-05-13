from __future__ import annotations

from pathlib import Path

from google.cloud import storage

from app.models import Artifact


class GCSArtifactStore:
    def __init__(self, bucket_name: str):
        self.bucket_name = bucket_name
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)

    def upload_artifacts(self, run_id: str, artifacts: list[Artifact]) -> list[Artifact]:
        uploaded: list[Artifact] = []
        for artifact in artifacts:
            local_path = Path(artifact.path)
            if not local_path.exists():
                uploaded.append(artifact)
                continue
            blob_name = f"runs/{run_id}/artifacts/{local_path.name}"
            blob = self.bucket.blob(blob_name)
            blob.upload_from_filename(str(local_path))
            artifact.path = f"gs://{self.bucket_name}/{blob_name}"
            uploaded.append(artifact)
        return uploaded

    def download_to_file(self, gcs_uri: str, destination: Path) -> Path:
        bucket_name, blob_name = self._parse_uri(gcs_uri)
        bucket = self.client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(destination))
        return destination

    def delete_run_artifacts(self, run_id: str) -> int:
        prefix = f"runs/{run_id}/"
        deleted = 0
        for blob in self.client.list_blobs(self.bucket_name, prefix=prefix):
            blob.delete()
            deleted += 1
        return deleted

    @staticmethod
    def _parse_uri(gcs_uri: str) -> tuple[str, str]:
        if not gcs_uri.startswith("gs://"):
            raise ValueError(f"Unsupported GCS URI: {gcs_uri}")
        bucket_and_blob = gcs_uri.removeprefix("gs://")
        bucket_name, _, blob_name = bucket_and_blob.partition("/")
        if not bucket_name or not blob_name:
            raise ValueError(f"Unsupported GCS URI: {gcs_uri}")
        return bucket_name, blob_name
