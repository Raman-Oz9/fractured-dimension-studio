# Fractured Dimension Studio

An automated YouTube Shorts production system built around cinematic graphic-novel stills, expressive camera choreography, Kokoro narration, and FFmpeg rendering.

## Current pipeline

1. Create a story project with a reusable character bible, series-wide visual style lock, and narration script.
2. Generate each shot through a configurable Cloudflare Workers AI model chain.
3. Automatically try configured fallback models when a model is unavailable or rejects a request. Authentication, permission, and quota errors stop immediately.
4. Add stable character descriptions to every shot prompt that references that character.
5. Record which model generated each image in `generation-report.json`.
6. Render stills into a vertical MP4 with continuous, eased, multi-keyframe camera paths. A still illustration is treated as a navigable cinematic space, not a slideshow.
7. Generate narration with Kokoro directly on the GitHub Actions runner (default `am_adam`, selectable `bm_george`) and mux the WAV audio into the final MP4. An optional remote VoiceStudio API backend is also supported when a reachable server is configured.

## Requirements

- Python 3.11+
- FFmpeg installed and available on `PATH`
- Cloudflare account with Workers AI access and an API token for image generation
- Kokoro TTS dependencies for GitHub Actions narration (installed by the workflow)

Install:

```bash
python -m pip install -e .[dev]
```

Create a starter project:

```bash
fractured-dimension create-example --output work/example
```

Set `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` for image generation. The GitHub Actions workflow installs Kokoro and runs it directly on the hosted runner; no local computer or external speech server is required. Choose `am_adam` or `bm_george` in the workflow dispatch form. For optional remote VoiceStudio mode, set `VOICE_BACKEND=voicestudio` and add `VOICESTUDIO_BASE_URL` (including `/v1`) and `VOICESTUDIO_API_KEY` as Actions secrets. VoiceStudio's documented API still requires a reachable server; its public Cloud API is not generally released. Never commit API keys.

The GitHub Actions workflow uses Kokoro directly on the runner by default, with `am_adam` or `bm_george` selectable. Piper is no longer part of the default narration path.

Generate the shot images and render:

```bash
fractured-dimension generate work/example/story.json
fractured-dimension render work/example/story.json --output output/short.mp4
```

## Cinematic camera director

**Primary rule: never render an illustration as a frozen slide with one mechanical zoom.** Every shot gets a continuous camera path with smooth ease-in/ease-out interpolation. The camera may travel through several framings during one still image:

- **Progressive push-in:** establish the environment, approach the character, then land on the face, eyes, hands or story-critical detail.
- **Reaction close-up:** move decisively to an expression or gesture and let the audience read it before moving on.
- **Progressive pull-back:** begin on a detail and widen to reveal the body, nearby people and the wider setting.
- **Purposeful pan / tracking:** travel across the illustration to follow attention or reveal connected details.
- **Overhead / descending reveal:** use a changing vertical focal point and scale to explain layout, geography or scale.
- **Dynamic reframing:** shift the focal point instead of keeping every subject dead centre.

Camera paths are keyframed independently of the 30 FPS output. Each keyframe has a normalized time `at` (0 to 1), zoom (1.0 to 1.6), and normalized crop anchors `x` and `y` (0 to 1). The renderer smoothly interpolates between keyframes using a smoothstep ease curve. Built-in presets are available through `camera`: `push_in`, `pull_out`, `pan_left`, `pan_right`, and `hold` (a subtle moving hold). Add a `camera_path` array to any shot to choreograph a custom journey:

```json
{
  "image": "images/shot-01.png",
  "duration": 4,
  "camera": "push_in",
  "camera_path": [
    {"at": 0.0, "zoom": 1.0, "x": 0.50, "y": 0.50},
    {"at": 0.3, "zoom": 1.07, "x": 0.51, "y": 0.49},
    {"at": 0.72, "zoom": 1.17, "x": 0.53, "y": 0.44},
    {"at": 1.0, "zoom": 1.24, "x": 0.53, "y": 0.42}
  ]
}
```

