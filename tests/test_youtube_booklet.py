from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "youtube_booklet.py"
SPEC = importlib.util.spec_from_file_location("youtube_booklet", MODULE_PATH)
assert SPEC and SPEC.loader
booklet = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = booklet
SPEC.loader.exec_module(booklet)

ACQUIRE_PATH = REPO_ROOT / "scripts" / "acquire_video.py"
ACQUIRE_SPEC = importlib.util.spec_from_file_location("acquire_video", ACQUIRE_PATH)
assert ACQUIRE_SPEC and ACQUIRE_SPEC.loader
acquire = importlib.util.module_from_spec(ACQUIRE_SPEC)
sys.modules[ACQUIRE_SPEC.name] = acquire
ACQUIRE_SPEC.loader.exec_module(acquire)


class AcquisitionAdapterTests(unittest.TestCase):
    def test_recognizes_supported_youtube_hosts_only(self) -> None:
        self.assertTrue(acquire.is_youtube_url("https://www.youtube.com/watch?v=abc"))
        self.assertTrue(acquire.is_youtube_url("https://youtu.be/abc"))
        self.assertFalse(acquire.is_youtube_url("https://example.com/video.mp4"))
        self.assertFalse(acquire.is_youtube_url("not a URL"))

    def test_classifies_rate_limits_and_access_controls(self) -> None:
        self.assertEqual(
            acquire.classify_failure("HTTP Error 429: Too Many Requests"),
            "source_rate_limited",
        )
        self.assertEqual(
            acquire.classify_failure("Sign in to confirm you're not a bot"),
            "source_unavailable",
        )
        self.assertEqual(
            acquire.classify_failure("This video is not available"),
            "source_unavailable",
        )
        self.assertEqual(
            acquire.classify_failure("extractor changed unexpectedly"), "media_required"
        )

    def test_finds_the_downloader_installed_beside_the_active_python(self) -> None:
        sibling = Path(sys.executable).parent / "yt-dlp"
        self.assertTrue(sibling.is_file(), f"test environment is missing {sibling}")


class TimestampTests(unittest.TestCase):
    def test_accepts_supported_timestamp_shapes(self) -> None:
        self.assertEqual(booklet.parse_timestamp("75.5"), 75.5)
        self.assertEqual(booklet.parse_timestamp("01:15.5"), 75.5)
        self.assertEqual(booklet.parse_timestamp("1:01:15.5"), 3675.5)

    def test_rejects_invalid_minute_or_second_components(self) -> None:
        with self.assertRaises(ValueError):
            booklet.parse_timestamp("1:60")
        with self.assertRaises(ValueError):
            booklet.parse_timestamp("-1")

    def test_parses_comments_optional_text_and_forced_line_breaks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cues = Path(directory) / "cues.txt"
            cues.write_text(
                "# page cues\n00:01 | First line\\nSecond line\n00:02\n00:03\tTabbed text\n",
                encoding="utf-8",
            )
            parsed = booklet.parse_cues(cues)
        self.assertEqual([cue.seconds for cue in parsed], [1.0, 2.0, 3.0])
        self.assertEqual(parsed[0].text, "First line\nSecond line")
        self.assertEqual(parsed[1].text, "")
        self.assertEqual(parsed[2].text, "Tabbed text")


