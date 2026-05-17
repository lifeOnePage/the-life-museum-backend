"""
VideoTranscoderService — 720p faststart MP4 트랜스코딩 파이프라인.

Flow:
  1. Google Photos =dv URL → httpx 스트리밍 다운로드 (임시 파일)
  2. FFmpeg 트랜스코딩: scale=-2:720, libx264, crf 23, preset fast, movflags +faststart
  3. R2 업로드 (videos/{uuid}.mp4), Cache-Control 1년
  4. DB video_cache 레코드 업데이트 (ready 상태)
"""

import asyncio
import hashlib
import logging
import os
import tempfile
import uuid
from pathlib import Path

import httpx

from app.config import settings
from app.services.storage import R2StorageService

logger = logging.getLogger(__name__)

# Limit concurrent transcoding to prevent memory exhaustion on Railway
_transcode_semaphore = asyncio.Semaphore(2)


def compute_source_url_hash(url: str) -> str:
    """Compute SHA256 hash of the base lh3 URL (strip query params & =dv suffix)."""
    # Google Photos lh3 URLs: https://lh3.googleusercontent.com/...=dv
    # Strip the =dv or any other parameter suffix to get stable base URL
    base = url.split("=")[0] if "=" in url else url
    return hashlib.sha256(base.encode()).hexdigest()


async def _download_video(url: str, dest: Path) -> int:
    """Stream-download video from URL to a local file. Returns file size in bytes."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            total = 0
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    f.write(chunk)
                    total += len(chunk)
    return total


async def _transcode_to_720p(input_path: Path, output_path: Path) -> float:
    """
    Transcode video to 720p faststart MP4.
    Returns duration in seconds.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vf", "scale=-2:720",
        "-c:v", "libx264",
        "-crf", "23",
        "-preset", "fast",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-f", "mp4",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(
            f"FFmpeg failed (code={proc.returncode}): {stderr.decode()[-500:]}"
        )

    # Extract duration from ffprobe
    duration = await _get_duration(output_path)
    return duration


async def _get_duration(path: Path) -> float:
    """Get video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except (ValueError, AttributeError):
        return 0.0


class VideoTranscoderService:
    def __init__(self):
        self.storage = R2StorageService()

    async def transcode_and_upload(
        self,
        source_url: str,
        record_id: uuid.UUID | None = None,
    ) -> dict:
        """
        Download, transcode to 720p, upload to R2.

        Returns dict with:
          source_url_hash, r2_url, original_size_bytes,
          optimized_size_bytes, duration_seconds
        """
        url_hash = compute_source_url_hash(source_url)

        async with _transcode_semaphore:
            with tempfile.TemporaryDirectory() as tmpdir:
                input_path = Path(tmpdir) / "input_video"
                output_path = Path(tmpdir) / "output.mp4"

                # 1. Download
                logger.info(
                    "Downloading video: hash=%s url=%s",
                    url_hash[:12],
                    source_url[:80],
                )
                original_size = await _download_video(source_url, input_path)
                logger.info(
                    "Downloaded: hash=%s size=%dMB",
                    url_hash[:12],
                    original_size // (1024 * 1024),
                )

                # 2. Transcode
                logger.info("Transcoding to 720p: hash=%s", url_hash[:12])
                duration = await _transcode_to_720p(input_path, output_path)
                optimized_size = output_path.stat().st_size
                logger.info(
                    "Transcoded: hash=%s size=%dMB duration=%.1fs (%.0f%% reduction)",
                    url_hash[:12],
                    optimized_size // (1024 * 1024),
                    duration,
                    (1 - optimized_size / original_size) * 100 if original_size else 0,
                )

                # 3. Upload to R2
                r2_key = f"videos/{uuid.uuid4()}.mp4"
                with open(output_path, "rb") as f:
                    video_bytes = f.read()

                self.storage.s3.put_object(
                    Bucket=self.storage.bucket_name,
                    Key=r2_key,
                    Body=video_bytes,
                    ContentType="video/mp4",
                    CacheControl="public, max-age=31536000, immutable",
                )

                r2_url = f"{self.storage.public_url}/{r2_key}"
                logger.info(
                    "Uploaded to R2: hash=%s url=%s",
                    url_hash[:12],
                    r2_url,
                )

                return {
                    "source_url_hash": url_hash,
                    "r2_url": r2_url,
                    "original_size_bytes": original_size,
                    "optimized_size_bytes": optimized_size,
                    "duration_seconds": duration,
                }
