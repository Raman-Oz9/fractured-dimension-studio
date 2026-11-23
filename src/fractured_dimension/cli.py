"""Command-line interface."""

from __future__ import annotations

import argparse

from .images import generate_story_images
from .project import create_example, load_story
from .render import render_story


def main() -> None:
    parser = argparse.ArgumentParser(prog="fractured-dimension")
    sub = parser.add_subparsers(dest="command", required=True)

    example = sub.add_parser("create-example", help="Create an example story project")
    example.add_argument("--output", required=True)

    generate = sub.add_parser("generate", help="Generate missing shot images using configured Cloudflare model fallbacks and character continuity")
    generate.add_argument("story")
    generate.add_argument("--overwrite", action="store_true")

    render = sub.add_parser("render", help="Render a story JSON file to MP4")
    render.add_argument("story")
    render.add_argument("--output", required=True)

    publish = sub.add_parser("publish", help="Upload a rendered video to YouTube (needs YT_* secrets)")
    publish.add_argument("story")
    publish.add_argument("video")

    hook = sub.add_parser("publish-hook", help="Send the video URL and metadata to the Zapier webhook (needs ZAPIER_HOOK_URL)")
    hook.add_argument("story")
    hook.add_argument("video_url")

    args = parser.parse_args()
    if args.command == "create-example":
        path = create_example(args.output)
        print(f"Created example project: {path}")
    elif args.command == "generate":
        story = load_story(args.story)
        paths = generate_story_images(story, overwrite=args.overwrite)
        for path in paths:
            print(f"Image ready: {path}")
    elif args.command == "render":
        story = load_story(args.story)
        result = render_story(story, args.output)
        print(f"Rendered video: {result}")
    elif args.command == "publish-hook":
        from .youtube import send_to_zapier

        send_to_zapier(args.story, args.video_url)
    elif args.command == "publish":
        from pathlib import Path

        from .youtube import publish as publish_video

        timeline = Path(args.video).with_suffix(".timeline.json")
        publish_video(args.story, args.video, timeline)


if __name__ == "__main__":
    main()
