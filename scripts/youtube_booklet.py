#!/usr/bin/env python3
"""Extract Frame Cue candidates and create an imposed home-print booklet PDF."""

from __future__ import annotations

import argparse
import io
import json
import math
import shutil
import subprocess
import sys
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import (
        Image,
        ImageDraw,
        ImageFilter,
        ImageFont,
        ImageOps,
        ImageStat,
        features,
    )
except ImportError as exc:  # pragma: no cover - exercised by users without dependencies
    raise SystemExit(
        "Pillow is required. Run: python3 -m pip install -r requirements.txt"
    ) from exc

try:
    import arabic_reshaper
    from bidi.algorithm import get_display as bidi_display
except ImportError:  # pragma: no cover - checked only for RTL fallback
    arabic_reshaper = None
    bidi_display = None

try:
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
except ImportError as exc:  # pragma: no cover - exercised by users without dependencies
    raise SystemExit(
        "ReportLab is required. Run: python3 -m pip install -r requirements.txt"
    ) from exc


SCHEMA_VERSION = 1
PAPERS_INCHES = {
    "letter": (11.0, 8.5),
    "a4": (11.692913, 8.267717),
}
DEFAULT_OFFSETS = (-0.30, -0.15, 0.0, 0.15, 0.30)
POINTS_PER_INCH = 72.0


class BookletError(RuntimeError):
    pass


@dataclass(frozen=True)
class Cue:
    source_line: int
    timestamp: str
    seconds: float
    text: str


def parse_timestamp(value: str) -> float:
    raw = value.strip()
    if not raw:
        raise ValueError("timestamp is empty")
    parts = raw.split(":")
    if len(parts) > 3:
        raise ValueError(f"invalid timestamp {value!r}")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError(f"invalid timestamp {value!r}") from exc
    if any(number < 0 for number in numbers):
        raise ValueError(f"timestamp must be non-negative: {value!r}")
    if len(numbers) > 1 and any(number >= 60 for number in numbers[1:]):
        raise ValueError(f"minutes and seconds must be below 60: {value!r}")
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    if not math.isfinite(seconds):
        raise ValueError(f"invalid timestamp {value!r}")
    return seconds


def parse_cues(path: Path) -> list[Cue]:
    cues: list[Cue] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            timestamp, page_text = line.split("|", 1)
        elif "\t" in raw_line:
            timestamp, page_text = raw_line.split("\t", 1)
        else:
            timestamp, page_text = line, ""
        timestamp = timestamp.strip()
        try:
            seconds = parse_timestamp(timestamp)
        except ValueError as exc:
            raise BookletError(f"{path}:{line_number}: {exc}") from exc
        cues.append(
            Cue(
                source_line=line_number,
                timestamp=timestamp,
                seconds=seconds,
                text=page_text.strip().replace("\\n", "\n"),
            )
        )
    if not cues:
        raise BookletError(f"{path} contains no Frame Cues")
    return cues


def run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def probe_video(path: Path) -> dict[str, object]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise BookletError("ffprobe is required but was not found on PATH")
    completed = run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "format=duration:stream=width,height,avg_frame_rate,codec_name",
            "-of",
            "json",
            str(path),
        ]
    )
    if completed.returncode:
        raise BookletError(completed.stderr.strip() or f"ffprobe could not read {path}")
    try:
        data = json.loads(completed.stdout)
        streams = data.get("streams") or []
        stream = streams[0]
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (json.JSONDecodeError, IndexError, TypeError, ValueError) as exc:
        raise BookletError(f"ffprobe returned incomplete metadata for {path}") from exc
    if duration <= 0:
        raise BookletError(f"{path} has no positive video duration")
    return {
        "duration_seconds": duration,
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "frame_rate": stream.get("avg_frame_rate"),
        "codec": stream.get("codec_name"),
    }


def extract_frame(video: Path, timestamp: float, output: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise BookletError("ffmpeg is required but was not found on PATH")
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{timestamp:.6f}",
            "-i",
            str(video),
            "-map",
            "0:v:0",
            "-frames:v",
            "1",
            "-an",
            "-sn",
            str(output),
        ]
    )
    if completed.returncode or not output.exists():
        detail = completed.stderr.strip() or "no image was written"
        raise BookletError(f"frame extraction failed at {timestamp:.3f}s: {detail}")


