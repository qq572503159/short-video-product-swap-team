from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_script_timeline(
    deep_analysis: dict[str, Any],
    product_name: str = "",
    voice_mode: str = "new_tts",
) -> dict[str, Any]:
    """Create an editable copy/script timeline without copying source subtitles."""
    segments = []
    for item in deep_analysis.get("segments", []):
        audio = item.get("audio", {})
        original = str(audio.get("dialogue", "")).strip()
        if original.startswith("待转写"):
            original = ""
        segments.append({
            "id": item.get("id", f"T{len(segments) + 1:02d}"),
            "start": item.get("start", 0),
            "end": item.get("end", 0),
            "original_dialogue": original,
            "adapted_dialogue": original,
            "subtitle_text": "",
            "voice_mode": voice_mode,
            "product_name": product_name,
            "delivery_notes": "根据新文案重新生成字幕；不复刻原视频字幕。",
            "needs_review": not bool(original),
        })
    return {
        "schema_version": "script-timeline@1",
        "source": deep_analysis.get("source", ""),
        "product_name": product_name,
        "voice_mode": voice_mode,
        "subtitle_policy": "ignore_source_generate_new",
        "editing_instructions": [
            "只修改 adapted_dialogue 和 subtitle_text，不修改原始对白字段。",
            "每段文案必须适配对应 start/end 时间，不要把多段对白合并。",
            "voice_mode 可选 original_audio、new_tts、new_human_voice。",
        ],
        "segments": segments,
    }


def render_script_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# 可编辑文案时间轴",
        "",
        f"产品：{data.get('product_name') or '待填写'}",
        f"配音策略：{data.get('voice_mode')}",
        "字幕策略：忽略原字幕，根据新文案重新生成",
        "",
        "| 时间 | 原声对白 | 改写文案 | 新字幕 | 配音策略 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in data.get("segments", []):
        lines.append(
            "| %.3f-%.3fs | %s | %s | %s | %s |" % (
                float(item.get("start", 0)), float(item.get("end", 0)),
                item.get("original_dialogue", ""), item.get("adapted_dialogue", ""),
                item.get("subtitle_text", ""), item.get("voice_mode", ""),
            )
        )
    lines.extend(["", "编辑规则：保留原声对白字段作为取证；只编辑改写文案和新字幕。", ""])
    return "\n".join(lines)


def run_script_timeline(deep_analysis_path: Path, output_dir: Path, product_name: str = "", voice_mode: str = "new_tts") -> dict[str, Any]:
    data = json.loads(deep_analysis_path.read_text(encoding="utf-8"))
    result = build_script_timeline(data, product_name=product_name, voice_mode=voice_mode)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "script-timeline.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "adapted_script.md").write_text(render_script_markdown(result), encoding="utf-8")
    return result
