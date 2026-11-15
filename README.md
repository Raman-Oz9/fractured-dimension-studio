# Fractured Dimension Studio

An automated YouTube Shorts production system built around cinematic graphic-novel stills, expressive camera choreography, narration, captions, and FFmpeg rendering.

## Current pipeline

1. Create a story project with a reusable character bible and series-wide visual style lock.
2. Generate each shot through a configurable Cloudflare Workers AI model chain.
3. Automatically try the configured fallback models if a model is unavailable or rejects a request. Authentication, permission, and quota errors stop immediately.
4. Add stable character descriptions to every shot prompt that references that character.
5. Record which model generated each image in `generation-report.json`.
6. Render the stills into a vertical MP4 with cinematic camera movement.

## Requirements

- Python 3.11+
- FFmpeg installed and available on `PATH`
- Cloudflare account with Workers AI access and an API token for image generation

Install:

```bash
python -m pip install -e .[dev]
```

Create a starter project:

```bash
fractured-dimension create-example --output work/example
```

Set `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` in your environment (or copy `.env.example` to `.env` and load it with your preferred environment manager). Generate the shot images:

```bash
fractured-dimension generate work/example/story.json
```

Existing images are skipped. Add `--overwrite` to regenerate them. Finally render:

```bash
fractured-dimension render work/example/story.json --output output/short.mp4
```

## Image model routing

The default primary model is Cloudflare Workers AI FLUX.1 Schnell. The default fallback chain is:

1. FLUX.1 Schnell — primary general-purpose image generation.
2. SDXL-Lightning — fast fallback.
3. SDXL Base — alternate quality/style fallback.

Override the primary model with `CLOUDFLARE_MODEL`. Override the ordered fallback chain with comma-separated model IDs in `CLOUDFLARE_FALLBACK_MODELS`. Friendly aliases include `flux-schnell`, `sdxl-lightning`, `sdxl-base`, `flux-2-dev`, and `dreamshaper`.

Cloudflare model availability, beta status, account access, and usage limits vary. The code falls back when a model request fails, but it cannot bypass account quota, missing permissions, or provider safety policies. Generation is not guaranteed to be unlimited or entirely free.

## Character continuity

Add a `character_bible` object to `story.json`. Each character should have a stable `visual_identity` description covering recognizable features, hairstyle, clothing, colours, and proportions. Add that character's ID to each relevant shot's `character_ids` list. The generator appends the same identity description and series style lock to each relevant shot prompt, and rejects references to undefined characters.

This is prompt-level consistency, not a guarantee that every generated face will be pixel-identical. The next character-consistency upgrade is image-conditioned reference generation and automated visual comparison. Cloudflare lists FLUX.2 [dev] as supporting multi-reference input, but this version does not yet send reference images to that API; it does not pretend that text prompts alone are reference-image conditioning.

## Visual direction

Graphic-novel illustration with dimensional depth, bold expressive ink, fractured geometric compositions, textured mixed media, and cinematic lighting. Use varied original characters and adapt the palette to each story. Camera movement should reveal reactions and story details: expressive close-ups of faces and hands, wider pull-outs that capture body language, purposeful pans, and controlled punch-ins—not generic static framing.

## Configuration and security

Credentials are read from environment variables. Never commit real API tokens or YouTube credentials. The repository contains placeholders only.

## Tests

```bash
pytest
```

## Roadmap

- [x] Story and shot-manifest validation.
- [x] Still-image rendering with expressive camera choreography.
- [x] Cloudflare Workers AI image-generation integration.
- [x] Multi-model fallback routing (FLUX.1 Schnell, SDXL-Lightning, SDXL Base).
- [x] Character bible and prompt-level identity/style locks.
- [x] Per-shot model generation report.
- [ ] FLUX.2 multi-reference image conditioning for stronger character consistency.
- [ ] Automated visual consistency checks and targeted regeneration.
- [ ] Narration and sound design.
- [ ] Captions and final quality checks.
- [ ] YouTube OAuth upload and scheduled publishing.