def score_frame(path: Path, cue_seconds: float, timestamp: float) -> float:
    with Image.open(path) as opened:
        gray = ImageOps.grayscale(opened)
        thumbnail = ImageOps.contain(gray, (640, 360), Image.Resampling.LANCZOS)
        stats = ImageStat.Stat(thumbnail)
        mean = stats.mean[0]
        contrast = math.sqrt(stats.var[0])
        edge_stats = ImageStat.Stat(thumbnail.filter(ImageFilter.FIND_EDGES))
        edge_energy = edge_stats.var[0]
    exposure_penalty = max(0.0, 18.0 - mean) * 2.0 + max(0.0, mean - 238.0) * 2.0
    distance_penalty = abs(timestamp - cue_seconds) * 12.0
    return edge_energy + contrast * 0.35 - exposure_penalty - distance_penalty


def relative_to(path: Path, directory: Path) -> str:
    return str(path.resolve().relative_to(directory.resolve()))


def find_font(explicit: Path | None = None) -> Path:
    if explicit:
        resolved = explicit.expanduser().resolve()
        if not resolved.is_file():
            raise BookletError(f"font file does not exist: {resolved}")
        return resolved
    candidates = [
        Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSans-Regular.ttf"),
        Path("C:/Windows/Fonts/arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    fc_match = shutil.which("fc-match")
    if fc_match:
        completed = run([fc_match, "-f", "%{file}", "sans-serif"])
        matched = Path(completed.stdout.strip())
        if completed.returncode == 0 and matched.is_file():
            return matched
    raise BookletError(
        "no usable TrueType/OpenType font was found; pass --font /path/to/font.ttf"
    )


def contact_font(size: int = 18) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(find_font()), size)
    except (BookletError, OSError):
        return ImageFont.load_default()


def make_page_contact_sheet(
    page: dict[str, object], manifest_dir: Path, output: Path
) -> None:
    candidates = page["candidates"]
    assert isinstance(candidates, list)
    cell_width, image_height, caption_height = 330, 186, 64
    sheet = Image.new(
        "RGB", (cell_width * len(candidates), image_height + caption_height), "white"
    )
    draw = ImageDraw.Draw(sheet)
    font = contact_font(16)
    selected = int(page["selected_candidate"])
    for index, candidate in enumerate(candidates, start=1):
        assert isinstance(candidate, dict)
        image_path = manifest_dir / str(candidate["image"])
        with Image.open(image_path) as opened:
            thumb = ImageOps.contain(
                opened.convert("RGB"), (cell_width - 10, image_height - 10)
            )
        x = (index - 1) * cell_width + (cell_width - thumb.width) // 2
        y = (image_height - thumb.height) // 2
        sheet.paste(thumb, (x, y))
        color = "#0B6E4F" if index == selected else "#333333"
        if page.get("page_kind") == "cover":
            label = "Published thumbnail cover"
        else:
            label = f"Candidate {index}  {float(candidate['timestamp_seconds']):.3f}s"
        if index == selected:
            label += "  SELECTED"
        draw.text(
            ((index - 1) * cell_width + 10, image_height + 8),
            label,
            fill=color,
            font=font,
        )
        detail = (
            "YouTube published image"
            if page.get("page_kind") == "cover"
            else f"offset {float(candidate['offset_seconds']):+.2f}s"
        )
        draw.text(
            ((index - 1) * cell_width + 10, image_height + 34),
            detail,
            fill="#666666",
            font=font,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92)


def make_selected_overview(manifest: dict[str, object], manifest_path: Path) -> None:
    pages = manifest["pages"]
    assert isinstance(pages, list)
    manifest_dir = manifest_path.parent
    thumb_w, thumb_h = 360, 203
    label_h = 42
    columns = 3
    rows = math.ceil(len(pages) / columns)
    sheet = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    font = contact_font(17)
    for position, page in enumerate(pages):
        assert isinstance(page, dict)
        candidates = page["candidates"]
        assert isinstance(candidates, list)
        selected = int(page["selected_candidate"])
        candidate = candidates[selected - 1]
        assert isinstance(candidate, dict)
        with Image.open(manifest_dir / str(candidate["image"])) as opened:
            thumb = ImageOps.fit(
                opened.convert("RGB"),
                (thumb_w - 8, thumb_h - 8),
                method=Image.Resampling.LANCZOS,
            )
        column = position % columns
        row = position // columns
        x = column * thumb_w + 4
        y = row * (thumb_h + label_h) + 4
        sheet.paste(thumb, (x, y))
        label = (
            "Page 1 - published thumbnail cover"
            if page.get("page_kind") == "cover"
            else f"Page {int(page['page_number'])} - {float(candidate['timestamp_seconds']):.3f}s"
        )
        draw.text(
            (column * thumb_w + 10, y + thumb_h),
            label,
            fill="#222222",
            font=font,
        )
    output = manifest_dir / "review" / "selected-pages.jpg"
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92)


