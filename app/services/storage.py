import uuid

import boto3

from app.config import settings


class R2StorageService:
    def __init__(self):
        self.s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )
        self.bucket_name = settings.R2_BUCKET_NAME
        self.public_url = settings.R2_PUBLIC_URL

    async def upload_file(self, file_content: bytes, content_type: str, extension: str) -> str:
        key = f"covers/{uuid.uuid4()}.{extension}"

        self.s3.put_object(
            Bucket=self.bucket_name,
            Key=key,
            Body=file_content,
            ContentType=content_type,
        )

        return f"{self.public_url}/{key}"
