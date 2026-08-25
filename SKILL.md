---
name: youtube-to-book
description: Create home-printable frame books from a YouTube or local video plus timestamps, including thumbnail covers, reviewed frame selection, numbered four-up cut-and-stack PDFs, and optional larger-page or duplex layouts.
---

# YouTube to Book

Create a **Book Draft** from a **Source Video** and ordered **Frame Cues**, then arrange the approved pages into a home-printing PDF. Keep the user's page order and wording authoritative.

## Inputs

Collect or infer:

- Source Video URL and, when URL acquisition is unavailable, a local video file.
- One Frame Cue per intended book page, with optional page text.
- Book title, paper (`letter` by default; `a4` when requested), binding direction (`left` by default; `right` for right-bound books), and print layout (`cut-stack-4up` by default; `cut-stack` for larger two-up pages; `booklet` for duplex folding). Print the logical page number at the bottom center of every page by default, including the cover.

For a YouTube Source Video, use its published thumbnail as the front cover by default. Frame Cues begin with the first inside page; the cover is not one of the user-numbered cues.

Normalize conversational timestamp lists to the cue format in [references/cue-format.md](references/cue-format.md). Do not require the user to rewrite a parseable list.

## Workflow

1. Create a project directory under `tmp/pdfs/<book-slug>/` and save the normalized cue file there. Final PDFs belong in `output/pdf/`.
2. Resolve the Source Video:
   - Use a supplied local file directly.
   - For a YouTube URL, explain that media access is an unofficial, best-effort step, then run `scripts/acquire_video.py`. This adapter never imports browser cookies or bypasses availability controls.
   - If acquisition returns anything other than `ok`, retain the URL and cue file, report its structured outcome, and ask for a local video file. Resume from the same project directory when supplied.
   - If ordinary browser playback is available, browser-captured paused frames are an acceptable manual fallback. Keep player chrome out of the image and import them with `import-frames`; do not treat this as source-media acquisition.
3. Extract nearby candidates with `scripts/youtube_booklet.py extract`. A Frame Cue is a baseline: the script samples a small neighborhood and records the sharpest candidate without changing page order.
4. Inspect every `review/page-*.jpg` contact sheet. Check character faces, motion blur, overlays, subtitles, and scene continuity. If the automatic choice is poor, select another recorded candidate with the `select` command. If every candidate is poor, offer a nearby Suggested Frame Cue and get approval before altering it.
5. Review page text in `manifest.json`. Preserve source language and user wording. Treat captions or speech recognition as a draft; surface ambiguous text rather than inventing it.
6. Confirm the logical page count before building. Four-up cut-and-stack and saddle stitch need a multiple of four to avoid blanks; two-up cut-and-stack needs an even count. Preserve every cue unless the user explicitly chooses one to remove.
7. Build with `scripts/youtube_booklet.py build`. The default `cut-stack-4up` layout produces numbered, single-sided portrait sheets with four quarter-Letter pages and horizontal/vertical center cut lines. Use `--layout cut-stack` for larger two-up pages, `--layout booklet` for duplex folding, and `--no-page-numbers` only when explicitly requested.
8. Render the PDF to PNG and inspect every sheet. Verify complete text, sequential unclipped page numbers, consistent margins, both center cut lines for four-up output, and the pile arrangement required by the selected layout. Rebuild until clean.

For a YouTube book, confirm that logical page 1 is the published thumbnail and logical page 2 corresponds to the user's first Frame Cue.

## Commands

Install runtime dependencies into the active Python environment when missing:

```bash
python3 -m pip install -r requirements.txt
```

Best-effort URL acquisition:

```bash
python3 scripts/acquire_video.py \
  --url "https://www.youtube.com/watch?v=..." \
  --output-dir tmp/pdfs/my-book/source
```

Extract and review:

```bash
python3 scripts/youtube_booklet.py extract \
  --video tmp/pdfs/my-book/source/source.mp4 \
  --source-url "https://www.youtube.com/watch?v=..." \
  --cues tmp/pdfs/my-book/cues.txt \
  --title "My Book" \
  --work-dir tmp/pdfs/my-book
```

Import browser-captured frames when URL acquisition failed but ordinary playback was available:

```bash
python3 scripts/youtube_booklet.py import-frames \
  --frames-dir tmp/pdfs/my-book/browser-frames \
  --cover-image tmp/pdfs/my-book/source/cover-thumbnail.jpg \
  --cues tmp/pdfs/my-book/cues.txt \
  --source-url "https://www.youtube.com/watch?v=..." \
  --work-dir tmp/pdfs/my-book/project
```

Override a candidate when visual review favors it:

```bash
python3 scripts/youtube_booklet.py select \
  --manifest tmp/pdfs/my-book/manifest.json \
  --page 3 \
  --candidate 4
```

Build the default US Letter, single-sided four-up cut-and-stack book:

```bash
python3 scripts/youtube_booklet.py build \
  --manifest tmp/pdfs/my-book/manifest.json \
  --output output/pdf/my-book-letter-four-up-cut-stack.pdf \
  --paper letter \
  --binding right
```

Use `--paper a4` for A4 or `--binding right` for a right-bound book. Use `--font /path/to/font.ttf` when the automatically discovered font does not cover the page language. Page numbers are enabled by default; `--no-page-numbers` suppresses them.

Use `--layout cut-stack` when larger half-Letter pages are more important than paper savings.

Build the optional duplex saddle-stitch version:

```bash
python3 scripts/youtube_booklet.py build \
  --manifest tmp/pdfs/my-book/manifest.json \
  --output output/pdf/my-book-letter-booklet.pdf \
  --paper letter \
  --binding right \
  --layout booklet
```

## Print Contract

For the default `cut-stack-4up` layout, print portrait, single-sided, at **Actual size / 100%**. Put the sheets in PDF order and cut the stack on both dashed center lines. Without reversing any pile, stack the quadrants in this order: top-left, top-right, bottom-left, bottom-right. Confirm that the bottom numbers now run sequentially, then staple along the binding edge. Do not fold this version; the physical backs remain blank.

For `--layout cut-stack`, print landscape and single-sided, cut on the vertical center line, place the left pile on top of the right pile, and edge-staple.

For `--layout booklet`, print at **Actual size / 100%**, duplex, **flip on short edge**, with printer scaling and booklet reordering disabled. Each PDF page is one physical sheet side; stack sheets in PDF order, fold the stack down the center, then staple through the fold.

The default is ink-conscious: white margins, no bleed, and light dashed cut lines. Home printers vary, so recommend a one-sheet test before printing a long book.

## Boundaries

- A public YouTube URL locates a video but does not guarantee downloadable media. The official YouTube API does not provide arbitrary source frames or public caption text.
- Never export cookies, introduce proxies, evade login/age/region controls, silently switch videos, or claim that successful acquisition grants reproduction rights.
- Reject cues outside the probed video duration. Preserve the cue and ask for a correction.
- Pad only to the selected layout's required page multiple. If the user rejects blank halves, ask them to choose content to add or remove; never silently drop a Frame Cue or invent a title, credit, lyric, or story page.
- Keep this home-booklet workflow separate from Lulu preparation. Lulu requires individual trim pages and a separate cover PDF, not this imposed landscape file.
