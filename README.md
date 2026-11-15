# Fractured Dimension Studio

An automated YouTube Shorts production system built around cinematic graphic-novel stills, expressive camera choreography, narration, captions, and FFmpeg rendering.

## Current foundation

- Story/shot manifest format with per-shot image prompts and camera instructions.
- FFmpeg renderer for still-image sequences using controlled pan/zoom movement.
- Environment-based configuration; secrets are never stored in source.
- GitHub Actions checks and tests.

## Requirements

- Python 3.11+
- FFmpeg installed and available on `PATH`

Install:

```bash
python -m pip install -e .[dev]
```

Create a starter project:

```bash
fractured-dimension create-example --output work/example
```

Place one image per shot in the example's `images/` directory using the filenames referenced by `story.json`, then render:

```bash
fractured-dimension render work/example/story.json --output output/short.mp4
```

The current renderer turns still images into a video with cinematic pan/zoom movement. Image generation, narration, captions, and YouTube publishing are separate integrations and are not yet implemented.

## Visual direction

Graphic-novel illustration with dimensional depth, bold expressive ink, fractured geometric compositions, textured mixed media, and cinematic lighting. Use varied original characters and adapt the palette to each story. Camera movement should reveal reactions and story details: expressive close-ups, wider pull-outs, purposeful pans, and controlled punch-ins—not generic static framing.

## Configuration

Copy `.env.example` to `.env` for local development. Never commit credentials. External-service secrets will be configured separately when integrations are added.

## Tests

```bash
pytest
```

## Roadmap

1. Story and shot-manifest validation.
2. Still-image rendering with expressive camera choreography.
3. Image-generation provider integration.
4. Narration and sound design.
5. Captions and final quality checks.
6. YouTube OAuth upload and scheduled publishing.

Free service quotas and API availability vary; the project will report limits rather than promise unlimited production.
