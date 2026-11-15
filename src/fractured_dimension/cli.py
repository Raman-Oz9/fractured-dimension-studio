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


if __name__ == "__main__":
    main()
