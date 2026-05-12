---
name: seedance-2-0
description: "Generate videos through public reAPI APIs using Seedance 2.0 models (default: doubao-seedance-2.0). Requires REAPI_API_KEY or REAPI_KEY from https://reapi.ai."
---

# Seedance 2.0 via reAPI

Generate videos with reAPI using Seedance 2.0 (`doubao-seedance-2.0`).

This skill is a thin public API wrapper around reAPI. It is not an official
model-provider plugin. Submit only canonical reAPI `model` values documented at
`https://reapi.ai/docs`.

## Configuration

Required:

- `REAPI_API_KEY` or `REAPI_KEY`: reAPI bearer token.

Get an API key:

1. Open `https://reapi.ai`.
2. Sign in or create an account.
3. Go to Dashboard -> API Keys.
4. Create a new key and copy it once.
5. Set it before using the skill:

```bash
export REAPI_API_KEY="rk_live_xxx"
```

Optional:

- `REAPI_BASE_URL`: override the API base URL. Defaults to `https://reapi.ai`.

Never paste or print the user's API key in final answers.

## Model Mapping

Default model:

```text
doubao-seedance-2.0
```

Supported canonical reAPI model IDs:

- `doubao-seedance-2.0`
- `doubao-seedance-2.0-fast`
- `doubao-seedance-2.0-face`
- `doubao-seedance-2.0-fast-face`

Notes:

- Default canonical model ID: `doubao-seedance-2.0`.
- Fast and face-focused variants are documented as `doubao-seedance-2.0-fast`, `doubao-seedance-2.0-face`, and `doubao-seedance-2.0-fast-face`.
- Common fields: `prompt`, `duration`, `size`, `resolution`, `seed`, `generate_audio`, `image_urls`, `video_urls`, `audio_urls`.

## Quick Start

Check configuration:

```bash
python3 scripts/reapi_model.py config
```

Print supported model IDs:

```bash
python3 scripts/reapi_model.py models
```

Print an example payload:

```bash
python3 scripts/reapi_model.py example
```

Submit a task and wait for completion:

```bash
python3 scripts/reapi_model.py submit --wait --prompt "a cinematic fox running through a snowy forest" --set duration=5 --set resolution=720p --set size=16:9
```

Submit a complete public API payload:

```bash
python3 scripts/reapi_model.py submit --wait --json '{"model":"doubao-seedance-2.0","prompt":"your prompt"}'
```

Poll an existing task:

```bash
python3 scripts/reapi_model.py wait task_xxx
```

Get a task once:

```bash
python3 scripts/reapi_model.py get task_xxx
```

## API Workflow

1. Submit to the public reAPI `videos` generation endpoint.
2. Read `id` from the response.
3. Poll `GET /api/v1/tasks/{id}` every 2-3 seconds.
4. On `status: "completed"`, return URLs from `output.video_urls`.
5. On `status: "failed"`, report the task `error.code` and `error.message`.

Polling does not consume credits. Submission requests consume credits based on
model and parameters.

## References

- `model.json`: machine-readable model mapping used by the CLI.
- `references/MODEL.md`: public model notes for this skill.
- Public docs: `https://reapi.ai/docs/seedance-2-0`