def save_manifest(manifest: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def load_manifest(path: Path) -> dict[str, object]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BookletError(f"could not read manifest {path}: {exc}") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise BookletError(f"unsupported manifest schema in {path}")
    pages = manifest.get("pages")
    if not isinstance(pages, list) or not pages:
        raise BookletError(f"manifest {path} contains no pages")
    for expected, page in enumerate(pages, start=1):
        if not isinstance(page, dict) or page.get("page_number") != expected:
            raise BookletError(f"manifest page order is invalid at page {expected}")
        candidates = page.get("candidates")
        selected = page.get("selected_candidate")
        if not isinstance(candidates, list) or not candidates:
            raise BookletError(f"manifest page {expected} contains no candidates")
        if not isinstance(selected, int) or not 1 <= selected <= len(candidates):
            raise BookletError(
                f"manifest page {expected} has an invalid selected candidate"
            )
    return manifest


def format_seconds(seconds: float) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{int(hours):02d}:{int(minutes):02d}:{secs:06.3f}"
    return f"{int(minutes):02d}:{secs:06.3f}"


def command_extract(args: argparse.Namespace) -> int:
    video = args.video.expanduser().resolve()
    if not video.is_file():
        raise BookletError(f"video file does not exist: {video}")
    cues_path = args.cues.expanduser().resolve()
    if not cues_path.is_file():
        raise BookletError(f"cue file does not exist: {cues_path}")
    cues = parse_cues(cues_path)
    media = probe_video(video)
    duration = float(media["duration_seconds"])
    invalid = [cue for cue in cues if cue.seconds >= duration]
    if invalid:
        details = ", ".join(
            f"line {cue.source_line} ({cue.timestamp})" for cue in invalid
        )
        raise BookletError(
            f"Frame Cues outside the {format_seconds(duration)} video duration: {details}"
        )

    work_dir = args.work_dir.expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    offsets = tuple(
        float(value.strip()) for value in args.offsets.split(",") if value.strip()
    )
    if not offsets:
        raise BookletError("--offsets must contain at least one number")

    pages: list[dict[str, object]] = []
    for page_number, cue in enumerate(cues, start=1):
        page_dir = work_dir / "frames" / f"page-{page_number:03d}"
        unique_times: list[tuple[float, float]] = []
        for offset in offsets:
            timestamp = min(max(cue.seconds + offset, 0.0), max(duration - 0.001, 0.0))
            if all(abs(timestamp - prior[0]) > 0.0005 for prior in unique_times):
                unique_times.append((timestamp, timestamp - cue.seconds))
        candidates: list[dict[str, object]] = []
        for candidate_number, (timestamp, actual_offset) in enumerate(
            unique_times, start=1
        ):
            output = page_dir / f"candidate-{candidate_number:02d}.png"
            extract_frame(video, timestamp, output)
            score = score_frame(output, cue.seconds, timestamp)
            candidates.append(
                {
                    "candidate_number": candidate_number,
                    "timestamp_seconds": round(timestamp, 6),
                    "offset_seconds": round(actual_offset, 6),
                    "sharpness_score": round(score, 4),
                    "image": relative_to(output, work_dir),
                }
            )
        selected = (
            max(
                range(len(candidates)),
                key=lambda index: float(candidates[index]["sharpness_score"]),
            )
            + 1
        )
        pages.append(
            {
                "page_number": page_number,
                "source_line": cue.source_line,
                "frame_cue": cue.timestamp,
                "cue_seconds": cue.seconds,
                "text": cue.text,
                "selected_candidate": selected,
                "candidates": candidates,
            }
        )

    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "video_file": str(video),
            "source_url": args.source_url,
            **media,
        },
        "book": {
            "title": args.title or "",
            "language": args.language or "",
        },
        "pages": pages,
    }
    manifest_path = work_dir / "manifest.json"
    save_manifest(manifest, manifest_path)
    for page in pages:
        make_page_contact_sheet(
            page,
            work_dir,
            work_dir / "review" / f"page-{int(page['page_number']):03d}.jpg",
        )
    make_selected_overview(manifest, manifest_path)
    print(
        json.dumps(
            {
                "status": "ok",
                "manifest": str(manifest_path),
                "review_directory": str(work_dir / "review"),
                "authored_pages": len(pages),
            },
            indent=2,
        )
    )
    return 0


def validate_image(path: Path, label: str) -> None:
    if not path.is_file():
        raise BookletError(f"{label} does not exist: {path}")
    try:
        with Image.open(path) as opened:
            opened.verify()
    except (OSError, SyntaxError) as exc:
        raise BookletError(f"{label} is not a readable image: {path}") from exc


