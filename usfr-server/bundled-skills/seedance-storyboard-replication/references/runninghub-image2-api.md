# RunningHub image2 API

The storyboard image channel uses RunningHub model API `2046514150500524035`:

- Model: `gpt-image-2/image-to-image-official-stable`
- Submit: `POST /openapi/v2/rhart-image-g-2-official/image-to-image`
- Query: `POST /openapi/v2/query`
- Local file upload: `POST /openapi/v2/media/upload/binary`
- Authentication: `Authorization: Bearer $RUNNINGHUB_API_KEY`

## Request

```json
{
  "prompt": "filled storyboard prompt",
  "imageUrls": ["https://.../reference.png"],
  "aspectRatio": "16:9",
  "resolution": "2k",
  "quality": "medium"
}
```

`prompt` is required and contains 1-20000 characters. `imageUrls` is required and
contains 1-10 JPG, JPEG, PNG, or WEBP references, each no larger than 10 MB.
Supported storyboard defaults are `aspectRatio=16:9`, `resolution=2k`, and
`quality=medium`.

The submit response contains `taskId`. Poll with `{"taskId": "..."}` until
`status` is `SUCCESS` or `FAILED`. A successful result URL is
`results[0].url`. The script saves the downloaded image, task/status records,
and model provenance beside the storyboard.

## Credential

Inject the key through the worker environment or an explicit private
`SEEDANCE_ENV_FILE`/`--env-file` path. A workstation `~/.codex/secrets` file is
development-only and must not be a deployment dependency:

```dotenv
RUNNINGHUB_API_KEY=
```

Never place a real key in this reference, a prompt, command output, request
record, or repository file.
