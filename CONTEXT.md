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

**Print Job**:
An unpaid Lulu API order created only after the book's print-ready files receive final approval. Payment remains a separate manual action in Lulu's Print Job portal.
_Avoid_: Cart, purchase