def command_import_frames(args: argparse.Namespace) -> int:
    cues_path = args.cues.expanduser().resolve()
    if not cues_path.is_file():
        raise BookletError(f"cue file does not exist: {cues_path}")
    cues = parse_cues(cues_path)
    cover_image = args.cover_image.expanduser().resolve()
    validate_image(cover_image, "cover image")
    frames_dir = args.frames_dir.expanduser().resolve()
    if not frames_dir.is_dir():
        raise BookletError(f"frames directory does not exist: {frames_dir}")
    frame_paths = sorted(
        path
        for path in frames_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    if len(frame_paths) != len(cues):
        raise BookletError(
            f"expected {len(cues)} captured frames for the Frame Cues, found {len(frame_paths)} in {frames_dir}"
        )
    for index, frame_path in enumerate(frame_paths, start=1):
        validate_image(frame_path, f"captured frame {index}")

    work_dir = args.work_dir.expanduser().resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict[str, object]] = []

    def import_page(
        source: Path,
        page_number: int,
        page_kind: str,
        cue: Cue | None,
    ) -> None:
        page_dir = work_dir / "frames" / f"page-{page_number:03d}"
        page_dir.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix.lower() if source.suffix else ".png"
        destination = page_dir / f"candidate-01{suffix}"
        shutil.copy2(source, destination)
        seconds = cue.seconds if cue else 0.0
        pages.append(
            {
                "page_number": page_number,
                "page_kind": page_kind,
                "source_line": cue.source_line if cue else 0,
                "frame_cue": cue.timestamp if cue else "published thumbnail",
                "cue_seconds": seconds,
                "text": cue.text if cue else "",
                "selected_candidate": 1,
                "candidates": [
                    {
                        "candidate_number": 1,
                        "timestamp_seconds": seconds,
                        "offset_seconds": 0.0,
                        "sharpness_score": None,
                        "image": relative_to(destination, work_dir),
                    }
                ],
            }
        )

    import_page(cover_image, 1, "cover", None)
    for content_number, (cue, frame_path) in enumerate(
        zip(cues, frame_paths, strict=True), start=1
    ):
        import_page(frame_path, content_number + 1, "content", cue)

    manifest: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "video_file": "",
            "source_url": args.source_url,
            "duration_seconds": args.duration_seconds,
            "acquisition": "browser-captured paused frames",
            "cover_source": "published YouTube thumbnail",
        },
        "book": {
            "title": args.title or "",
            "language": args.language or "",
        },
        "pages": pages,
    }
    manifest_path = work_dir / "manifest.json"
    save_manifest(manifest, manifest_path)
    for page in pages:
        make_page_contact_sheet(
            page,
            work_dir,
            work_dir / "review" / f"page-{int(page['page_number']):03d}.jpg",
        )
    make_selected_overview(manifest, manifest_path)
    print(
        json.dumps(
            {
                "status": "ok",
                "manifest": str(manifest_path),
                "review_directory": str(work_dir / "review"),
                "cover_pages": 1,
                "content_pages": len(cues),
                "authored_pages": len(pages),
            },
            indent=2,
        )
    )
    return 0


