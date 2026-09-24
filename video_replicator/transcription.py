from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _normalize_whisper_json(data: Any) -> dict[str, Any]:
    raw_segments = data.get("segments", []) if isinstance(data, dict) else []
    segments: list[dict[str, Any]] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            continue
        try:
            start = max(0.0, float(item.get("start", 0)))
            end = max(start, float(item.get("end", start)))
        except (TypeError, ValueError):
            continue
        text = str(item.get("text", "")).strip()
        if text:
            segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    return {
        "schema_version": "transcript@1",
        "language": data.get("language") if isinstance(data, dict) else None,
        "segments": segments,
        "source": "local_whisper",
    }


def transcribe_video(
    video: Path,
    output_dir: Path,
    language: str | None = None,
    model: str = "small",
    audio_format: str = "wav",
) -> dict[str, Any]:
    """Extract audio and run the locally installed Whisper CLI."""
    ffmpeg = shutil.which("ffmpeg")
    whisper = shutil.which("whisper")
    if not ffmpeg:
        raise RuntimeError("未找到 ffmpeg，无法从视频提取音频")
    if not whisper:
        raise RuntimeError("未找到 whisper CLI，请先安装 openai-whisper")
    video = video.resolve()
    if not video.is_file():
        raise FileNotFoundError(f"找不到视频: {video}")
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = output_dir / f"audio.{audio_format}"
    command = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", str(audio_path)]
    extracted = subprocess.run(command, capture_output=True, text=True)
    if extracted.returncode != 0:
        raise RuntimeError(f"音频提取失败: {extracted.stderr.strip()}")

    whisper_dir = output_dir / "whisper"
    whisper_dir.mkdir(parents=True, exist_ok=True)
    whisper_command = [whisper, str(audio_path), "--model", model, "--output_dir", str(whisper_dir), "--output_format", "json"]
    if language:
        whisper_command.extend(["--language", language])
    result = subprocess.run(whisper_command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Whisper 转写失败: {(result.stderr or result.stdout).strip()}")
    raw_json = whisper_dir / f"{audio_path.stem}.json"
    if not raw_json.is_file():
        raise RuntimeError(f"Whisper 未生成 JSON: {raw_json}")
    transcript = _normalize_whisper_json(json.loads(raw_json.read_text(encoding="utf-8")))
    transcript["video"] = str(video)
    transcript["audio"] = str(audio_path.resolve())
    transcript["model"] = model
    output_path = output_dir / "transcript.json"
    output_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "transcript.txt").write_text("\n".join(item["text"] for item in transcript["segments"]) + "\n", encoding="utf-8")
    return transcript
