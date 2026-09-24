from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path


def run(*args: str) -> None:
    subprocess.run(list(args), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        text=True,
    )
    return float(out.strip())


def load_segments(path: Path) -> list[tuple[str, float, float, str]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    result = []
    for index, item in enumerate(data.get("segments", []), start=1):
        start, end = float(item["start"]), float(item["end"])
        text = str(item.get("adapted_dialogue", "")).strip()
        result.append((str(item.get("id") or f"T{index:02d}"), start, end, text))
    if not result:
        raise ValueError(f"时间轴没有 segments: {path}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="按项目文案时间轴生成并合并本地配音")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--video", type=Path, help="待合并视频；默认项目 outputs/newapi/generated.mp4")
    parser.add_argument("--timeline", type=Path, help="script-timeline.json；默认项目 analysis/script-timeline.json")
    parser.add_argument("--voice", default="zh-CN-YunyangNeural")
    args = parser.parse_args()

    if shutil.which("edge-tts") is None or shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise SystemExit("需要 edge-tts、ffmpeg 和 ffprobe")

    project = args.project.resolve()
    source_video = (args.video or project / "outputs/newapi/generated.mp4").resolve()
    timeline = (args.timeline or project / "analysis/script-timeline.json").resolve()
    if not source_video.is_file():
        raise SystemExit(f"找不到输入视频: {source_video}")
    if not timeline.is_file():
        raise SystemExit(f"找不到文案时间轴: {timeline}")

    segments = load_segments(timeline)
    audio_dir = source_video.parent / "exact-voiceover"
    audio_dir.mkdir(parents=True, exist_ok=True)
    normalized: list[Path] = []

    for seg_id, start, end, text in segments:
        target = end - start
        if target <= 0:
            raise ValueError(f"{seg_id} 时间范围无效")
        out = audio_dir / f"{seg_id}.wav"
        if text:
            raw = audio_dir / f"{seg_id}.mp3"
            run("edge-tts", "--voice", args.voice, "--text", text, "--rate", "+0%", "--write-media", str(raw))
            ratio = max(0.5, min(2.0, duration(raw) / target))
            run(
                "ffmpeg", "-y", "-i", str(raw),
                "-filter:a", f"atempo={ratio:.6f},apad,atrim=duration={target:.3f}",
                "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out),
            )
        else:
            run(
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-t", f"{target:.3f}", "-c:a", "pcm_s16le", str(out),
            )
        normalized.append(out)

    concat = audio_dir / "concat.txt"
    concat.write_text("\n".join(f"file '{path.as_posix()}'" for path in normalized) + "\n", encoding="utf-8")
    voiceover = audio_dir / "exact-voiceover.wav"
    run("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(voiceover))

    output_video = source_video.with_name(f"{source_video.stem}-exact-voiceover{source_video.suffix}")
    run(
        "ffmpeg", "-y", "-i", str(source_video), "-i", str(voiceover),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
        "-b:a", "128k", "-shortest", str(output_video),
    )
    report = {
        "voice": args.voice,
        "segments": [{"id": i, "start": s, "end": e, "text": t} for i, s, e, t in segments],
        "input_video": str(source_video),
        "output_video": str(output_video),
        "audio": str(voiceover),
    }
    (audio_dir / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_video)


if __name__ == "__main__":
    main()
