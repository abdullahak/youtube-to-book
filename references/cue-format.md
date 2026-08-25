# Frame Cue format

Use UTF-8 text with one logical book page per non-empty line:

```text
# Lines beginning with # are comments.
00:03.500 | Optional words printed on page 1
00:11     | Optional words printed on page 2
01:02.25
```

The separator is the first `|` or tab. Text is optional and may contain additional `|` characters. Write a literal `\n` to force a line break inside the printed text.

Accepted timestamps are seconds (`75.5`), `MM:SS`, or `HH:MM:SS`, with an optional decimal fraction. Page order is line order; timestamps need not be sorted.

When the user supplies another clear format, normalize it rather than asking them to retype it. Preserve every timestamp and page-text string exactly apart from unambiguous syntax cleanup.

For a YouTube Source Video, the published thumbnail is logical page 1 (the front cover), the first cue is the first inside page, and the final cue is the last authored inside page. For a local-only source without a cover image, the first cue remains logical page 1.

The default four-up cut-and-stack layout pads to a multiple of four. The larger two-up cut-and-stack layout pads to an even count, and the optional saddle-stitch layout pads to a multiple of four. When the user wants no blank pages, get approval for the exact page to add or remove; never discard a Frame Cue automatically.