def command_select(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.expanduser().resolve()
    manifest = load_manifest(manifest_path)
    pages = manifest["pages"]
    assert isinstance(pages, list)
    if not 1 <= args.page <= len(pages):
        raise BookletError(f"page must be between 1 and {len(pages)}")
    page = pages[args.page - 1]
    assert isinstance(page, dict)
    candidates = page["candidates"]
    assert isinstance(candidates, list)
    if not 1 <= args.candidate <= len(candidates):
        raise BookletError(
            f"candidate must be between 1 and {len(candidates)} for page {args.page}"
        )
    page["selected_candidate"] = args.candidate
    save_manifest(manifest, manifest_path)
    make_page_contact_sheet(
        page,
        manifest_path.parent,
        manifest_path.parent / "review" / f"page-{args.page:03d}.jpg",
    )
    make_selected_overview(manifest, manifest_path)
    print(
        json.dumps(
            {"status": "ok", "page": args.page, "selected_candidate": args.candidate},
            indent=2,
        )
    )
    return 0


def imposed_pairs(
    authored_pages: int, binding: str = "left"
) -> tuple[int, list[tuple[int | None, int | None]]]:
    if authored_pages < 1:
        raise ValueError("authored_pages must be positive")
    padded_pages = int(math.ceil(authored_pages / 4.0) * 4)
    pairs: list[tuple[int | None, int | None]] = []
    sheet_count = padded_pages // 4
    for sheet in range(sheet_count):
        outer_left = padded_pages - 2 * sheet
        outer_right = 1 + 2 * sheet
        inner_left = 2 + 2 * sheet
        inner_right = padded_pages - 1 - 2 * sheet
        for left, right in ((outer_left, outer_right), (inner_left, inner_right)):
            if binding == "right":
                left, right = right, left
            pairs.append(
                (
                    left if left <= authored_pages else None,
                    right if right <= authored_pages else None,
                )
            )
    return padded_pages, pairs


def cut_stack_pairs(
    authored_pages: int,
) -> tuple[int, list[tuple[int | None, int | None]]]:
    """Arrange pages for one-sided printing, center cutting, and pile stacking."""
    padded_pages, groups = cut_stack_groups(authored_pages, 2)
    return padded_pages, [(group[0], group[1]) for group in groups]


def cut_stack_groups(
    authored_pages: int, pages_per_sheet: int
) -> tuple[int, list[tuple[int | None, ...]]]:
    """Arrange equal sequential piles across each single-sided printed sheet."""
    if authored_pages < 1:
        raise ValueError("authored_pages must be positive")
    if pages_per_sheet not in {2, 4}:
        raise ValueError("pages_per_sheet must be 2 or 4")
    padded_pages = int(math.ceil(authored_pages / pages_per_sheet) * pages_per_sheet)
    pile_size = padded_pages // pages_per_sheet
    groups: list[tuple[int | None, ...]] = []
    for sheet_index in range(pile_size):
        groups.append(
            tuple(
                number if number <= authored_pages else None
                for number in (
                    sheet_index + 1 + pile_index * pile_size
                    for pile_index in range(pages_per_sheet)
                )
            )
        )
    return padded_pages, groups


def text_direction(text: str) -> str:
    for character in text:
        bidi = unicodedata.bidirectional(character)
        if bidi in {"R", "AL", "AN"}:
            return "rtl"
        if bidi == "L":
            return "ltr"
    return "ltr"


def has_arabic(text: str) -> bool:
    return any("ARABIC" in unicodedata.name(character, "") for character in text)


def display_text(text: str, direction: str) -> str:
    if direction != "rtl" or features.check("raqm"):
        return text
    if bidi_display is None:
        raise BookletError(
            "right-to-left page text requires python-bidi; run: python3 -m pip install -r requirements.txt"
        )
    reshaped = text
    if has_arabic(text):
        if arabic_reshaper is None:
            raise BookletError(
                "Arabic page text requires arabic-reshaper; run: python3 -m pip install -r requirements.txt"
            )
        reshaped = arabic_reshaper.reshape(text)
    return bidi_display(reshaped)


def measure_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, direction: str
) -> float:
    kwargs: dict[str, str] = {}
    if features.check("raqm"):
        kwargs["direction"] = direction
    return float(draw.textlength(display_text(text, direction), font=font, **kwargs))


def wrap_paragraph(
    draw: ImageDraw.ImageDraw,
    paragraph: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    direction: str,
) -> list[str]:
    if not paragraph:
        return [""]
    tokens = paragraph.split()
    joiner = " "
    if len(tokens) == 1 and measure_text(draw, paragraph, font, direction) > max_width:
        tokens = list(paragraph)
        joiner = ""
    lines: list[str] = []
    current = ""
    for token in tokens:
        proposed = token if not current else current + joiner + token
        if current and measure_text(draw, proposed, font, direction) > max_width:
            lines.append(current)
            current = token
        else:
            current = proposed
    if current:
        lines.append(current)
    return lines


def fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: Path,
    max_width: int,
    max_height: int,
    dpi: int,
    max_points: int,
    min_points: int,
) -> tuple[ImageFont.FreeTypeFont, list[str], int, str]:
    direction = text_direction(text)
    for point_size in range(max_points, min_points - 1, -1):
        pixel_size = max(1, round(point_size * dpi / 72))
        font = ImageFont.truetype(str(font_path), pixel_size)
        lines: list[str] = []
        for paragraph in text.split("\n"):
            lines.extend(wrap_paragraph(draw, paragraph, font, max_width, direction))
        bbox = font.getbbox("Agأب")
        line_height = max(1, bbox[3] - bbox[1] + round(pixel_size * 0.34))
        if (
            lines
            and len(lines) * line_height <= max_height
            and all(
                measure_text(draw, line, font, direction) <= max_width + 1
                for line in lines
            )
        ):
            return font, lines, line_height, direction
    raise BookletError(
        "page text does not fit at the minimum font size; shorten it or split it across pages"
    )


