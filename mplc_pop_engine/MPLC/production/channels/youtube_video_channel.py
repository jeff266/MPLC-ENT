#!/usr/bin/env python3
"""
YouTube Video Evidence Channel — vertical-agnostic.

Built for the Custom Vertical Builder (see
claude/Custom_Vertical_Builder_Design.md in the MPLC project). Reuses the
Serper-video-search / RapidAPI-download / OpenCV-frame-extraction / YOLO
detection mechanics already proven in
production/enrichers/healthcare_unified.py (search_youtube_videos,
download_video, extract_frames, yolo_detect_tv, analyze_frame_vlm), but
config-driven (query templates + target/excluded spaces) instead of
healthcare-hardcoded text, and with entity matching delegated to the shared,
hardened production/workers/entity_verification.py module rather than
healthcare's own verify_video_entity. Per Jeff's 2026-11-18 scoping note
("too many false positives previously... make sure we have true entity
resolution") this is a deliberate substitution, not an incidental one.

Conforms to channels/base.py's EvidenceChannel interface.
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

import requests

sys.path.insert(0, str(Path(__file__).parent))
from base import AccountContext, ChannelResult, EvidenceChannel  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent / "workers"))
from entity_verification import verify_entity_match  # noqa: E402

# Same constants as healthcare_unified.py -- duplicated rather than imported
# for the same reason documented in serper_image_channel.py: this channel
# must not depend on the enricher file it's meant to eventually replace
# (design doc §5 step 4).
SERPER_COST_PER_CALL = 0.001
RAPIDAPI_COST_PER_VIDEO = 0.0002
CLAUDE_INPUT_COST_PER_TOKEN = 0.000003
CLAUDE_OUTPUT_COST_PER_TOKEN = 0.000015

YOLO_TV_CLASS_NAMES = {"tv", "tvmonitor"}  # COCO class names covering a wall-mounted TV


class YouTubeVideoEvidenceChannel(EvidenceChannel):
    name = "youtube_video"

    def __init__(
        self,
        query_templates: List[str],
        target_spaces: List[str],
        excluded_spaces: List[str],
        serper_key: Optional[str] = None,
        rapidapi_key: Optional[str] = None,
        anthropic_key: Optional[str] = None,
        max_queries: int = 3,
        videos_per_query: int = 3,
        frames_per_video: int = 6,
        yolo_model_path: Optional[str] = None,
    ):
        self.query_templates = query_templates
        self.target_spaces = target_spaces
        self.excluded_spaces = excluded_spaces
        self.serper_key = serper_key or os.getenv("SERPER_API_KEY")
        self.rapidapi_key = rapidapi_key or os.getenv("RAPIDAPI_KEY")
        self.anthropic_key = anthropic_key or os.getenv("ANTHROPIC_API_KEY")
        self.max_queries = max_queries
        self.videos_per_query = videos_per_query
        self.frames_per_video = frames_per_video
        self.yolo_model_path = yolo_model_path or os.getenv("YOLO_MODEL_PATH", "yolov8n.pt")
        self._yolo_model = None  # lazy-loaded; a vertical that never uses this channel pays nothing

    def _format_queries(self, ctx: AccountContext) -> List[str]:
        fmt_args = {
            "account_name": ctx.account_name,
            "city": ctx.city,
            "state": ctx.state,
            "country": ctx.country,
        }
        out = []
        for template in self.query_templates[: self.max_queries]:
            try:
                out.append(template.format(**fmt_args))
            except (KeyError, IndexError):
                continue
        return out

    def _search_videos(self, ctx: AccountContext) -> tuple[list, float]:
        cost = 0.0
        videos = []
        for query in self._format_queries(ctx):
            try:
                response = requests.post(
                    "https://google.serper.dev/videos",
                    headers={"X-API-KEY": self.serper_key, "Content-Type": "application/json"},
                    data=json.dumps({"q": query, "num": 10}),
                    timeout=30,
                )
                cost += SERPER_COST_PER_CALL
                if response.status_code != 200:
                    continue
                results = response.json().get("videos", [])
                for v in results[: self.videos_per_query]:
                    link = v.get("link", "")
                    if "youtube.com" in link or "youtu.be" in link:
                        videos.append({"url": link, "title": v.get("title", ""), "query": query})
                if videos:
                    break
            except requests.RequestException:
                continue
        return videos, cost

    def _download_video(self, video_url: str, dest_dir: Path) -> Optional[Path]:
        """Downloads via RapidAPI's YouTube-downloader endpoint, same shape
        as healthcare_unified.download_video(). RapidAPI key required."""
        try:
            video_id = video_url.split("v=")[-1].split("&")[0] if "v=" in video_url else video_url.rsplit("/", 1)[-1]
            response = requests.get(
                "https://youtube-media-downloader.p.rapidapi.com/v2/video/details",
                headers={"X-RapidAPI-Key": self.rapidapi_key,
                         "X-RapidAPI-Host": "youtube-media-downloader.p.rapidapi.com"},
                params={"videoId": video_id},
                timeout=30,
            )
            if response.status_code != 200:
                return None
            data = response.json()
            formats = data.get("videos", {}).get("items", [])
            if not formats:
                return None
            download_url = formats[0].get("url")
            if not download_url:
                return None
            video_path = dest_dir / f"{video_id}.mp4"
            video_resp = requests.get(download_url, timeout=60, stream=True)
            with open(video_path, "wb") as f:
                for chunk in video_resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return video_path
        except Exception:
            return None

    def _extract_frames(self, video_path: Path, dest_dir: Path) -> List[Path]:
        """Uses ffmpeg (same tool healthcare_unified.extract_frames shells
        out to via cv2/ffmpeg) to pull evenly-spaced frames."""
        frames = []
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
                capture_output=True, text=True, timeout=15,
            )
            duration = float(probe.stdout.strip() or 0)
            if duration <= 0:
                return frames
            interval = max(duration / (self.frames_per_video + 1), 1.0)
            for i in range(1, self.frames_per_video + 1):
                ts = i * interval
                frame_path = dest_dir / f"frame_{i}.jpg"
                subprocess.run(
                    ["ffmpeg", "-y", "-ss", str(ts), "-i", str(video_path), "-frames:v", "1", str(frame_path)],
                    capture_output=True, timeout=15,
                )
                if frame_path.exists():
                    frames.append(frame_path)
        except Exception:
            pass
        return frames

    def _yolo_detect_tv(self, frame_path: Path) -> bool:
        """Same pre-filter healthcare_unified uses: skip frames with no
        detected TV before paying for a VLM call on every single frame."""
        try:
            if self._yolo_model is None:
                from ultralytics import YOLO
                self._yolo_model = YOLO(self.yolo_model_path)
            results = self._yolo_model(str(frame_path), verbose=False)
            for r in results:
                for box in r.boxes:
                    cls_name = r.names[int(box.cls[0])]
                    if cls_name.lower() in YOLO_TV_CLASS_NAMES:
                        return True
            return False
        except Exception:
            # No YOLO available / model failed to load -- don't let a
            # missing optional dependency silently reject every frame;
            # fall through and let the VLM be the sole filter instead.
            return True

    def _vlm_prompt(self, ctx: AccountContext, video_title: str) -> str:
        targets = ", ".join(self.target_spaces) or "a communal space"
        excludes = ", ".join(self.excluded_spaces) or "none specified"
        return f"""Analyze this video frame for TV evidence relevant to {ctx.account_name}.

