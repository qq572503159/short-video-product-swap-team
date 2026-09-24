from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import requests


REVIEW_PROMPT = """
你是短视频复刻项目的视觉复核智能体。请分析上传的视频，输出严格 JSON，不要输出 Markdown 代码围栏。

目标：为“保留人物、场景、机位、动作和节奏，只替换产品”的复刻流程提供证据。
请主动回看关键动作和产品出现的片段，时间戳精确到 0.1 秒。必须读取音轨；对白只填写实际听到的原声或旁白，不要根据画面猜台词。原视频字幕不作为复刻目标，只记录是否存在，不要抄录字幕。

JSON 结构必须是：
{
  "video_overview": {"core_intent":"", "style_keywords":[], "language":"", "speech_rate":"", "voice_emotion":"", "audio_notes":""},
  "scene_and_light": {"space":"", "props":[], "lighting":"", "color_and_texture":""},
  "segments": [
    {
      "id":"T01", "start":0.0, "end":1.0,
      "shot_size":"", "camera_angle":"", "scene_action":"",
      "dialogue":"无可辨识对白", "dialogue_confidence":0.0,
      "expression_emotion":"", "realism_details":"",
      "sound_effects":"", "bgm":"", "camera_movement":"", "focus_change":"",
      "product": {"visible":true, "position":"", "size_ratio":"", "orientation":"", "occlusion":"", "motion":"", "start_state":"", "end_state":""},
      "source_subtitle_present":false, "confidence":0.0, "uncertain_items":[]
    }
  ]
}

切分原则：优先按镜头边界和对白边界；动作连续但对白变化时可切段；每段一般 0.5 到 3 秒，不要把多个不连续动作合并。没有人声的片段写“无可辨识对白”。如果音轨无法读取，才写“音轨无法读取”。
""".strip()


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I | re.S).strip()
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else {"raw": value}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if match:
            try:
                value = json.loads(match.group(0))
                return value if isinstance(value, dict) else {"raw": value}
            except json.JSONDecodeError:
                pass
        return {"raw_text": text}


def _upload_multipart(video: Path, api_key: str) -> dict[str, Any]:
    url = "https://generativelanguage.googleapis.com/upload/v1beta/files"
    metadata = {"file": {"display_name": video.name}}
    with video.open("rb") as handle:
        response = requests.post(
            url,
            params={"key": api_key},
            headers={"X-Goog-Upload-Protocol": "multipart"},
            files={
                "metadata": ("metadata", json.dumps(metadata), "application/json"),
                "file": (video.name, handle, "video/mp4"),
            },
            timeout=(30, 300),
        )
    response.raise_for_status()
    payload = response.json().get("file") or {}
    if not payload.get("uri"):
        raise RuntimeError("Gemini multipart 上传未返回文件 URI")
    return payload


def run_gemini_review(video: Path, output_dir: Path, model: str = "gemini-3.8-flash") -> dict[str, Any]:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("未找到 GEMINI_API_KEY，请先配置 .env")
    video = video.resolve()
    if not video.is_file():
        raise FileNotFoundError(f"找不到参考视频: {video}")
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError("缺少 google-genai，请运行: py -3.12 -m pip install google-genai python-dotenv") from exc

    client = genai.Client(api_key=api_key)
    uploaded_data = _upload_multipart(video, api_key)
    started = time.time()
    uploaded_name = uploaded_data.get("name", "")
    uploaded_uri = uploaded_data.get("uri", "")
    uploaded_state = str((uploaded_data.get("state") or "")).upper()
    while uploaded_state == "PROCESSING":
        if time.time() - started > 900:
            raise RuntimeError("Gemini 视频处理超过 15 分钟，已停止等待")
        time.sleep(2)
        uploaded = client.files.get(name=uploaded_name)
        uploaded_uri = getattr(uploaded, "uri", uploaded_uri)
        uploaded_state = str(getattr(getattr(uploaded, "state", None), "name", "")).upper()
    if uploaded_state == "FAILED":
        raise RuntimeError("Gemini 视频处理失败")

    interaction = client.interactions.create(
        model=model,
        input=[
            {"type": "video", "uri": uploaded_uri, "processing": "agentic"},
            {"type": "text", "text": REVIEW_PROMPT},
        ],
        background=True,
    )
    interaction_id = getattr(interaction, "id", "")
    if not interaction_id:
        raise RuntimeError("Gemini 未返回后台交互 ID")
    started = time.time()
    while True:
        if time.time() - started > 900:
            raise RuntimeError("Gemini 后台视觉复核超过 15 分钟，已停止等待；可使用交互 ID 重试查询")
        status = str(getattr(interaction, "status", "")).lower()
        if status in {"completed", "failed", "cancelled", "expired"}:
            break
        time.sleep(5)
        interaction = client.interactions.get(interaction_id)
    if str(getattr(interaction, "status", "")).lower() != "completed":
        raise RuntimeError(f"Gemini 后台视觉复核未完成: {getattr(interaction, 'status', 'unknown')}")
    output_text = getattr(interaction, "output_text", "") or ""
    result = _extract_json(output_text)
    result["meta"] = {
        "source_video": str(video),
        "model": model,
        "provider": "gemini-agentic-video",
        "uploaded_file_name": uploaded_name,
        "uploaded_uri": uploaded_uri,
        "interaction_id": interaction_id,
        "note": "参考视频已按用户确认上传到 Gemini；本结果仅用于视觉复核，不代表已提交视频生成。",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "gemini-visual-review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "gemini-visual-review.md").write_text(output_text + "\n", encoding="utf-8")
    return result
