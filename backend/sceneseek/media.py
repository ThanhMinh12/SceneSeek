from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import subprocess

import cv2
from PIL import Image


@dataclass(slots=True)
class ExtractedFrames:
    images: list[Image.Image]
    timestamps: list[float]
    thumbnail_names: list[str]
    duration_seconds: float


def extract_frames(
    video_path: Path,
    interval_seconds: float,
    thumbnail_dir: Path | None = None,
    max_frames: int | None = None,
    max_duration: float = 600,
) -> ExtractedFrames:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError("The uploaded file could not be decoded as a video")

    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0 or frame_total <= 0:
        capture.release()
        raise ValueError("Video metadata is missing a valid frame rate or duration")
    if frame_total / fps > max_duration or frame_total / fps <= 0:
        capture.release()
        raise ValueError(f"Video must be at most {max_duration:g} seconds long")
    if capture.get(cv2.CAP_PROP_FRAME_WIDTH) * capture.get(cv2.CAP_PROP_FRAME_HEIGHT) > 3840 * 2160:
        capture.release()
        raise ValueError("Video resolution must be at most 3840 × 2160")

    images: list[Image.Image] = []
    timestamps: list[float] = []
    thumbnail_names: list[str] = []
    frame_number = 0
    sampled = 0

    if thumbnail_dir is not None:
        thumbnail_dir.mkdir(parents=True, exist_ok=True)

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            # Round each absolute timestamp, not a rounded fixed stride. At
            # 25 fps, repeating round(.5 * fps) drifts by a full frame every
            # second, which breaks normal/fast/slow alignment around shot cuts.
            if frame_number >= int(sampled * fps * interval_seconds + 0.5):
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = Image.fromarray(rgb)
                image.thumbnail((960, 540), Image.Resampling.LANCZOS)
                images.append(image.copy())
                timestamps.append(frame_number / fps)
                if thumbnail_dir is not None:
                    name = f"{sampled:06d}.jpg"
                    thumbnail = image.copy()
                    thumbnail.thumbnail((640, 360), Image.Resampling.LANCZOS)
                    thumbnail.save(thumbnail_dir / name, "JPEG", quality=82, optimize=True)
                    thumbnail_names.append(name)
                else:
                    thumbnail_names.append("")
                sampled += 1
                if max_frames is not None and sampled >= max_frames:
                    break
            frame_number += 1
    finally:
        capture.release()

    if not images:
        raise ValueError("No frames could be extracted from the uploaded video")
    return ExtractedFrames(
        images=images,
        timestamps=timestamps,
        thumbnail_names=thumbnail_names,
        duration_seconds=frame_total / fps,
    )


def browser_video(source: Path, destination: Path, duration: float) -> None:
    """Create a bounded, browser-portable VP8/WebM derivative; retain the original."""
    executable = os.getenv("SCENESEEK_FFMPEG") or shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("FFmpeg is required for browser playback. Install it or use Docker.")
    temporary = destination.with_suffix(".webm.tmp")
    try:
        subprocess.run([
            executable, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-map", "0:v:0", "-vf",
            "scale=960:540:force_original_aspect_ratio=decrease", "-c:v", "libvpx",
            "-deadline", "realtime", "-cpu-used", "8", "-b:v", "900k",
            "-threads", "1", "-an", "-f", "webm", str(temporary),
        ], check=True, timeout=min(600, duration * 3 + 30), capture_output=True)
        temporary.replace(destination)
    except subprocess.CalledProcessError as exc:
        raise ValueError("Video could not be prepared for browser playback") from exc
    finally:
        temporary.unlink(missing_ok=True)