def paste_rounded_frame(
    page: Image.Image,
    frame_path: Path,
    box: tuple[int, int, int, int],
    radius: int,
) -> None:
    left, top, right, bottom = box
    max_size = (right - left, bottom - top)
    with Image.open(frame_path) as opened:
        fitted = ImageOps.contain(
            opened.convert("RGB"), max_size, Image.Resampling.LANCZOS
        )
    x = left + (max_size[0] - fitted.width) // 2
    y = top + (max_size[1] - fitted.height) // 2
    shadow = Image.new("RGBA", page.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (
            x + radius // 3,
            y + radius // 2,
            x + fitted.width + radius // 3,
            y + fitted.height + radius // 2,
        ),
        radius=radius,
        fill=(20, 30, 45, 45),
    )
    page.alpha_composite(shadow)
    mask = Image.new("L", fitted.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, fitted.width, fitted.height), radius=radius, fill=255
    )
    page.paste(fitted, (x, y), mask)


def draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: Sequence[str],
    font: ImageFont.FreeTypeFont,
    center_x: int,
    start_y: int,
    line_height: int,
    fill: str,
    direction: str,
    language: str,
) -> None:
    kwargs: dict[str, str] = {}
    if features.check("raqm"):
        kwargs["direction"] = direction
        if language:
            kwargs["language"] = language
    for index, line in enumerate(lines):
        draw.text(
            (center_x, start_y + index * line_height),
            display_text(line, direction),
            font=font,
            fill=fill,
            anchor="ma",
            align="center",
            **kwargs,
        )


def selected_image(page: dict[str, object], manifest_dir: Path) -> Path:
    candidates = page["candidates"]
    assert isinstance(candidates, list)
    selected = int(page["selected_candidate"])
    candidate = candidates[selected - 1]
    assert isinstance(candidate, dict)
    image_path = (manifest_dir / str(candidate["image"])).resolve()
    if not image_path.is_file():
        raise BookletError(f"selected frame does not exist: {image_path}")
    return image_path