class ImpositionTests(unittest.TestCase):
    def test_left_bound_eight_page_order(self) -> None:
        padded, pairs = booklet.imposed_pairs(8, "left")
        self.assertEqual(padded, 8)
        self.assertEqual(pairs, [(8, 1), (2, 7), (6, 3), (4, 5)])

    def test_right_bound_mirrors_each_sheet_side(self) -> None:
        padded, pairs = booklet.imposed_pairs(8, "right")
        self.assertEqual(padded, 8)
        self.assertEqual(pairs, [(1, 8), (7, 2), (3, 6), (5, 4)])

    def test_padding_is_blank_without_renumbering_authored_pages(self) -> None:
        padded, pairs = booklet.imposed_pairs(5, "left")
        self.assertEqual(padded, 8)
        self.assertEqual(pairs, [(None, 1), (2, None), (None, 3), (4, 5)])

    def test_cut_stack_order_forms_two_sequential_piles(self) -> None:
        padded, pairs = booklet.cut_stack_pairs(20)
        self.assertEqual(padded, 20)
        self.assertEqual(
            pairs,
            [
                (1, 11),
                (2, 12),
                (3, 13),
                (4, 14),
                (5, 15),
                (6, 16),
                (7, 17),
                (8, 18),
                (9, 19),
                (10, 20),
            ],
        )

    def test_cut_stack_pads_only_to_an_even_page_count(self) -> None:
        padded, pairs = booklet.cut_stack_pairs(5)
        self.assertEqual(padded, 6)
        self.assertEqual(pairs, [(1, 4), (2, 5), (3, None)])

    def test_four_up_cut_stack_forms_four_sequential_piles(self) -> None:
        padded, groups = booklet.cut_stack_groups(20, 4)
        self.assertEqual(padded, 20)
        self.assertEqual(
            groups,
            [
                (1, 6, 11, 16),
                (2, 7, 12, 17),
                (3, 8, 13, 18),
                (4, 9, 14, 19),
                (5, 10, 15, 20),
            ],
        )

    def test_four_up_cut_stack_pads_to_a_multiple_of_four(self) -> None:
        padded, groups = booklet.cut_stack_groups(5, 4)
        self.assertEqual(padded, 8)
        self.assertEqual(groups, [(1, 3, 5, None), (2, 4, None, None)])


