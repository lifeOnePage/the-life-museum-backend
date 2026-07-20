"""R2 버킷 CORS에 네이티브 앱 Origin을 추가한다 (기존 규칙 유지·병합, 재실행 안전).

실행: venv/bin/python scripts/update_r2_cors.py
적용 전 규칙을 출력하므로 문제 시 그 값으로 되돌릴 수 있다.
"""

import json
import sys
from pathlib import Path

import boto3

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402

# 웹(vercel/localhost:3000)은 기존 규칙에 이미 있음 — 앱 웹뷰 Origin을 추가
NEW_ORIGINS = [
    "capacitor://localhost",  # iOS WKWebView
    "https://localhost",      # Android WebView
]


def main():
    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )
    bucket = settings.R2_BUCKET_NAME

    try:
        current = s3.get_bucket_cors(Bucket=bucket)["CORSRules"]
    except s3.exceptions.ClientError as e:
        if "NoSuchCORSConfiguration" in str(e):
            current = []
        else:
            raise

    print("=== 적용 전 규칙 (백업용) ===")
    print(json.dumps(current, indent=2, ensure_ascii=False))

    rules = [dict(r) for r in current]
    existing_origins = {o for r in rules for o in r.get("AllowedOrigins", [])}
    to_add = [o for o in NEW_ORIGINS if o not in existing_origins]

    if not to_add:
        print("추가할 Origin 없음 — 이미 반영됨")
        return

    if rules:
        # 첫 규칙에 Origin만 추가 (메서드/헤더 등 기존 정책 유지)
        rules[0]["AllowedOrigins"] = rules[0].get("AllowedOrigins", []) + to_add
    else:
        rules = [
            {
                "AllowedOrigins": NEW_ORIGINS,
                "AllowedMethods": ["GET", "HEAD"],
                "AllowedHeaders": ["*"],
                "MaxAgeSeconds": 86400,
            }
        ]

    s3.put_bucket_cors(Bucket=bucket, CORSConfiguration={"CORSRules": rules})

    print("=== 적용 후 규칙 ===")
    print(json.dumps(s3.get_bucket_cors(Bucket=bucket)["CORSRules"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
