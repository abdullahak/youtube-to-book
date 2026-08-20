# Source video acquisition and analysis

Research date: 2026-08-19

## Question

What technically reliable path can a personal Codex skill use to inspect an arbitrary public video URL, recover the original-language lyrics or dialogue, and capture print-usable nearby frames, while accurately documenting platform restrictions, unavailable inputs, and required fallbacks?

## Decision

There is **no official, reliable YouTube path from an arbitrary public watch URL to a decoded media file, arbitrary still frames, or caption text**. The skill can keep the desired `Source Video URL + Frame Cues` experience as its best-effort happy path, but it must model acquisition as a fallible adapter and make a user-supplied local media file the reliable fallback boundary.

Use this acquisition ladder:

1. **Resolve and inspect the URL without downloading media.** Normalize a supported provider URL to its stable identifier. For YouTube, fetch public metadata with `videos.list` using an API key: title, channel, duration, caption-present flag, embeddability, availability/region signals, and the thumbnail variants YouTube actually returns. YouTube documents `maxres` as 1280×720 but says it is available only for some videos. Do not manufacture thumbnail variant URLs when a variant is absent from the API response. [YouTube video resource](https://developers.google.com/youtube/v3/docs/videos), [Videos: list](https://developers.google.com/youtube/v3/docs/videos/list)
2. **Acquire an analysis file through an explicit source adapter.** A local file supplied by the operator is the reliable route. A generic direct-media URL may also be accepted after a bounded `HEAD`/`GET`, MIME-type check, size limit, and `ffprobe` validation. An HTML watch page requires a provider-specific adapter; it is not itself media.
3. **Offer YouTube extraction only as an optional, replaceable personal-tool adapter.** `yt-dlp` can often recover formats, subtitles, and thumbnails, but it is an unofficial downloader, is vulnerable to site changes and anti-bot controls, and is not a YouTube API capability. Its own project warns that its stable releases are prone to external breakage as sites change. It must never be described as reliable for every public URL. [yt-dlp project documentation](https://github.com/yt-dlp/yt-dlp#readme)
4. **Do not automatically export or persist browser cookies.** If an operator independently chooses to run a cookie-authenticated downloader, that is an external/manual recovery action, not the skill's default behavior. The yt-dlp documentation warns that browser-cookie export may export cookies for every site and must be protected. [yt-dlp cookie guidance](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp)
5. **Stop cleanly when media acquisition fails.** Preserve the URL and Frame Cues, report the concrete failure, and ask for a local video file. Do not silently switch videos, scrape through a proxy, bypass region or age restrictions, or claim that a public URL guarantees access.

This keeps the simple one-URL workflow when it happens to work, while making the product promise truthful: a public URL is a locator, not a guaranteed media input.

## What the official YouTube surfaces can and cannot do

| Need | Officially available | Boundary |
| --- | --- | --- |
| Public metadata | `videos.list` returns requested resource parts and costs one quota unit. Public fields include title, description, duration, caption availability, embeddability, license, and published thumbnail variants. | Requires an API key or another registered caller identity. It does not return a downloadable playback file. YouTube says uploaded-file details are owner-only. [Videos: list](https://developers.google.com/youtube/v3/docs/videos/list), [video resource](https://developers.google.com/youtube/v3/docs/videos#fileDetails) |
| Cover thumbnail candidate | `snippet.thumbnails` can contain `default`, `medium`, `high`, `standard`, and `maxres`; `maxres` is 1280×720 for some videos. | This is one creator/YouTube-selected image, not an arbitrary timestamp. Availability varies. Retrieval does not itself grant a license to reproduce the image in a book. [Thumbnail fields](https://developers.google.com/youtube/v3/docs/videos#snippet.thumbnails) |
| Playback at a Frame Cue | The IFrame Player API can load or seek to a requested time and report current playback time. | Seeking advances to a nearby keyframe in some cases. The API exposes playback controls, not decoded pixels or a still-image export operation. [IFrame Player API](https://developers.google.com/youtube/iframe_api_reference#Playback_controls) |
| Caption presence | `contentDetails.caption` says whether captions are available. | It does not contain caption text or establish that captions accurately represent song lyrics. [Caption presence field](https://developers.google.com/youtube/v3/docs/videos#contentDetails.caption) |
| Caption-track inventory | `captions.list` returns track metadata after OAuth authorization. | The response explicitly omits caption text. [Captions: list](https://developers.google.com/youtube/v3/docs/captions/list) |
| Caption text through the Data API | `captions.download` returns a caption track in formats including SRT and VTT. | It requires OAuth authorization **and permission to edit the video**, so it is not an arbitrary-public-video transcript API. [Captions: download](https://developers.google.com/youtube/v3/docs/captions/download) |
| Viewer transcript | YouTube's watch experience provides **Show transcript** for videos that have captions and lets a viewer jump by transcript line. | This is a viewer feature, not a documented transcript API. It is a useful manual fallback: the operator can paste/export the original-language transcript when present. [YouTube Help: View video transcripts](https://support.google.com/youtube/answer/15930243) |
| Offline download | YouTube Premium can make eligible videos available for offline playback inside YouTube. | YouTube says those files are encrypted and can only be watched in the app. It separately allows creators to download videos they uploaded and says users cannot download another user's video as an ordinary file. Neither path provides the skill an analysis file for an arbitrary public video. [YouTube offline FAQ](https://support.google.com/youtube/answer/7381437), [download your own uploads](https://support.google.com/youtube/answer/56100) |

The official API can therefore validate and describe a Source Video, provide a cover candidate, and drive an embedded player. It cannot implement the required frame-and-audio analysis for arbitrary public videos.

## Platform restrictions that the skill must state accurately

YouTube's general Terms permit personal, non-commercial viewing/listening and use of the embeddable player, but prohibit accessing, reproducing, downloading, distributing, displaying, altering, or otherwise using Content except where the service expressly authorizes it or permission has been obtained. They also prohibit automated access without prior written permission, except for the stated search-engine exception. [YouTube Terms of Service, “Permissions and Restrictions”](https://www.youtube.com/static?template=terms)

For API clients, YouTube's Developer Policies are even more explicit: an API client must not download, import, cache, or store YouTube audiovisual content without prior written approval, separate audio/video components, or use non-YouTube technology to retrieve API data or audiovisual content. [YouTube API Services Developer Policies, III.E and III.I](https://developers.google.com/youtube/terms/developer-policies)

Consequences for this private project:

- “Public” means viewable subject to YouTube's current controls; it does not mean downloadable, reusable, or technically available from every environment.
- The official API adapter must remain metadata/playback-only.
- Any `yt-dlp`, transcript-scraping, or browser-capture path must be labeled an unofficial personal-tool path, not represented as supported by YouTube, and treated as best effort.
- The map has already ruled a rights-attestation step out of this private workflow. The skill need not add one, but it also must not assert that YouTube supplied permission or that a successful download proves permission. This research records platform constraints and is not legal advice.

## Frame and original-language text pipeline after a media file exists

Once an analysis file exists, the rest of the path is technically dependable and provider-independent:

1. Validate the file with `ffprobe`; record duration, native pixel dimensions, frame rate, audio streams, and rotation.
2. For each Frame Cue, decode a small neighborhood around the timestamp at native resolution rather than taking a single exact-millisecond image. FFmpeg documents that input seeking goes to a nearby seek point and, during transcoding with accurate seeking enabled (the default), decodes and discards the extra segment up to the requested time. Sample several lossless PNG candidates around the cue and select for sharpness, unobstructed characters, and low motion while preserving the source composition. [FFmpeg `-ss` documentation](https://ffmpeg.org/ffmpeg.html#Main-options)
3. Keep the chosen source timestamp with each frame so the selection is auditable and can be revised. A cue outside the validated duration is a user-correctable error, not a reason to guess.
4. Prefer trustworthy original-language text in this order: creator-supplied/manual captions or an operator-supplied lyric sheet; then visible YouTube transcript text manually supplied by the operator; then speech recognition from the acquired audio.
5. Treat machine transcription as a draft, especially for songs, children's voices, overlapping speech, and repeated refrains. Align it to Frame Cues, display low-confidence or ambiguous passages for review, and never translate, romanize, or invent missing lyrics when the book requires source-language text.
6. If no dependable text can be recovered, keep the selected frames and ask the operator to provide/correct the wording. If no print-usable frame exists near a cue, flag it and offer a Suggested Frame Cue for approval rather than substituting one silently.

Browser-mediated playback can assist a human in locating a cue or manually capturing a visible frame, but it should be a last-resort/manual fallback: embedded playback can be unavailable, browser automation can be challenged, player chrome can contaminate screenshots, and the official IFrame API does not export source pixels.

## Required failure contract

The acquisition adapter should return structured outcomes so the conversational skill can recover without losing the user's work:

| Outcome | Meaning | Required next action |
| --- | --- | --- |
| `unsupported_source` | The URL is neither a supported provider nor a direct media URL. | Ask for a local media file; retain Frame Cues. |
| `source_unavailable` | Deleted/private video, region/age restriction, login requirement, embed disabled, or provider says unavailable. | Report the provider reason when known; ask for a local file. Do not bypass the restriction. |
| `source_rate_limited` | HTTP 429, CAPTCHA, bot check, or temporary provider throttling. | Allow a bounded later retry; otherwise ask for a local file. Do not loop or silently introduce proxies. |
| `metadata_auth_required` | Official metadata call lacks an API key/registered identity. | Explain that YouTube metadata credentials are missing; credential provisioning remains a separate map decision. |
| `media_required` | Metadata/playback worked, but no decodable analysis file is available. | Ask for a local media file. |
| `text_unavailable` | No supplied text, usable captions, transcript, or sufficiently reliable speech recognition. | Ask the operator for the source-language lyric/dialogue text; do not fabricate. |
| `frame_unusable` | Neighborhood is blurred, occluded, too small, or the cue is out of range. | Offer nearby candidates or a Suggested Frame Cue and require approval. |

Retries should be bounded and distinguish permanent provider states from temporary throttling. Media and derived-artifact retention is intentionally not decided here; it remains a separate item on the Wayfinder map.

## Concrete test: supplied Adam Wa Mishmish video

Test URL: `https://www.youtube.com/watch?v=2LaIBgvzIRY`

Observed from the current development environment on 2026-08-19:

- URL normalization produced video ID `2LaIBgvzIRY`.
- YouTube's oEmbed endpoint responded successfully with the Arabic title **أغنية الحركات للأطفال 🕺👯 | آدم ومشمش**, author **آدم ومشمش — أغاني أطفال عربية**, and a 480×360 `hqdefault` thumbnail. This established that lightweight public metadata remained reachable.
- The conventional `maxresdefault.jpg` endpoint returned HTTP 200 and a real 1280×720 thumbnail. The implementation should still use the official `snippet.thumbnails.maxres` field when available rather than infer this undocumented URL pattern.
- A YouTube Data API `videos.list` call without an API key returned HTTP 403 `PERMISSION_DENIED`: “Method doesn't allow unregistered callers.” This confirms that an API key is a real prerequisite for the official metadata adapter.
- The normal watch page returned HTTP 302 to Google's “sorry”/unusual-traffic page. The privacy-enhanced embed document returned HTTP 200, showing why embed reachability and watch-page automation must be treated separately.
- `yt-dlp` stable `2026.07.04`, with Node `23.5.0` and the recommended remote EJS component enabled, received HTTP 429 for the watch page and then `LOGIN_REQUIRED` / “Sign in to confirm you're not a bot.” No format list or media file was obtained. The project's own FAQ identifies 429 as an IP block and suggests CAPTCHA/cookies, illustrating why this cannot be the reliable contract. [yt-dlp 429 guidance](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#http-error-429-too-many-requests-or-402-payment-required)
- `youtube-transcript-api` `1.2.4` failed before it could list tracks, reporting that YouTube blocked the current IP. Its maintainer documents cloud/self-hosted IP blocking and proxy workarounds. A proxy is not an acceptable automatic fallback here because it adds cost, fragility, and restriction-bypass behavior. [youtube-transcript-api IP-block documentation](https://github.com/jdepoix/youtube-transcript-api#working-around-ip-bans-requestblocked-or-ipblocked-exception)
- No local copy of the video was available, so arbitrary frame decoding and audio transcription could not be tested. That is the expected `media_required` state, not evidence that the video lacks usable captions or frames.

The example therefore validates the layered decision: metadata/thumbnail discovery can succeed while media and transcript acquisition fail in the same session. The skill must preserve the user's Source Video and Frame Cues, explain the exact blocked layer, and request a local video (and, if needed, source-language text) rather than pretending the public URL is sufficient.

## Acceptance implications for the eventual specification

- The happy path may begin with only a URL and Frame Cues, but the interface must be able to pause for a local file without discarding either.
- Unit/integration fixtures should cover official metadata success, no `maxres` thumbnail, embed disabled, missing captions, invalid/out-of-range Frame Cues, direct-media validation, and local-file extraction.
- A network integration test against a live YouTube video can be informational only; it must not gate the build because anti-bot, region, and availability state are external and unstable.
- The first representative end-to-end acceptance test should be rerun with a local copy of the supplied example video and a small set of operator-authored Frame Cues. That is the point at which nearby-frame quality and Arabic lyric alignment can be evaluated reproducibly.
