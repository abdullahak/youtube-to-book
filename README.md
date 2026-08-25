# YouTube to Book

A Codex skill that turns a video and an ordered timestamp list into a home-printable booklet PDF.

The workflow:

1. Accepts a YouTube URL and Frame Cues such as `00:12.5 | Page words`.
2. Uses the video's published YouTube thumbnail as the front cover; the first cue becomes the first inside page.
3. Attempts cookie-free, best-effort video acquisition, with a local video file or clean browser-frame capture as fallbacks.
4. Extracts several nearby frame candidates for every cue and creates contact sheets for visual review.
5. Preserves optional page text, including Arabic/right-to-left text.
6. Produces a numbered, single-sided US Letter or A4 PDF with four cut-apart book pages per sheet by default, with larger two-up and duplex layouts available.

## Install

Install this repository as the `youtube-to-book` skill, then install its Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

FFmpeg and FFprobe are required for video analysis. Poppler's `pdftoppm` is recommended for final PDF visual verification.

## Cue file

```text
00:03.500 | Optional words printed on page 1
00:11     | Optional words printed on page 2
01:02.25
```

See [SKILL.md](SKILL.md) for the complete agent workflow and [references/cue-format.md](references/cue-format.md) for accepted timestamp syntax.

## Print settings

The default output uses `--layout cut-stack-4up` and numbers every logical page at the bottom center. Print portrait and single-sided at Actual size / 100%, keep the sheets in PDF order, and cut the stack on both dashed center lines. Stack the four piles without reversing them in this order: top-left, top-right, bottom-left, bottom-right. Verify that the page numbers are sequential, then staple along the binding edge. The physical backs remain blank. Pass `--no-page-numbers` only when an unnumbered book is wanted.

Use `--layout cut-stack` for larger two-up pages printed landscape.

For a duplex printer, use `--layout booklet`, print at Actual size / 100%, flip on the short edge, and disable printer-side booklet reordering. Stack the sheets in PDF order, fold down the center, then staple through the fold.

This home booklet is intentionally separate from a Lulu print file. Lulu expects individual trim pages and a separate cover PDF rather than an imposed two-up landscape PDF.
