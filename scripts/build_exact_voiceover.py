from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "projects/demo-9-22/outputs/newapi/edited-sheets-run-20260923"
VOICE = "zh-CN-YunyangNeural"

SEGMENTS = [
    ("T01", 0.00, 0.76, "先好了"),
    ("T02", 0.76, 1.60, "没有多少单"),
    ("T03", 1.60, 2.56, "注意手速"),
    ("T04", 2.56, 3.20, "这个"),
    ("T05", 3.20, 5.36, "这个酒特别特别的好喝"),
    ("T06", 5.36, 8.16, "之前你们花大几百"),
    ("T07", 8.16, 9.80, "只买了这么一瓶酒"),
    ("T08", 9.80, 10.64, ""),
    ("T09", 10.64, 12.16, "赶紧去退了吧"),
    ("T10", 12.16, 12.56, "好"),
    ("T11", 12.56, 13.92, "现在酒厂做活动"),
    ("T12", 13.92, 15.00, "一整箱6瓶"),
]


def run(*args: str) -> None:
    subprocess.run(list(args), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def duration(path: Path) -> float:
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        text=True,
    )
    return float(out.strip())


def main() -> None:
    if shutil.which("edge-tts") is None or shutil.which("ffmpeg") is None:
        raise SystemExit("需要 edge-tts 和 ffmpeg")
    audio_dir = RUN / "exact-voiceover"
    audio_dir.mkdir(parents=True, exist_ok=True)
    normalized: list[Path] = []

    for seg_id, start, end, text in SEGMENTS:
        target = end - start
        out = audio_dir / f"{seg_id}.wav"
        if text:
            raw = audio_dir / f"{seg_id}.mp3"
            run("edge-tts", "--voice", VOICE, "--text", text, "--rate", "+0%", "--write-media", str(raw))
            src = duration(raw)
            ratio = max(0.5, min(2.0, src / target))
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
    concat.write_text("\n".join(f"file '{p.as_posix()}'" for p in normalized) + "\n", encoding="utf-8")
    voiceover = audio_dir / "exact-voiceover.wav"
    run("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(voiceover))

    source_video = RUN / "generated.mp4"
    output_video = RUN / "generated-exact-voiceover.mp4"
    run(
        "ffmpeg", "-y", "-i", str(source_video), "-i", str(voiceover),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
        "-b:a", "128k", "-shortest", str(output_video),
    )
    report = {
        "voice": VOICE,
        "segments": [{"id": i, "start": s, "end": e, "text": t} for i, s, e, t in SEGMENTS],
        "input_video": str(source_video),
        "output_video": str(output_video),
        "audio": str(voiceover),
        "note": "T08 9.80-10.64s intentionally silent to preserve the approved timeline.",
    }
    (audio_dir / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output_video)


if __name__ == "__main__":
    main()
