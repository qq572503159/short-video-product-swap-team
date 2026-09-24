from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import VideoEvidence, write_json


def _segments(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("segments", value.get("items", []))
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start", item.get("start_sec", 0)))
            end = float(item.get("end", item.get("end_sec", start)))
        except (TypeError, ValueError):
            continue
        result.append({"start": max(0.0, start), "end": max(start, end), "text": str(item.get("text", item.get("content", ""))).strip()})
    return sorted(result, key=lambda item: (item["start"], item["end"]))


def _overlap(items: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    return [item for item in items if item["start"] < end and item["end"] > start]


def _frame_refs(manifest: dict[str, Any], start: float, end: float) -> list[str]:
    refs = []
    for sheet in manifest.get("shot_sheets", []):
        for frame in sheet.get("frames", []):
            timestamp = float(frame.get("timestamp", 0) or 0)
            if start <= timestamp < end:
                refs.append("Shot %02d" % int(frame.get("shot_number", 0)))
    return refs[:6]


def _scene_for_range(evidence: VideoEvidence, start: float, end: float) -> dict[str, Any]:
    matches = []
    for scene in evidence.scenes:
        try:
            scene_start = float(scene.get("start", 0) or 0)
            scene_end = float(scene.get("end", scene_start) or scene_start)
        except (TypeError, ValueError):
            continue
        if scene_start < end and scene_end > start:
            matches.append(scene)
    return max(matches, key=lambda item: float(item.get("end", 0) or 0) - float(item.get("start", 0) or 0), default={})


def _audio_summary(evidence: VideoEvidence, transcript: list[dict[str, Any]]) -> dict[str, Any]:
    has_audio = bool(evidence.audio.get("has_audio"))
    if transcript:
        status, note = "provided_transcript", "对白来自带时间戳转写，未根据画面猜测。"
    elif has_audio:
        status, note = "transcription_pending", "存在音轨，但当前未提供带时间戳转写；不可把对白猜写进拆解。"
    else:
        status, note = "no_audio", "未检测到音轨，因此没有可辨识对白。"
    return {"has_audio": has_audio, "dialogue_status": status, "dialogue_note": note, "speech_rate": "待音频分析", "language": "待音频分析", "music": "待音频分析", "environment": "待音频分析"}


def _boundaries(evidence: VideoEvidence, transcript: list[dict[str, Any]], ocr: list[dict[str, Any]], duration: float, fallback: float) -> list[float]:
    points = {0.0, round(duration, 6)}
    for scene in evidence.scenes:
        for key in ("start", "end"):
            try:
                value = float(scene.get(key, 0) or 0)
            except (TypeError, ValueError):
                continue
            if 0.0 < value < duration:
                points.add(round(value, 6))
    for item in transcript + ocr:
        for key in ("start", "end"):
            value = float(item[key])
            if 0.0 < value < duration:
                points.add(round(value, 6))
    if len(points) <= 2:
        cursor = fallback
        while cursor < duration - 1e-6:
            points.add(round(min(cursor, duration), 6))
            cursor += fallback
    ordered = sorted(points)
    result = [ordered[0]]
    for value in ordered[1:]:
        if value - result[-1] >= 0.05:
            result.append(value)
    if result[-1] != duration:
        result.append(duration)
    return result


def build_deep_analysis(evidence: VideoEvidence, manifest: dict[str, Any] | None = None, transcript_data: Any = None, ocr_data: Any = None, segment_seconds: float = 1.0) -> dict[str, Any]:
    if segment_seconds <= 0:
        raise ValueError("segment_seconds 必须大于 0")
    duration = float(evidence.metadata.get("duration", 0) or 0)
    if duration <= 0:
        duration = max((float(scene.get("end", 0) or 0) for scene in evidence.scenes), default=0.0)
    transcript, ocr, manifest = _segments(transcript_data), _segments(ocr_data), manifest or {}
    streams = evidence.metadata.get("streams", [])
    video_stream = next((item for item in streams if item.get("codec_type") == "video"), {})
    # Source captions are intentionally not part of the replication timeline.
    boundaries = _boundaries(evidence, transcript, [], duration, segment_seconds)
    segments = []
    index = 1
    for cursor, end in zip(boundaries, boundaries[1:]):
        scene = _scene_for_range(evidence, cursor, end)
        dialogue_items, subtitle_items = _overlap(transcript, cursor, end), _overlap(ocr, cursor, end)
        scene_audio = str(scene.get("audio") or "").strip()
        if dialogue_items:
            dialogue, dialogue_source = " ".join(item["text"] for item in dialogue_items if item["text"]), "provided_transcript"
        elif scene_audio:
            dialogue, dialogue_source = scene_audio, "video-shots"
        else:
            dialogue = "待转写：不可根据画面猜测对白" if evidence.audio.get("has_audio") else "无可辨识对白"
            dialogue_source = "unavailable"
        # Source subtitles are intentionally excluded from replication. New captions are authored from the edited script.
        source_subtitle = "已忽略原字幕" if subtitle_items or scene.get("onscreenText") else "原字幕未纳入复刻"
        segments.append({
            "id": "T%02d" % index, "start": round(cursor, 3), "end": round(end, 3), "frame_refs": _frame_refs(manifest, cursor, end),
            "shot_size_angle": {"shot_size": scene.get("size") or "待视觉分析", "angle": scene.get("camera") or "待视觉分析"},
            "scene_action": str(scene.get("frame") or "待视觉分析"), "lighting": {"description": "待视觉分析", "confidence": 0.0},
            "expression_emotion": "待视觉分析", "realism_details": "待视觉分析",
            "audio": {"dialogue": dialogue, "dialogue_source": dialogue_source, "sound_effects": "待音频分析", "bgm": "待音频分析"},
            "subtitle": {"source_text": source_subtitle, "text": "待新文案生成", "strategy": "ignore_source_generate_new"},
            "camera_focus": {"movement": "待视觉分析", "focus": "待视觉分析"},
            "product": {"position": "待产品一致性师标注", "size": "待标注", "orientation": "待标注", "occlusion": "待标注", "motion": "待标注"},
            "continuity": {"start_state": "待人工确认", "end_state": "待人工确认"}, "confidence": 0.0 if not scene else 0.45,
            "uncertain_items": ["需要视觉、音频和产品专项智能体补充"],
        })
        index += 1
    return {"schema_version": "deep-video-analysis@1", "source": evidence.source, "video_overview": {"style_keywords": ["真实实拍", "连续时间片", "竖屏短视频"], "core_intent": "待编导确认", "voice_summary": _audio_summary(evidence, transcript)}, "technical": {"duration": duration, "fps": video_stream.get("avg_frame_rate", video_stream.get("r_frame_rate", "")), "width": video_stream.get("width"), "height": video_stream.get("height"), "aspect_ratio": evidence.style.get("aspect") or "待计算", "has_audio": bool(evidence.audio.get("has_audio"))}, "scene_and_light": {"space": "待视觉分析", "lighting": "待视觉分析", "props": []}, "caption_policy": {"source_subtitles": "ignore", "generated_subtitles": "from_new_script", "note": "原字幕不作为复刻目标；生成阶段根据新文案重新生成字幕。"}, "segments": segments, "inputs": {"transcript_provided": bool(transcript), "ocr_provided": bool(ocr), "segment_seconds": segment_seconds, "segmentation": "adaptive_boundaries_with_interval_fallback"}, "warnings": ["未提供 ASR/OCR/视觉专项结果的字段会标记待分析，不会猜测。", "原字幕不会复制到生成提示词；字幕由新文案阶段重新设计。"]}


def render_deep_analysis_markdown(data: dict[str, Any]) -> str:
    technical, overview = data["technical"], data["video_overview"]
    lines = ["# 深度视频拆解", "", "来源：%s" % data["source"], "", "## 视频总览", "- 风格关键词：%s" % "、".join(overview["style_keywords"]), "- 核心意图：%s" % overview["core_intent"], "- 音频状态：%s" % overview["voice_summary"]["dialogue_note"], "", "## 技术信息", "- 时长：%.3fs" % technical["duration"], "- 画幅：%s × %s，%s" % (technical.get("width"), technical.get("height"), technical.get("aspect_ratio")), "- 帧率：%s" % technical.get("fps"), "", "## 逐时间片段", "", "| 时间 | 关键帧 | 场景/动作 | 原声对白 | 字幕 | 产品状态 | 连续性 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for item in data["segments"]:
        product, continuity = item["product"], item["continuity"]
        lines.append("| %.3f-%.3fs | %s | %s | %s | %s | %s；%s | %s → %s |" % (item["start"], item["end"], ", ".join(item["frame_refs"]) or "待补充", item["scene_action"], item["audio"]["dialogue"], item["subtitle"]["text"], product["position"], product["motion"], continuity["start_state"], continuity["end_state"]))
    lines.extend(["", "> 说明：对白只接受实际转写或音轨分析结果；原字幕不复刻，字幕在生成阶段根据新文案重新生成。", ""])
    return "\n".join(lines)


def run_deep_analysis(evidence_path: Path, output_dir: Path, manifest_path: Path | None = None, transcript_path: Path | None = None, ocr_path: Path | None = None, segment_seconds: float = 1.0) -> dict[str, Any]:
    data = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence = VideoEvidence(**data)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path and manifest_path.is_file() else None
    transcript = json.loads(transcript_path.read_text(encoding="utf-8")) if transcript_path and transcript_path.is_file() else None
    ocr = json.loads(ocr_path.read_text(encoding="utf-8")) if ocr_path and ocr_path.is_file() else None
    result = build_deep_analysis(evidence, manifest, transcript, ocr, segment_seconds)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "deep-analysis.json", result)
    (output_dir / "deep-analysis.md").write_text(render_deep_analysis_markdown(result), encoding="utf-8")
    return result
