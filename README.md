# Fractured Dimension Studio

An automated YouTube Shorts production system built around cinematic graphic-novel stills, expressive camera choreography, narration, captions, and FFmpeg rendering.

## Current pipeline

1. Create a story project and shot manifest.
2. Generate missing shot images through Cloudflare Workers AI.
3. Render the stills into a vertical MP4 with cinematic camera movement.

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

Set `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` in your environment (or copy `.env.example` to `.env` and load it with your preferred environment manager). Then generate the shot images:

```bash
fractured-dimension generate work/example/story.json
```

Existing images are skipped. Add `--overwrite` to regenerate them. Finally render:

```bash
fractured-dimension render work/example/story.json --output output/short.mp4
```

The default image model is Cloudflare Workers AI `@cf/black-forest-labs/flux-1-schnell`. Model availability, account access, and usage limits depend on Cloudflare's current plan and terms; generation is not guaranteed to be unlimited or entirely free.

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
- [ ] Narration and sound design.
- [ ] Captions and final quality checks.
- [ ] YouTube OAuth upload and scheduled publishing.