Video title: {video_title}
Target spaces (look for TVs here): {targets}
Excluded spaces (do NOT count a TV found here): {excludes}

TV must be:
1. In one of the target spaces above
2. An entertainment/information TV showing content, not a menu board, logo
   display, black/powered-off screen, meeting-room display, or desk monitor

Answer ONLY with valid JSON:
{{
  "tv_detected": true|false,
  "tv_location": "<one of the target spaces, or none>",
  "confidence": "high|medium|low",
  "tv_powered_on": true|false,
  "reasoning": "Brief explanation"
}}"""

    def _analyze_frame_vlm(self, frame_path: Path, ctx: AccountContext, video_title: str) -> tuple[Optional[dict], float]:
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=self.anthropic_key)
            with open(frame_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode()
            response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=300,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_data}},
                        {"type": "text", "text": self._vlm_prompt(ctx, video_title)},
                    ],
                }],
            )
            cost = (response.usage.input_tokens * CLAUDE_INPUT_COST_PER_TOKEN
                    + response.usage.output_tokens * CLAUDE_OUTPUT_COST_PER_TOKEN)
            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.strip("`").lstrip("json").strip()
            return json.loads(text), cost
        except Exception:
            return None, 0.0

    def search_evidence(self, ctx: AccountContext) -> ChannelResult:
        total_cost = 0.0
        videos, search_cost = self._search_videos(ctx)
        total_cost += search_cost
        if not videos:
            return ChannelResult.rejected(self.name, "No videos found", cost=total_cost)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            for video in videos:
                # Entity verification runs ONCE per video, using the search
                # result's own url/title, before any download/ffmpeg/YOLO/VLM
                # work happens at all. (Optimization, 2026-11-18: originally
                # this ran per FRAME, after a full VLM analysis of that frame
                # -- meaning a wrong-entity video still paid for a RapidAPI
                # download, frame extraction, and VLM calls on every frame
                # before any of that got thrown away. The entity check only
                # depends on the video's url/title, which don't change frame
                # to frame, so there is nothing to gain by repeating it, and
                # everything to lose by running it last.) Same non-negotiable
                # entity-resolution requirement as SerperImageEvidenceChannel
                # -- see that file's comment for why this replaces
                # healthcare's own verify_video_entity rather than reusing it.
                verdict = verify_entity_match(
                    account_name=ctx.account_name,
                    account_industry=ctx.industry,
                    account_state=ctx.state,
                    account_website=ctx.website,
                    evidence_url=video["url"],
                    evidence_title=video["title"],
                    use_llm_arbitration=True,
                )
                total_cost += verdict.get("details", {}).get("llm_arbitration", {}).get("cost", 0.0)
                if not verdict["match"]:
                    continue

                video_path = self._download_video(video["url"], tmp_dir)
                if video_path is None:
                    continue
                total_cost += RAPIDAPI_COST_PER_VIDEO
                frames = self._extract_frames(video_path, tmp_dir)
                for frame_path in frames:
                    if not self._yolo_detect_tv(frame_path):
                        continue
                    vlm_result, vlm_cost = self._analyze_frame_vlm(frame_path, ctx, video["title"])
                    total_cost += vlm_cost
                    if not vlm_result or not vlm_result.get("tv_detected") or not vlm_result.get("tv_powered_on"):
                        continue

                    return ChannelResult(
                        tier="PROSPECT",
                        channel=self.name,
                        cost=total_cost,
                        evidence={
                            "source_url": video["url"],
                            "evidence_photo_location": str(frame_path),
                            "evidence_description": vlm_result.get("reasoning", ""),
                            "space_type": vlm_result.get("tv_location"),
                            "tv_powered_on": bool(vlm_result.get("tv_powered_on")),
                            "vlm_confidence": vlm_result.get("confidence", "low"),
                        },
                        details={"entity_match": verdict, "video_title": video["title"]},
                    )

        return ChannelResult.rejected(self.name, "No validated TV evidence found", cost=total_cost)
