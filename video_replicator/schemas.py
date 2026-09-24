from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any
import json


@dataclass
class VideoEvidence:
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)
    transcript: str = ""
    scenes: list[dict[str, Any]] = field(default_factory=list)
    frames: list[dict[str, Any]] = field(default_factory=list)
    style: dict[str, Any] = field(default_factory=dict)
    audio: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class Shot:
    id: str
    start: float
    end: float
    goal: str
    subject: str
    action: str
    camera: str
    lighting: str = ""
    dialogue: str = ""
    continuity: str = ""
    risks: list[str] = field(default_factory=list)


@dataclass
class ReplicationPlan:
    target_duration: float
    segment_max_sec: int
    aspect_ratio: str = "9:16"
    shots: list[Shot] = field(default_factory=list)
    segments: list[dict[str, Any]] = field(default_factory=list)
    prompts: list[dict[str, Any]] = field(default_factory=list)
    review_flags: list[str] = field(default_factory=list)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(value) if is_dataclass(value) else value
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
