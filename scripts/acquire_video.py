#!/usr/bin/env python3
"""Best-effort, cookie-free acquisition adapter for a public YouTube URL."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

YOUTUBE_HOSTS = {
    "youtu.be",
    "www.youtu.be",
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
}


def emit(payload: dict[str, object], status_file: Path | None = None) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    print(encoded)
    if status_file:
        status_file.parent.mkdir(parents=True, exist_ok=True)
        status_file.write_text(encoded + "\n", encoding="utf-8")


def classify_failure(message: str) -> str:
    lowered = message.lower()
    if any(
        token in lowered
        for token in ("http error 429", "too many requests", "captcha", "rate limit")
    ):
        return "source_rate_limited"
    if any(
        token in lowered
        for token in (
            "private video",
            "video unavailable",
            "video is not available",
            "not available in your country",
            "not available in your region",
            "age-restricted",
            "age restricted",
            "login required",
            "sign in to confirm",
            "members-only",
        )
    ):
        return "source_unavailable"
    return "media_required"


def is_youtube_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and (parsed.hostname or "").lower() in YOUTUBE_HOSTS
    )


def probe(path: Path) -> dict[str, object]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is required to validate the acquired media")
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "format=duration:stream=width,height,codec_name",
        "-of",
        "json",
        str(path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode:
        detail = completed.stderr.strip() or "ffprobe could not decode the file"
        raise RuntimeError(detail)
    data = json.loads(completed.stdout)
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError("the acquired file has no video stream")
    duration = float((data.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise RuntimeError("the acquired file has no positive duration")
    stream = streams[0]
    return {
        "duration_seconds": duration,
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "codec": stream.get("codec_name"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Attempt cookie-free YouTube media acquisition with an installed yt-dlp."
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--status-file", type=Path)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    status_file = args.status_file or args.output_dir / "acquisition-status.json"

    if not is_youtube_url(args.url):
        emit(
            {
                "status": "unsupported_source",
                "source_url": args.url,
                "message": "Only YouTube URLs are supported by this optional adapter; supply a local video file.",
            },
            status_file,
        )
        return 2

    sibling_yt_dlp = Path(sys.executable).parent / "yt-dlp"
    yt_dlp = shutil.which("yt-dlp") or (
        str(sibling_yt_dlp) if sibling_yt_dlp.is_file() else None
    )
    if not yt_dlp:
        emit(
            {
                "status": "media_required",
                "source_url": args.url,
                "message": "yt-dlp is not installed. Supply a local video file, or independently install yt-dlp for a best-effort retry.",
            },
            status_file,
        )
        return 2

    output_template = str(args.output_dir / "source.%(ext)s")
    command = [
        yt_dlp,
        "--no-playlist",
        "--no-write-comments",
        "--no-write-info-json",
        "--no-write-thumbnail",
        "--format",
        "bv*+ba/b",
        "--merge-output-format",
        "mp4",
        "--output",
        output_template,
        args.url,
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    combined_output = "\n".join(
        part for part in (completed.stdout, completed.stderr) if part
    ).strip()
    if completed.returncode:
        outcome = classify_failure(combined_output)
        emit(
            {
                "status": outcome,
                "source_url": args.url,
                "message": "YouTube media acquisition did not produce a usable file. Supply a local video file.",
                "adapter_detail": combined_output[-4000:],
            },
            status_file,
        )
        return 2

    candidates = sorted(
        path
        for path in args.output_dir.glob("source.*")
        if path.is_file() and path != status_file and not path.name.endswith(".part")
    )
    if not candidates:
        emit(
            {
                "status": "media_required",
                "source_url": args.url,
                "message": "The adapter exited successfully but no media file was found. Supply a local video file.",
            },
            status_file,
        )
        return 2

    media_path = max(candidates, key=lambda item: item.stat().st_size)
    try:
        media = probe(media_path)
    except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
        emit(
            {
                "status": "media_required",
                "source_url": args.url,
                "message": f"The acquired file failed media validation: {exc}",
            },
            status_file,
        )
        return 2

    emit(
        {
            "status": "ok",
            "source_url": args.url,
            "video_file": str(media_path.resolve()),
            "media": media,
            "message": "Best-effort media acquisition succeeded; this does not establish reproduction rights.",
        },
        status_file,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