def render_logical_page(
    page_entry: dict[str, object] | None,
    manifest_dir: Path,
    page_width_inches: float,
    height_inches: float,
    dpi: int,
    font_path: Path,
    title: str,
    language: str,
    page_numbers: bool,
) -> Image.Image:
    width = round(page_width_inches * dpi)
    height = round(height_inches * dpi)
    page = Image.new("RGBA", (width, height), "white")
    if page_entry is None:
        return page
    draw = ImageDraw.Draw(page)
    margin = round((0.25 if page_width_inches <= 4.5 else 0.40) * dpi)
    center_x = width // 2
    ink = "#172238"
    muted = "#4B5563"
    accent = "#D69A2D"
    cursor_y = margin

    page_number = int(page_entry["page_number"])
    is_cover = page_entry.get("page_kind") == "cover"
    if page_number == 1 and title and not is_cover:
        title_region_height = round(0.88 * dpi)
        title_font, title_lines, title_line_height, title_direction = fit_text(
            draw,
            title,
            font_path,
            width - 2 * margin,
            title_region_height,
            dpi,
            max_points=27,
            min_points=17,
        )
        title_height = len(title_lines) * title_line_height
        draw_centered_lines(
            draw,
            title_lines,
            title_font,
            center_x,
            cursor_y + max(0, (title_region_height - title_height) // 2),
            title_line_height,
            ink,
            title_direction,
            language,
        )
        cursor_y += title_region_height + round(0.12 * dpi)

    page_text = str(page_entry.get("text") or "")
    frame_width = width - 2 * margin
    frame_height = round(frame_width * 9 / 16)
    if not page_text and not (page_number == 1 and title and not is_cover):
        cursor_y = (height - frame_height) // 2
    frame_box = (margin, cursor_y, width - margin, cursor_y + frame_height)
    paste_rounded_frame(
        page,
        selected_image(page_entry, manifest_dir),
        frame_box,
        radius=round(0.10 * dpi),
    )
    cursor_y += frame_height

    if page_text:
        text_top = cursor_y + round(0.38 * dpi)
        text_bottom = height - margin - (round(0.28 * dpi) if page_numbers else 0)
        available_height = text_bottom - text_top
        text_font, lines, line_height, direction = fit_text(
            draw,
            page_text,
            font_path,
            width - 2 * margin,
            available_height,
            dpi,
            max_points=28,
            min_points=15,
        )
        block_height = len(lines) * line_height
        line_y = text_top + max(0, (available_height - block_height) // 2)
        draw_centered_lines(
            draw,
            lines,
            text_font,
            center_x,
            line_y,
            line_height,
            ink,
            direction,
            language,
        )
        rule_width = min(round(0.8 * dpi), width // 4)
        rule_y = max(cursor_y + round(0.16 * dpi), line_y - round(0.15 * dpi))
        draw.rounded_rectangle(
            (
                center_x - rule_width // 2,
                rule_y,
                center_x + rule_width // 2,
                rule_y + max(2, dpi // 70),
            ),
            radius=max(1, dpi // 140),
            fill=accent,
        )

    if page_numbers:
        number_font = ImageFont.truetype(str(font_path), round(11 * dpi / 72))
        draw.text(
            (center_x, height - round(0.28 * dpi)),
            str(page_number),
            font=number_font,
            fill=muted,
            anchor="mm",
        )
    return page


def command_build(args: argparse.Namespace) -> int:
    manifest_path = args.manifest.expanduser().resolve()
    manifest = load_manifest(manifest_path)
    pages = manifest["pages"]
    assert isinstance(pages, list)
    base_width, base_height = PAPERS_INCHES[args.paper]
    is_cut_stack = args.layout in {"cut-stack", "cut-stack-4up"}
    if args.layout == "cut-stack-4up":
        paper_width, paper_height = (
            min(base_width, base_height),
            max(base_width, base_height),
        )
        columns, rows = 2, 2
        padded_pages, sheet_groups = cut_stack_groups(len(pages), 4)
        subject = (
            f"Home-print single-sided four-up cut-and-stack book; {len(pages)} "
            f"authored pages; {padded_pages} arranged logical pages"
        )
        print_settings = (
            "Actual size / 100%, portrait, single-sided; cut on both center "
            "lines, stack piles top-left, top-right, bottom-left, bottom-right, "
            "then edge-staple"
        )
        physical_sheets = len(sheet_groups)
    elif args.layout == "cut-stack":
        paper_width, paper_height = (
            max(base_width, base_height),
            min(base_width, base_height),
        )
        columns, rows = 2, 1
        padded_pages, sheet_groups = cut_stack_groups(len(pages), 2)
        subject = (
            f"Home-print single-sided cut-and-stack book; {len(pages)} authored "
            f"pages; {padded_pages} arranged logical pages"
        )
        print_settings = (
            "Actual size / 100%, single-sided; cut on the center line, place the "
            "left pile on top of the right pile, then edge-staple"
        )
        physical_sheets = len(sheet_groups)
    else:
        paper_width, paper_height = (
            max(base_width, base_height),
            min(base_width, base_height),
        )
        columns, rows = 2, 1
        padded_pages, sheet_groups = imposed_pairs(len(pages), args.binding)
        subject = (
            f"Home-print saddle-stitch booklet; {len(pages)} authored pages; "
            f"{padded_pages} imposed logical pages"
        )
        print_settings = (
            "Actual size / 100%, duplex, flip on short edge; disable printer "
            "booklet reordering"
        )
        physical_sheets = padded_pages // 4
    cell_width = paper_width / columns
    cell_height = paper_height / rows
    font_path = find_font(args.font)
    book = manifest.get("book") or {}
    assert isinstance(book, dict)
    title = str(args.title if args.title is not None else book.get("title") or "")
    language = str(book.get("language") or "")

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(
        str(output),
        pagesize=(paper_width * POINTS_PER_INCH, paper_height * POINTS_PER_INCH),
        pageCompression=1,
    )
    pdf.setTitle(title or output.stem)
    pdf.setAuthor("youtube-to-book")
    pdf.setSubject(subject)
    pdf.setCreator("youtube-to-book")

    for sheet_group in sheet_groups:
        for slot, page_number in enumerate(sheet_group):
            page_entry = pages[page_number - 1] if page_number is not None else None
            logical_page = render_logical_page(
                page_entry,
                manifest_path.parent,
                cell_width,
                cell_height,
                args.dpi,
                font_path,
                title,
                language,
                args.page_numbers,
            )
            image_buffer = io.BytesIO()
            logical_page.convert("RGB").save(
                image_buffer,
                format="JPEG",
                quality=94,
                subsampling=0,
                optimize=True,
                dpi=(args.dpi, args.dpi),
            )
            image_buffer.seek(0)
            column = slot % columns
            row = slot // columns
            pdf.drawImage(
                ImageReader(image_buffer),
                column * cell_width * POINTS_PER_INCH,
                (paper_height - (row + 1) * cell_height) * POINTS_PER_INCH,
                width=cell_width * POINTS_PER_INCH,
                height=cell_height * POINTS_PER_INCH,
            )
        if is_cut_stack:
            inset = 0.15 * POINTS_PER_INCH
            pdf.setStrokeColorRGB(0.68, 0.68, 0.68)
            pdf.setLineWidth(0.45)
            pdf.setDash(3, 3)
            for column in range(1, columns):
                cut_x = column * cell_width * POINTS_PER_INCH
                pdf.line(
                    cut_x,
                    inset,
                    cut_x,
                    paper_height * POINTS_PER_INCH - inset,
                )
            for row in range(1, rows):
                cut_y = row * cell_height * POINTS_PER_INCH
                pdf.line(
                    inset,
                    cut_y,
                    paper_width * POINTS_PER_INCH - inset,
                    cut_y,
                )
            pdf.setDash()
        elif args.fold_marks:
            center = cell_width * POINTS_PER_INCH
            pdf.setStrokeColorRGB(0.72, 0.72, 0.72)
            pdf.setLineWidth(0.35)
            mark = 0.12 * POINTS_PER_INCH
            pdf.line(center, 0, center, mark)
            pdf.line(
                center,
                paper_height * POINTS_PER_INCH - mark,
                center,
                paper_height * POINTS_PER_INCH,
            )
        pdf.showPage()
    pdf.save()

    print(
        json.dumps(
            {
                "status": "ok",
                "output": str(output),
                "paper": args.paper,
                "binding": args.binding,
                "layout": args.layout,
                "page_numbers": args.page_numbers,
                "authored_pages": len(pages),
                "padded_logical_pages": padded_pages,
                "logical_pages_per_sheet": columns * rows,
                "physical_sheets": physical_sheets,
                "pdf_sheet_sides": len(sheet_groups),
                "print_settings": print_settings,
            },
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract_parser = subparsers.add_parser(
        "extract", help="extract nearby candidates for each Frame Cue"
    )
    extract_parser.add_argument("--video", type=Path, required=True)
    extract_parser.add_argument("--source-url", default="")
    extract_parser.add_argument("--cues", type=Path, required=True)
    extract_parser.add_argument("--title", default="")
    extract_parser.add_argument("--language", default="")
    extract_parser.add_argument("--work-dir", type=Path, required=True)
    extract_parser.add_argument(
        "--offsets",
        default=",".join(f"{value:.2f}" for value in DEFAULT_OFFSETS),
        help="comma-separated seconds relative to each cue",
    )
    extract_parser.set_defaults(handler=command_extract)

    import_parser = subparsers.add_parser(
        "import-frames",
        help="import a published thumbnail cover and browser-captured content frames",
    )
    import_parser.add_argument("--frames-dir", type=Path, required=True)
    import_parser.add_argument("--cover-image", type=Path, required=True)
    import_parser.add_argument("--cues", type=Path, required=True)
    import_parser.add_argument("--source-url", required=True)
    import_parser.add_argument("--title", default="")
    import_parser.add_argument("--language", default="")
    import_parser.add_argument("--duration-seconds", type=float, default=0.0)
    import_parser.add_argument("--work-dir", type=Path, required=True)
    import_parser.set_defaults(handler=command_import_frames)

    select_parser = subparsers.add_parser(
        "select", help="select a reviewed candidate for one page"
    )
    select_parser.add_argument("--manifest", type=Path, required=True)
    select_parser.add_argument("--page", type=int, required=True)
    select_parser.add_argument("--candidate", type=int, required=True)
    select_parser.set_defaults(handler=command_select)

    build_parser = subparsers.add_parser(
        "build", help="build an imposed home-print book PDF"
    )
    build_parser.add_argument("--manifest", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument(
        "--paper", choices=sorted(PAPERS_INCHES), default="letter"
    )
    build_parser.add_argument("--binding", choices=("left", "right"), default="left")
    build_parser.add_argument(
        "--layout",
        choices=("booklet", "cut-stack", "cut-stack-4up"),
        default="cut-stack-4up",
        help="four-up or two-up cut-and-stack, or booklet for duplex folding",
    )
    build_parser.add_argument("--font", type=Path)
    build_parser.add_argument("--title", help="override the manifest title")
    build_parser.add_argument("--dpi", type=int, default=300)
    build_parser.add_argument(
        "--page-numbers",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="print logical page numbers at the bottom center (default: enabled)",
    )
    build_parser.add_argument("--fold-marks", action="store_true")
    build_parser.set_defaults(handler=command_build)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "dpi", 300) < 150:
        parser.error("--dpi must be at least 150")
    try:
        return int(args.handler(args))
    except BookletError as exc:
        print(
            json.dumps(
                {"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
