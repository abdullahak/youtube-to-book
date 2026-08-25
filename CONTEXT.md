# YouTube-to-Book

This context describes a private workflow that turns a familiar children's video into a screen-free, printed frame-and-lyrics book for one family.

## Language

**Source Video**:
The single public video selected as the source for one book.
_Avoid_: Episode, content

**Frame Cue**:
A user-authored timestamp identifying a desired book scene. It is a baseline for selecting the clearest nearby source frame, not an exact-millisecond capture instruction.
_Avoid_: Screenshot, keyframe

**Suggested Frame Cue**:
An additional scene proposed when the supplied frame cues leave a gap or yield a poor image. It does not join the book unless the user approves it.
_Avoid_: Automatic page

**Book Draft**:
The reviewable frame-and-lyrics book before final approval for print preparation.
_Avoid_: Proof, final PDF

**Frame Page**:
One authored portrait book page containing the selected nearby frame, optional user-approved text, and its logical page number at the bottom center. Frame Page order is the order of the supplied Frame Cues.
_Avoid_: PDF page, sheet

**Cover Page**:
Logical page 1 of a YouTube-sourced home-print PDF, using the published YouTube thumbnail without consuming a Frame Cue. The user's first numbered Frame Cue becomes logical page 2.
_Avoid_: Cue 1, title spread

**Sheet Side**:
One landscape page in the home-print PDF. It contains two imposed Frame Pages and represents one side of one physical sheet.
_Avoid_: Spread

**Single-Sided Cut-and-Stack PDF**:
The default home-print artifact. It places four sequential page piles in a 2x2 grid on portrait US Letter or A4 sheets, with one logical page number in each quadrant.
_Avoid_: Booklet PDF, reader PDF

**Duplex Saddle-Stitch PDF**:
An optional home-print artifact imposed in duplex booklet order for folding and stapling through the center.
_Avoid_: Single-sided PDF, Lulu interior

**Print Job**:
An unpaid Lulu API order created only after the book's print-ready files receive final approval. Payment remains a separate manual action in Lulu's Print Job portal.
_Avoid_: Cart, purchase

## First deliverable

The immediate workflow produces a Single-Sided Cut-and-Stack PDF. US Letter is the default; A4 is selectable. Print the portrait sheets one-sided in PDF order and cut the stack on its horizontal and vertical center lines. Without reversing the piles, stack top-left, top-right, bottom-left, then bottom-right; verify sequential page numbers and staple the resulting quarter-sheet stack along its binding edge. The physical backs remain blank, and this format is cut rather than folded.

Use a Duplex Saddle-Stitch PDF only when explicitly requested. It is printed duplex, flipped on the short edge, folded once down the center, and stapled through the fold.

Saddle stitching requires a Frame Page count divisible by four. Preserve every authored page and append intentional blanks only as needed. For left binding, an eight-page booklet is imposed as `8–1`, `2–7`, `6–3`, `4–5`; right binding mirrors each pair.

The user prints at actual size with printer-side reordering and scaling disabled. Home-print PDFs cannot be submitted as a Lulu interior: Lulu preparation remains a separate future branch that exports individual trim pages and a separate cover.
