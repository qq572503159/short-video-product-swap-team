from __future__ import annotations

"""Compile an API-ready prompt from a reviewed visual breakdown and editable copy timeline."""

import json
from pathlib import Path
from typing import Any


PLACEHOLDERS = ("待视觉分析", "待音频分析", "待人工确认", "待标注", "待补充", "待判断", "TODO", "TBD")


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _strings(item)]
    return []


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 根节点必须是对象: {path}")
    return value


def validate_framework(framework: dict[str, Any], timeline: dict[str, Any]) -> None:
    shots = framework.get("shots")
    segments = timeline.get("segments")
    if not isinstance(shots, list) or not shots:
        raise ValueError("复刻蓝图必须包含非空 shots 列表")
    if not isinstance(segments, list) or not segments:
        raise ValueError("文案时间轴必须包含非空 segments 列表")

    duration = float(framework.get("duration_seconds", 0))
    if duration <= 0:
        raise ValueError("复刻蓝图缺少有效 duration_seconds")

    previous_end = 0.0
    if abs(float(shots[0].get("start", -1))) > 0.05:
        raise ValueError("逐镜蓝图必须从 0 秒开始")
    for index, shot in enumerate(shots):
        for key in (
            "id", "start", "end", "shot_function", "shot_size", "angle_composition",
            "scene_action", "lighting", "expression_emotion", "realism_texture", "audio",
            "camera_focus", "product_state", "continuity", "confidence", "uncertain_items",
        ):
            if shot.get(key) in (None, ""):
                raise ValueError(f"镜头 {shot.get('id', '?')} 缺少必填字段 {key}")
        for key, value in shot.items():
            if any(marker in text for text in _strings(value) for marker in PLACEHOLDERS):
                raise ValueError(f"镜头 {shot['id']} 的 {key} 仍含待补充占位内容")
        start, end = float(shot["start"]), float(shot["end"])
        if start < previous_end - 0.05 or end <= start or end > duration + 0.05:
            raise ValueError(f"镜头 {shot['id']} 时间无效或顺序重叠")
        if index and abs(start - previous_end) > 0.05:
            raise ValueError(f"镜头 {shot['id']} 与前一镜之间存在未覆盖的时间段")
        previous_end = end
    if abs(previous_end - duration) > 0.05:
        raise ValueError("逐镜蓝图必须覆盖到视频结束时间")

    previous_end = 0.0
    for segment in segments:
        start, end = float(segment["start"]), float(segment["end"])
        if start < previous_end - 0.05 or end <= start or end > duration + 0.05:
            raise ValueError(f"文案片段 {segment.get('id', '?')} 时间无效或顺序重叠")
        previous_end = end


def _copy_overlapping(timeline: dict[str, Any], start: float, end: float) -> list[dict[str, Any]]:
    overlaps = []
    for segment in timeline["segments"]:
        text = str(segment.get("adapted_dialogue", "")).strip()
        left = max(start, float(segment["start"]))
        right = min(end, float(segment["end"]))
        if text and right > left:
            overlaps.append({"start": left, "end": right, "text": text})
    return overlaps