class PdfIntegrationTests(unittest.TestCase):
    def test_build_defaults_to_numbered_single_sided_four_up_cut_stack(self) -> None:
        parsed = booklet.build_parser().parse_args(
            ["build", "--manifest", "manifest.json", "--output", "book.pdf"]
        )
        self.assertEqual(parsed.layout, "cut-stack-4up")
        self.assertTrue(parsed.page_numbers)

        unnumbered = booklet.build_parser().parse_args(
            [
                "build",
                "--manifest",
                "manifest.json",
                "--output",
                "book.pdf",
                "--no-page-numbers",
            ]
        )
        self.assertFalse(unnumbered.page_numbers)

    def test_builds_landscape_letter_pdf_with_expected_sheet_sides(self) -> None:
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = root / "frames"
            frames.mkdir()
            pages = []
            colors = ["#E76F51", "#F4A261", "#E9C46A", "#2A9D8F", "#457B9D"]
            for page_number, color in enumerate(colors, start=1):
                frame = frames / f"page-{page_number:03d}.png"
                image = Image.new("RGB", (960, 540), color)
                ImageDraw.Draw(image).text(
                    (40, 40), f"PAGE {page_number}", fill="white"
                )
                image.save(frame)
                pages.append(
                    {
                        "page_number": page_number,
                        "source_line": page_number,
                        "frame_cue": f"00:0{page_number}",
                        "cue_seconds": float(page_number),
                        "text": "كل يوم حكاية جديدة"
                        if page_number == 4
                        else f"Words for page {page_number}",
                        "selected_candidate": 1,
                        "candidates": [
                            {
                                "candidate_number": 1,
                                "timestamp_seconds": float(page_number),
                                "offset_seconds": 0.0,
                                "sharpness_score": 1.0,
                                "image": str(frame.relative_to(root)),
                            }
                        ],
                    }
                )
            manifest = {
                "schema_version": 1,
                "source": {"video_file": "fixture.mp4", "duration_seconds": 10.0},
                "book": {"title": "A Small Book", "language": "ar"},
                "pages": pages,
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            output = root / "booklet.pdf"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "build",
                    "--manifest",
                    str(manifest_path),
                    "--output",
                    str(output),
                    "--layout",
                    "booklet",
                    "--dpi",
                    "150",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            reader = PdfReader(output)
            self.assertEqual(len(reader.pages), 4)
            first_page = reader.pages[0]
            width = float(first_page.mediabox.width)
            height = float(first_page.mediabox.height)
            self.assertAlmostEqual(width, 11 * 72, places=1)
            self.assertAlmostEqual(height, 8.5 * 72, places=1)

            cut_stack_output = root / "cut-stack.pdf"
            cut_stack = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "build",
                    "--manifest",
                    str(manifest_path),
                    "--output",
                    str(cut_stack_output),
                    "--layout",
                    "cut-stack",
                    "--dpi",
                    "150",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(cut_stack.returncode, 0, cut_stack.stderr)
            self.assertEqual(len(PdfReader(cut_stack_output).pages), 3)

            four_up_output = root / "four-up-cut-stack.pdf"
            four_up = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "build",
                    "--manifest",
                    str(manifest_path),
                    "--output",
                    str(four_up_output),
                    "--dpi",
                    "150",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(four_up.returncode, 0, four_up.stderr)
            four_up_status = json.loads(four_up.stdout)
            self.assertEqual(four_up_status["layout"], "cut-stack-4up")
            self.assertEqual(four_up_status["logical_pages_per_sheet"], 4)
            four_up_reader = PdfReader(four_up_output)
            self.assertEqual(len(four_up_reader.pages), 2)
            four_up_page = four_up_reader.pages[0]
            self.assertAlmostEqual(
                float(four_up_page.mediabox.width), 8.5 * 72, places=1
            )
            self.assertAlmostEqual(
                float(four_up_page.mediabox.height), 11 * 72, places=1
            )


class PageNumberRenderingTests(unittest.TestCase):
    def test_number_is_drawn_only_in_the_bottom_page_margin(self) -> None:
        from PIL import Image, ImageChops

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frame = root / "frame.png"
            Image.new("RGB", (960, 540), "#4A90E2").save(frame)
            page = {
                "page_number": 7,
                "text": "",
                "selected_candidate": 1,
                "candidates": [{"image": frame.name}],
            }
            font = booklet.find_font(None)
            numbered = booklet.render_logical_page(
                page, root, 5.5, 8.5, 150, font, "", "", True
            )
            unnumbered = booklet.render_logical_page(
                page, root, 5.5, 8.5, 150, font, "", "", False
            )
            difference = ImageChops.difference(
                numbered.convert("RGB"), unnumbered.convert("RGB")
            ).getbbox()
            self.assertIsNotNone(difference)
            assert difference is not None
            self.assertGreater(difference[1], numbered.height - round(0.5 * 150))


class FrameExtractionIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required"
    )
    def test_extracts_candidate_neighborhoods_and_review_images(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "fixture.mp4"
            cues = root / "cues.txt"
            cues.write_text(
                "00:00.50 | First page\n00:01.50 | Second page\n", encoding="utf-8"
            )
            generated = subprocess.run(
                [
                    shutil.which("ffmpeg") or "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc2=duration=2:size=320x180:rate=24",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            work_dir = root / "project"
            extracted = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "extract",
                    "--video",
                    str(video),
                    "--cues",
                    str(cues),
                    "--work-dir",
                    str(work_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(extracted.returncode, 0, extracted.stderr)
            manifest = json.loads(
                (work_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest["pages"]), 2)
            self.assertEqual(len(manifest["pages"][0]["candidates"]), 5)
            self.assertTrue((work_dir / "review" / "page-001.jpg").is_file())
            self.assertTrue((work_dir / "review" / "selected-pages.jpg").is_file())


class BrowserFrameImportTests(unittest.TestCase):
    def test_prepends_the_published_thumbnail_without_consuming_a_cue(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = root / "browser-frames"
            frames.mkdir()
            Image.new("RGB", (1280, 720), "cyan").save(root / "cover.jpg")
            Image.new("RGB", (1920, 1080), "red").save(frames / "page-001.png")
            Image.new("RGB", (1920, 1080), "blue").save(frames / "page-002.png")
            (root / "cues.txt").write_text("00:22\n00:23\n", encoding="utf-8")
            work_dir = root / "project"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "import-frames",
                    "--frames-dir",
                    str(frames),
                    "--cover-image",
                    str(root / "cover.jpg"),
                    "--cues",
                    str(root / "cues.txt"),
                    "--source-url",
                    "https://www.youtube.com/watch?v=fixture",
                    "--work-dir",
                    str(work_dir),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            manifest = json.loads(
                (work_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(manifest["pages"]), 3)
            self.assertEqual(manifest["pages"][0]["page_kind"], "cover")
            self.assertEqual(manifest["pages"][1]["frame_cue"], "00:22")
            self.assertEqual(manifest["pages"][2]["frame_cue"], "00:23")


if __name__ == "__main__":
    unittest.main()
