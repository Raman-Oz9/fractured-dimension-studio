"""Upload a rendered Short to YouTube with the Data API v3 (standard library only).

Secrets (GitHub repository secrets, see docs/youtube-setup.md):
  YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
Optional environment:
  YT_PRIVACY   private (default) | unlisted | public
  YT_PUBLISH_AT  RFC 3339 time, e.g. 2026-11-24T16:00:00Z (the video then stays private until then)
  YT_SYNTHETIC   "1" (default) marks the video as containing altered/synthetic media
"""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
CAPTION_URL = "https://www.googleapis.com/upload/youtube/v3/captions?uploadType=multipart&part=snippet"


def access_token() -> str:
    data = urllib.parse.urlencode({
        "client_id": os.environ["YT_CLIENT_ID"],
        "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=data), timeout=60) as response:
        return json.load(response)["access_token"]


def build_metadata(story: dict[str, Any]) -> dict[str, Any]:
    """Title, description and tags from story['youtube'] with sensible Shorts defaults."""
    yt = dict(story.get("youtube") or {})
    title = str(yt.get("title") or story.get("title") or "Untitled").strip()
    if "#shorts" not in title.lower() and len(title) <= 90:
        title = f"{title} #Shorts"
    hook = " ".join(str(story["shots"][0]["narration"]).split()[:40]) if story.get("shots") else ""
    description = str(yt.get("description") or f"{hook}\n\nA horror story told in manga style.\n\n#Shorts #Horror #HorrorStories #Manga #Creepy")
    tags = list(yt.get("tags") or ["horror", "horror stories", "scary stories", "creepy", "manga", "shorts", "folklore"])
    privacy = os.environ.get("YT_PRIVACY", "private").strip().lower() or "private"
    status: dict[str, Any] = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": False,
        "containsSyntheticMedia": os.environ.get("YT_SYNTHETIC", "1") != "0",
    }
    publish_at = os.environ.get("YT_PUBLISH_AT", "").strip()
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
    return {
        "snippet": {"title": title[:100], "description": description[:4900], "tags": tags, "categoryId": "24",
                    "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": status,
    }


def _srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(timeline: list[dict[str, Any]]) -> str:
    """One caption cue per narration line (the burned-in manga captions are word by word)."""
    cues = []
    for number, entry in enumerate(timeline, 1):
        start = float(entry["speech_start"])
        end = start + float(entry["speech"])
        text = re.sub(r"\s+", " ", str(entry["narration"])).strip()
        cues.append(f"{number}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n")
    return "\n".join(cues)


def _request(url: str, token: str, *, data: bytes | None = None, headers: dict[str, str] | None = None, method: str = "POST"):
    req = urllib.request.Request(url, data=data, method=method, headers={"Authorization": f"Bearer {token}", **(headers or {})})
    return urllib.request.urlopen(req, timeout=600)


def upload_video(video: Path, metadata: dict[str, Any], token: str) -> str:
    """Resumable upload; returns the new video id."""
    size = video.stat().st_size
    start = _request(
        UPLOAD_URL, token, data=json.dumps(metadata).encode(),
        headers={"Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Type": "video/mp4",
                 "X-Upload-Content-Length": str(size)},
    )
    session = start.headers["Location"]
    with video.open("rb") as handle:
        body = handle.read()
    with _request(session, token, data=body, headers={"Content-Type": "video/mp4", "Content-Length": str(size)}, method="PUT") as response:
        return json.load(response)["id"]


def upload_captions(video_id: str, srt: str, token: str, language: str = "en") -> None:
    boundary = "fdstudio-boundary"
    meta = json.dumps({"snippet": {"videoId": video_id, "language": language, "name": "English", "isDraft": False}})
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
        f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n{srt}\r\n--{boundary}--"
    ).encode()
    _request(CAPTION_URL, token, data=body, headers={"Content-Type": f"multipart/related; boundary={boundary}"}).read()


def publish(story_path: str | Path, video: str | Path, timeline_path: str | Path | None = None) -> str:
    story = json.loads(Path(story_path).read_text(encoding="utf-8"))
    token = access_token()
    video_id = upload_video(Path(video), build_metadata(story), token)
    print(f"Uploaded: https://youtube.com/shorts/{video_id}")
    if timeline_path and Path(timeline_path).exists():
        try:
            timeline = json.loads(Path(timeline_path).read_text(encoding="utf-8"))
            timeline = timeline["timeline"] if isinstance(timeline, dict) and "timeline" in timeline else timeline
            upload_captions(video_id, build_srt(timeline), token)
            print("Caption track uploaded.")
        except Exception as exc:  # captions are a bonus; never fail the upload over them
            print(f"::warning::Caption track not uploaded: {exc}")
    return video_id