The path must begin at 0 and end at 1. A zoom of 1 is the full fitted image; larger values move closer. `x=0` targets the left edge, `x=1` the right edge; `y=0` targets the top and `y=1` the bottom. Compose the source illustration with enough surrounding detail for the planned camera travel. The renderer preserves the 9:16 aspect ratio and never stretches the image. It cannot reveal content that was not present in the original still.

The default example deliberately uses a wide-to-detail move on its first image and a detail-to-context pull-back on its second image, following the camera direction in the supplied Cinematic Camera & Storytelling Skill.

## Image model routing

The default primary model is Cloudflare Workers AI FLUX.1 Schnell. The default fallback chain is:

1. FLUX.1 Schnell — primary general-purpose image generation.
2. SDXL-Lightning — fast fallback.
3. SDXL Base — alternate quality/style fallback.

Override the primary model with `CLOUDFLARE_MODEL`. Override the ordered fallback chain with comma-separated model IDs in `CLOUDFLARE_FALLBACK_MODELS`. Friendly aliases include `flux-schnell`, `sdxl-lightning`, `sdxl-base`, `flux-2-dev`, and `dreamshaper`.

Cloudflare model availability, beta status, account access, and usage limits vary. The code falls back when a model request fails, but it cannot bypass account quota, missing permissions, or provider safety policies. Generation is not guaranteed to be unlimited or entirely free.

## Character continuity

Add a `character_bible` object to `story.json`. Each character can define a stable `visual_identity`, a `reference_image` path, and a `reference_prompt`. The generator creates a reusable character sheet first, then sends that sheet as an actual image reference to FLUX.2 Klein for shots that feature the character. Reference images are resized to fit Cloudflare's 512×512 input limit. Add the character ID to each relevant shot's `character_ids` list. The generator also appends the same identity description and series style lock to each shot prompt, plus explicit single-head, facial-alignment and human-anatomy constraints to reduce duplicated or detached heads. These prompt constraints reduce errors but cannot guarantee every generated image is anatomically perfect.

FLUX.2 Klein, FLUX.2 Dev, and FLUX.2 Klein 9B are treated as reference-capable models. When a shot includes a character reference image, the router tries only this reference-capable family; it will not silently fall back to FLUX.1 Schnell or SDXL and lose the image reference. If every reference-capable option fails, that shot fails clearly instead of quietly producing a continuity-breaking image. Shots without character references can still use the general multi-model fallback chain. This improves continuity but does not guarantee pixel-identical faces. The per-shot model and whether an actual reference image was supplied are written to `generation-report.json`.

## Visual direction

Retro-cinematic graphic-novel illustration with dimensional depth, bold expressive ink, fractured geometric compositions, subtle 35mm grain, fine halftone print shading, tactile aged-paper texture, and a slightly faded vintage palette. Keep faces and midtones crisp and readable; grain must never obscure anatomy. Use varied original characters and adapt the palette to each story. Camera movement is the main storytelling tool: continuous face/hand/detail push-ins, context-revealing pull-backs, purposeful pans, tracking and reframing—not generic static framing. Images are fitted to the 9:16 canvas by aspect-ratio-preserving crop, never stretched to fit.

## Configuration and security

Credentials are read from environment variables. Never commit real API tokens or YouTube credentials. The repository contains placeholders only.

## Tests

```bash
pytest
```

## Roadmap

- [x] Story and shot-manifest validation.
- [x] Aspect-ratio-safe still-image rendering with continuous keyframed camera choreography.
- [x] Cloudflare Workers AI image-generation integration.
- [x] Multi-model fallback routing (FLUX.1 Schnell, SDXL-Lightning, SDXL Base).
- [x] Character bible and prompt-level identity/style locks.
- [x] Per-shot model generation report.
- [x] FLUX.2 multi-reference image conditioning with reference-safe model fallback for stronger character consistency.
- [x] VoiceStudio.sh API-server narration with selectable voice profiles and MP4 audio muxing.
- [ ] Word-timed captions and final quality checks.
- [ ] Background music and sound-effect mixing.
- [ ] Automated visual consistency checks and targeted regeneration.
- [ ] YouTube OAuth upload and scheduled publishing.