def compile_prompt(
    framework: dict[str, Any],
    timeline: dict[str, Any],
    *,
    audio_mode: str = "voiceover",
) -> str:
    validate_framework(framework, timeline)
    if audio_mode not in {"silent", "ambient", "music", "voiceover", "full"}:
        raise ValueError(f"不支持的 audio_mode: {audio_mode}")

    duration = int(round(float(framework["duration_seconds"])))
    aspect = str(framework.get("aspect_ratio", "9:16"))
    product = str(framework.get("replacement", {}).get("product_name") or timeline.get("product_name") or "目标产品")
    replacement = framework.get("replacement", {})
    overview = framework.get("overview", {})
    scene_and_light = framework.get("scene_and_light", {})
    editing = framework.get("editing", {})
    lines = [
        f"生成一条{duration}秒、{aspect}竖屏、连续单画面的写实短视频。",
        "严格执行下方逐镜时间轴：每个时间段的场景、景别、构图、主体位置、动作起止状态、运镜和镜头切点均为必须遵守的结构，不得重新编排、合并、扩写或自由创作。",
        "编号关键帧仅用于对应时间段的画面证据，不是分屏版式；禁止把拼图格子、编号或边框生成到成片。",
        "",
        f"【整体调性与内容目的】风格：{'、'.join(overview.get('style_keywords', []))}。视频内容目的：{overview.get('core_intent', '')}",
        f"【总体场景与光线】{scene_and_light.get('scene_1', '')} {scene_and_light.get('scene_2', '')} 光线：{scene_and_light.get('lighting', '')}",
        f"【剪辑节奏】真实镜头切点为：{'、'.join(f'{float(t):.2f}s' for t in editing.get('actual_cut_points_seconds', []))}。{editing.get('pace', '')}",
        f"【锁定不变】{framework.get('preserve_rule', '原片中可见的人物/身体局部、服装、场景、道具、光线方向、画幅构图、镜头次序、动作路径、镜头切点和节奏。不得新增人物、场景、道具、动作或机位。')}",
        f"【唯一替换项】将原画面中对应酒瓶统一替换为{product}。{replacement.get('product_appearance', '产品外观严格以产品参考图为准。')}",
        f"{replacement.get('placement_rule', '替换后遵循原瓶在各镜头中的位置、朝向、手部接触与遮挡关系；保持物理比例合理，并跨镜头连续。')}",
        "",
        "【逐镜复刻结构】",
    ]
    for shot in framework["shots"]:
        audio = shot["audio"]
        focus = shot["camera_focus"]
        product_state = shot["product_state"]
        continuity = shot["continuity"]
        rewritten = _copy_overlapping(timeline, float(shot["start"]), float(shot["end"]))
        rewritten_text = "；".join(
            f"{item['start']:.2f}-{item['end']:.2f}s {item['text']}" for item in rewritten
        ) or "本段无新增口播，承接上一段或保留自然停顿"
        lines.extend(
            [
                f"{shot['id']}（源镜头 {shot.get('source_shot_id', '未标注')}）｜{float(shot['start']):.2f}-{float(shot['end']):.2f}s｜对应关键帧：{'、'.join(shot.get('frame_refs', []))}",
                f"镜头功能：{shot['shot_function']}",
                f"景别/角度/构图：{shot['shot_size']}；{shot['angle_composition']}",
                f"场景与动作：{shot['scene_action']}",
                f"本段光线：{shot['lighting']}",
                f"人物/手部情绪表现：{shot['expression_emotion']}",
                f"真实质感与物理反馈：{shot['realism_texture']}",
                f"原声拆解记录仅保存在本地，不向生成模型复述原台词；原片音效观察：{audio.get('sound_effects', '')}；原片BGM观察：{audio.get('bgm', '')}",
                f"运镜/焦点：{focus.get('movement', '')}；{focus.get('focus', '')}",
                f"产品状态：位置={product_state.get('position', '')}；数量={product_state.get('quantity', '')}；朝向={product_state.get('orientation', '')}；接触={product_state.get('interaction', '')}",
                f"动作连续性：开始={continuity.get('start', '')}；结束={continuity.get('end', '')}",
                *([f"本段替换后新口播：{rewritten_text}"] if audio_mode in {"voiceover", "full"} else []),
                f"观察置信度：{shot['confidence']}；不确定项：{'；'.join(shot['uncertain_items']) if shot['uncertain_items'] else '无'}",
            ]
        )
    lines.extend(["", "【声音与口播】"])
    if audio_mode in {"voiceover", "full"}:
        lines.append("生成视频时同步生成清晰自然的普通话口播，语气、语速和停顿贴合时间轴；逐字使用下列改写文案，不漏句、不复用原视频台词、不额外添加口播：")
        lines.append("逐镜对应的新文案已写在各镜头条目中；按那些局部时间码演绎，禁止打乱镜头与台词对应关系。")
        lines.append("声音不得改变或重新设计镜头结构；按原时间轴完成口播，画面动作与口播节奏对应。")
        lines.append("不要生成字幕、屏幕文字、价格、促销字样、贴纸、按钮、角标或水印；产品标签自身内容除外。")
        if audio_mode == "voiceover":
            lines.append("不要背景音乐；仅保留口播及自然、克制的现场动作/环境声。")
    elif audio_mode == "silent":
        lines.append("输出静音视频，不生成口播、环境声或背景音乐。")
    elif audio_mode == "ambient":
        lines.append("只生成符合画面动作的现场环境声和拟音；不要口播、背景音乐或字幕。")
    else:
        lines.append("按画面生成口播、环境声和适量背景音乐；不得生成字幕或画外文字。")

    lines.extend(
        [
            "",
            "【负向约束】禁止改变上述逐镜结构；禁止新增、删减或重排镜头；禁止擅自改变人物、场景、背景、机位、产品数量关系、动作方向、镜头切点；禁止复刻原视频烧录字幕、价格和营销贴纸。产品外观以产品参考图为唯一依据，关键帧只锁定原片结构。",
        ]
    )
    return "\n".join(lines)


def compile_files(framework_path: Path, timeline_path: Path, output_path: Path, *, audio_mode: str = "voiceover") -> str:
    prompt = compile_prompt(load_json(framework_path), load_json(timeline_path), audio_mode=audio_mode)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(prompt, encoding="utf-8-sig")
    return prompt
