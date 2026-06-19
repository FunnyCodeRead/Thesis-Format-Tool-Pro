from __future__ import annotations

from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
JSON_MIME_TYPE = "application/json"


class R2StorageError(RuntimeError):
    pass


def build_original_document_key(user_id: str, document_id: str) -> str:
    return f"users/{user_id}/documents/{document_id}/original.docx"


def build_fixed_document_key(user_id: str, document_id: str) -> str:
    return f"users/{user_id}/documents/{document_id}/fixed.docx"


def build_report_document_key(user_id: str, document_id: str) -> str:
    return f"users/{user_id}/documents/{document_id}/report.json"


def build_annotated_document_key(user_id: str, document_id: str) -> str:
    return f"users/{user_id}/documents/{document_id}/annotated-report.docx"


def build_annotated_report_document_key(user_id: str, document_id: str) -> str:
    return build_annotated_document_key(user_id, document_id)


class R2StorageClient:
    def __init__(self) -> None:
        missing = [
            name
            for name, value in [
                ("R2_ACCOUNT_ID", settings.r2_account_id),
                ("R2_ACCESS_KEY_ID", settings.r2_access_key_id),
                ("R2_SECRET_ACCESS_KEY", settings.r2_secret_access_key),
                ("R2_BUCKET_NAME", settings.r2_bucket_name),
            ]
            if not value
        ]
        if missing:
            raise R2StorageError(
                f"Missing R2 configuration: {', '.join(missing)}"
            )

        self._bucket_name = settings.r2_bucket_name
        self._client = boto3.client(
            service_name="s3",
            endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )

    def upload_bytes(
        self,
        *,
        object_key: str,
        content: bytes,
        content_type: str = DOCX_MIME_TYPE,
    ) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket_name,
                Key=object_key,
                Body=content,
                ContentType=content_type,
            )
        except (BotoCoreError, ClientError) as exc:
            raise R2StorageError(f"Failed to upload object {object_key}.") from exc

    def download_bytes(self, object_key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket_name, Key=object_key)
            return response["Body"].read()
        except (BotoCoreError, ClientError) as exc:
            raise R2StorageError(f"Failed to download object {object_key}.") from exc

    def delete_object(self, object_key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket_name, Key=object_key)
        except (BotoCoreError, ClientError) as exc:
            raise R2StorageError(f"Failed to delete object {object_key}.") from exc


@lru_cache(maxsize=1)
def get_r2_storage_client() -> R2StorageClient:
    return R2StorageClient()
