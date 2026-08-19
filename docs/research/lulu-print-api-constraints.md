# Lulu Print API constraints for the first frame-and-lyrics book

Research date: 2026-08-19

## Conclusion

The proposed private workflow is feasible with Lulu, with one important correction: the API does not add a book to a shopping cart. After final approval it creates a **Print Job**. The job remains `UNPAID` for manual payment in Lulu's Print Job portal only when automatic payment is disabled on the Lulu account. A saved payment method activates automatic payment and can advance a new job toward production, so the implementation cannot use Lulu job creation as a harmless preview action. Lulu's current [Print API documentation](https://api.lulu.com/docs/) describes the `UNPAID` flow, and its [automatic-payment instructions](https://help.api.lulu.com/en/support/solutions/articles/64000293838-how-do-i-set-up-automatic-payment-fulfillment-for-my-api-orders-) say adding a payment method activates automatic payments.

The skill should therefore have two separate irreversible-looking gates:

1. approve the reviewed PDFs and live cost calculation; then
2. explicitly approve **Create unpaid Lulu Print Job**, after confirming that the production Lulu account has no saved payment method and automatic/batch payment is disabled.

The API request has no documented per-job `pay=false` or equivalent. That means the no-saved-card account state is a human-controlled safety precondition, not something the API client can guarantee from the create-job payload. This is an inference from the documented create-job schema and payment behavior.

## Product constraints that affect the book design

Lulu now uses dotted POD package IDs. The dotted format went live on 2026-03-31 and the legacy 27-character form is scheduled to stop working on 2027-02-01, so all new implementation and saved project state should use dotted IDs from the [current API documentation](https://api.lulu.com/docs/).

The separate physical-preset decision can choose among Lulu's combinations, but the current official [Print API Product Specification Sheet](https://assets.lulu.com/media/specs/lulu-print-api-spec-sheet.xlsx) makes this particularly suitable candidate available:

| Attribute | Candidate value |
| --- | --- |
| Trim | Small Square, 7.5 x 7.5 in |
| Interior | Full Color, Premium, 80# Coated White |
| Binding | Hardcover Case Wrap |
| Finish | Matte |
| Dotted POD package ID | `0750X0750.FC.PRE.CW.080CW444.MXX` |
| Interior page range | 24–800 |
| Full-bleed interior page | 7.75 x 7.75 in |
| Current sheet price components (USD) | $10.98 base + $0.2148/page |
| Illustrative 24-page print cost | $16.14 before shipping, fulfillment, fees, discounts, and tax |

The same sheet lists a Standard Color version, `0750X0750.FC.STD.CW.080CW444.MXX`, at $10.98 + $0.0635/page ($12.50 for 24 pages before the other charges). Premium Color is the quality-oriented candidate because Lulu's [Book Creation Guide](https://assets.lulu.com/media/guides/en/lulu-book-creation-guide.pdf) recommends Premium Color for high-resolution photos and heavy/full-page ink coverage. The preset itself must still be chosen with the user; these are constraints and a viable default, not a substitute for that choice.

The 24-page casewrap minimum is consequential:

- The cover is a separate PDF and does not count toward the 24 interior pages.
- Interior page 1 prints on the right; odd pages are right-hand pages and even pages are left-hand pages. A 24-page interior therefore has 11 normal facing spreads (`2–3` through `22–23`) plus standalone opening page 1 and closing page 24. If one approved frame cue maps to one spread, a minimal casewrap book naturally fits 11 frame-cue spreads, with the two standalone pages used for title/dedication and credits/source note. Longer sequences must increase the interior page count.
- Casewrap cannot print on the inside front or back cover. Lulu only offers inside-cover printing for magazine and comic-book products, per [Lulu's inside-cover guidance](https://help.api.lulu.com/en/support/solutions/articles/64000254629-is-it-possible-to-print-on-the-inside-of-a-book-cover-).
- A short book should not carry spine text. Lulu's Book Creation Guide advises omitting spine text at 80 pages or fewer.

For a 16:9 video frame, Small Square is also a practical print-resolution compromise. A frame fitted without cropping into a 6.5-inch-wide interior safe area needs about 1950 x 1097 pixels at 300 PPI; a 1920 x 1080 source frame is nearly native size. A casewrap front cover using the more conservative 0.75-inch safety inset has a 6-inch-wide safe area, needing about 1800 x 1013 pixels. By contrast, filling the entire square bleed area requires about 2325 x 2325 pixels and discards substantial horizontal content. This calculation supports a framed/letterboxed cover and interior visual system, with title or lyrics above/below the image, instead of forcing a full-square crop. Lower-resolution source frames will still require quality review and upscaling.

## Print-ready PDF contract

Lulu requires two files: one multipage interior PDF and one single-page cover PDF, both supplied by downloadable URL. Its [PDF Creation Settings](https://help.api.lulu.com/en/support/solutions/articles/64000254609-pdf-creation-settings) and [Book Creation Guide](https://assets.lulu.com/media/guides/en/lulu-book-creation-guide.pdf) establish the following contract.

### Interior

- Export individual pages, not reader spreads, in one PDF containing every title, copyright, story, credit, and intentionally blank page.
- For the Small Square full-bleed candidate, every page is 7.75 x 7.75 in: 7.5-in trim plus 0.125-in bleed on all four edges.
- Extend backgrounds/images intended to reach the trimmed edge through the bleed, but keep text, faces, and other important content at least 0.5 in inside the trim edge. Lulu also specifies at least a 0.2-in gutter; its guide says books under 60 pages need no additional gutter beyond the 0.5-in inside safety margin.
- Use 300–600 PPI images, embed all fonts (or convert them to outlines), flatten transparency, and rasterize vector objects as required by Lulu's settings.
- Use sRGB for newly prepared RGB artwork; do not change already-correct CMYK artwork back to RGB. Expect some screen-to-print color variance.
- Do not include crop, trim, bleed, or margin marks; do not password-protect or otherwise secure the PDF.
- Preserve physical page order explicitly: page 1 is right-hand; odd pages are right and even pages are left. This matters for both left-to-right and right-to-left source-language layouts.

### Cover

- Export one integrated spread PDF containing back cover, spine, and front cover. A front-cover JPEG or thumbnail by itself is not a valid cover file.
- Finalize the interior page count and POD package ID first, then call `POST /cover-dimensions/` to obtain the exact width and height. Cover size and spine geometry depend on both values.
- Use 300–600 PPI images, embedded fonts, and flattened transparency; include 0.125-in bleed and no printer marks or password protection.
- Keep title and other critical front/back-cover elements at least 0.75 in inside the trim for casewrap. Lulu's older API-specific settings prescribe 0.75 in for casewrap while the newer general Book Creation Guide states 0.5 in; using 0.75 in is the conservative rule that satisfies both.
- Do not put title text on the spine for this short book. Keep the screenshot as background/visual material and place overlaid title text in a high-contrast region inside the safe area; a solid or translucent text panel should be flattened into the PDF.
- No ISBN or barcode is required for a book that is not intended for retail distribution, according to the Book Creation Guide.

## File hosting and validation workflow

Lulu pulls the PDFs; it does not accept local files or multipart upload in the Print Job request. Its [required-files guidance](https://help.api.lulu.com/en/support/solutions/articles/64000254607-what-files-are-required-for-lulu-print-api-production-) requires URLs from which Lulu can download the files and allows encoded HTTP Basic Authentication in the URL. The current API examples use direct-download Dropbox links.

For this private workflow:

- Upload only the two approved print PDFs to HTTPS URLs that return the PDF bytes without an interactive login page. Unguessable, time-limited URLs are reasonable, but their expiry must extend through Lulu's asynchronous validation and normalization; keep them live until the job reaches `UNPAID` and the line item has a `printable_id`.
- Optionally supply `source_md5_sum` with each file so Lulu can check transfer integrity.
- Do not assume that an HTTP `201` means a file is print-ready. First submit the interior to `POST /validate-interior/` with the POD package ID and poll its record to terminal `NORMALIZED` (or `ERROR`). The API reports such problems as an invalid PDF, too few pages, mixed page sizes, unembedded fonts, or corrupt images.
- Use the returned page count plus the POD package ID to call `POST /cover-dimensions/`, render the exact cover, submit it to `POST /validate-cover/`, and poll to terminal `NORMALIZED` (or `ERROR`).
- Create a Print Job only with the exact validated PDFs/POD package ID. Lulu validates and normalizes again as part of the job and can reject or cancel it if the inputs or downloads fail.
- The official API materials reviewed here do not publish a general maximum PDF byte size. Treat Lulu's validation response—not an invented local limit—as authoritative, while still producing efficiently encoded PDFs.

After a printable has been successfully normalized, Lulu returns an immutable `printable_id`; future reorders can use that ID without transferring the files again. This does not remove the need to retain the locally reviewed source and print PDFs for reproducibility.

## Cost calculation and address inputs

Do not present the spreadsheet formula as a final price. Immediately before the create-job gate, call `POST /shipping-options/` for the exact destination and line item, let the user choose an available service, then call `POST /print-job-cost-calculations/`. The [OpenAPI specification](https://api.lulu.com/api-docs/openapi-specs/openapi_public.yml) requires:

- each line item's dotted `pod_package_id`, final `page_count`, and `quantity`;
- a shipping address, including a valid phone number; and
- a `shipping_option` such as `MAIL`, `GROUND`, `EXPEDITED`, or `EXPRESS` that is available for that address.

The response provides item cost and discounts, shipping/handling, fulfillment, other fees, taxes, currency, and total with and without tax. Show the exact returned total, currency, quantity, destination summary, service, and quote timestamp in the final confirmation; recalculate if any of those inputs changes.

The API itself has no subscription or startup charge. Lulu's [fee guidance](https://help.api.lulu.com/en/support/solutions/articles/64000254631-are-there-fees-to-use-lulu-s-print-api-) says orders are charged for printing, shipping, fulfillment, taxes, and any nonstandard integration services. The current [fulfillment-fee table](https://help.api.lulu.com/en/support/solutions/articles/64000265990-per-order-fulfillment-fee) lists USD 0.75 per order, independent of item count, and says the cost-calculation endpoint includes it.

The eventual Print Job also requires `contact_email`, `line_items`, `shipping_address`, and `shipping_level`. Its address schema requires recipient name, email, phone, street, city, country, and postcode (plus state where applicable). Use an idempotency-like local `external_id` and record Lulu's returned job ID so a retry cannot accidentally create a second unpaid job.

## Sandbox and production safety

Lulu provides a separate sandbox account and credentials at `https://developers.sandbox.lulu.com/`, with API base URL `https://api.sandbox.lulu.com/`. Sandbox jobs are never forwarded to physical production and can be paid with Lulu's documented test card, per the [sandbox guidance](https://help.api.lulu.com/en/support/solutions/articles/64000306383-do-you-have-a-sandbox-environment-).

Use sandbox to exercise authentication, direct-download URLs, asynchronous interior/cover validation, cover dimensions, cost calculation, job creation, status polling, cancellation, and test payment. Keep sandbox and production credentials/configuration physically separate and make the active environment conspicuous in every approval prompt. Sandbox success does not waive production prevalidation.

## Exact unpaid-job behavior

The production flow is:

1. `POST /print-jobs/` with validated sources, dotted POD package ID, quantity, delivery/contact details, and shipping level.
2. Poll the job. It begins in `CREATED` while Lulu processes it, then becomes `UNPAID` if accepted and automatic payment is off; `REJECTED`/`ERROR` must stop the flow.
3. Return the Lulu job ID, current cost/status, and instructions to open the Print Job portal. This is the nearest equivalent to “added to cart.”
4. The user pays manually in Lulu. The skill never enters card data or invokes payment.

While a job is `UNPAID`, the API permits cancellation with `PUT /print-jobs/{id}/status/` and `{ "name": "CANCELED" }`. Once paid, the job moves through payment and a mandatory production delay; `production_delay` is configurable from 60 to 2,880 minutes (48 hours), but it is not a substitute for the unpaid approval gate. Lulu says a job cannot be canceled after production starts. The reviewed official materials do not specify how long an unpaid job is retained, so the workflow should not promise indefinite cart-like storage.

Automatic payment is the main hazard. Lulu's current instructions say that saving a payment method automatically enables auto pay; removing it disables auto pay and restores individual payment in the Print Job portal. Scheduled batch payments are another payment mode that must be disabled. For the first version, use a dedicated production API account with no stored payment method, and require a one-time setup attestation plus a reminder at every production create-job gate.

## Implementation contract carried forward

- Default all integration testing to sandbox.
- Store dotted POD IDs, not legacy IDs.
- Keep product preset and final page count immutable between cover generation, PDF approval, cost calculation, and job creation; any change invalidates the cover and quote.
- Require both validators to reach `NORMALIZED` before enabling production job creation.
- Show the all-in live cost before the explicit create-job approval.
- Name the action **Create unpaid Lulu Print Job**, never “order,” “checkout,” or “add to cart.”
- Block production job creation unless the user confirms the dedicated Lulu account has automatic and scheduled payments disabled.
- After creation, verify and report `UNPAID`; if status advances toward payment/production unexpectedly, surface an urgent warning rather than claiming the safety gate held.
- Keep payment entirely manual in Lulu's portal.
