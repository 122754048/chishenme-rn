# RunningHub Standard Model Seedance API

USFR uses RunningHub's Standard Model API for every Seedance video task. It
requires an enterprise-shared `RUNNINGHUB_SEEDANCE_API_KEY` and never reuses
the generic RunningHub workflow key implicitly.

## Endpoints

- Create: `POST https://www.runninghub.cn/openapi/v2/bytedance/seedance-2.0-fast-token/multimodal-video`
- Query: `POST https://www.runninghub.cn/openapi/v2/query`
- Upload: `POST https://www.runninghub.cn/openapi/v2/media/upload/binary`

Use `Authorization: Bearer <RUNNINGHUB_SEEDANCE_API_KEY>` for each endpoint.
`data.download_url` returned by upload is the temporary public HTTPS reference
URL. It expires after one day.

## Fixed-B USFR request

```json
{
  "prompt": "approved compiled prompt",
  "resolution": "720p",
  "duration": "4",
  "imageUrls": ["one to nine URLs in continuous-present-role-order/v1"],
  "videoUrls": ["matching original source-video segment URL"],
  "audioUrls": [],
  "generateAudio": true,
  "ratio": "9:16",
  "realPersonMode": false,
  "conversionSlots": [],
  "returnLastFrame": false,
  "seed": -1
}
```

Every source-fidelity generated fixed-B request carries exactly one
`videoUrls[0]`: the matching original 2-15 second source segment only. It must
bind `usfr-video-reference/v1` with the source-video and source-slice SHA-256
values, exact segment time window, the complete image-binding digest, and at
least one target change. The mandatory upstream visual chain is
source Cut frames → replacement-control sheet → approved director board.
Source Cut/keyframe sheets and replacement-control sheets must never be sent to
Seedance. Target changes are a new
model/product/App/UI asset, approved script/selling-point/dialogue/lyric change,
localized language, or uploaded background music. Set `realPersonMode=true` and
`conversionSlots=["all"]`. Opaque UI-operation media and tail video remain
forbidden in `videoUrls`. The full source video must never be uploaded to
Seedance.
The selected background-music or singing segment may provide one
duration-bounded `audioUrls` item, and its compiled prompt must name it
`@Audio1`.

The request binds every image through
`usfr-multimodal-reference-binding/v2` and accepts at most nine images under
`continuous-present-role-order/v1`: @Image1 is the new model identity when a
model replacement is populated; product or App truth follows the model
identity when populated; approved director storyboard PNG pages follow the
populated target-truth images; and additional verified references follow only
with explicit purpose and Cut scope. Every approved storyboard page is uploaded
as its original confirmed PNG. The workflow must not generate, merge, crop, or
substitute an execution carrier. `seedance_execution_carrier.png` is forbidden.
A single `storyboard_url` is invalid. Enforce
`uploaded_tags == binding_tags == prompt_tags`. @Video1 is a video-slot
reference and never consumes an image index. @Audio1 is an audio-slot reference
and never consumes an image index. Source Cut/keyframe sheets and
replacement-control sheets must never be sent to Seedance.

For a local source intake, do not pre-cut or substitute another video manually.
Use `--source-video-file <source_video> --segment-plan-file <frozen_plan>
--segment-id <S01|S02>` on `runninghub_seedance_submit.py`. The adapter accepts
only the `source_video` route, derives the exact segment start/end and hashes
from the frozen plan, and then either reuses a complete 2-15 second source or
uses FFmpeg to materialize the exact window. It records
`usfr-source-video-reference/v1` beside the slice and reuses that slice only
when the source SHA-256, segment ID/window, slice SHA-256, and duration still
match. This local preparation creates no Provider task. Opaque UI-operation
and tail media have no such CLI route and cannot become `videoUrls[0]`.

Run `runninghub_seedance_submit.py --dry-run`, preserve its request SHA-256,
then submit the exact audited request with `--approved-request-sha256`. Do not
retry an upload or paid create after 429, 5xx, timeout, reset, or ambiguous
response: RunningHub media upload is never automatically retried after a 429,
5xx, timeout, connection reset, or ambiguous response, and paid Seedance
create is never automatically retried after a 429, 5xx, timeout, connection
reset, or ambiguous response. Query a
returned `taskId` only, then download the successful MP4 immediately because
result URLs expire after 24 hours. `--resume-task-id` does not require a new
prompt or duration, performs no asset preparation or payload build, and cannot
be combined with `--dry-run`.
