from __future__ import annotations

import json
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schemas import ReplicationPlan, Shot, VideoEvidence


@dataclass
class _FrameCandidate:
    path: Path
    timestamp: float | None
    source: str
    borrowed: bool = False


class KeyframeCurationAgent:
    """Build temporal evidence sheets from continuous, locally extracted frames."""

    display_name = "关键帧拼图师"
    STAGES = ("opening", "middle", "ending")
    IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

    def run(
        self,
        evidence: VideoEvidence | None,
        frames_dir: Path,
        output_dir: Path,
        max_per_stage: int = 9,
        video: Path | None = None,
        sample_interval_sec: float = 1.0,
        frames_per_sheet: int = 3,
    ) -> dict[str, Any]:
        if max_per_stage < 1:
            raise ValueError("max_per_stage 必须大于 0")
        if sample_interval_sec <= 0:
            raise ValueError("sample_interval_sec 必须大于 0")
        if frames_per_sheet <= 0:
            raise ValueError("frames_per_sheet 必须大于 0")
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageOps
        except ImportError as exc:
            raise RuntimeError("关键帧拼图需要 Pillow，请运行: python -m pip install Pillow") from exc

        candidates, warnings = self._collect_candidates(evidence, frames_dir)
        duration = self._duration(evidence, candidates)
        resolved_video = self._resolve_video(video, evidence)
        sampled_frames_dir: Path | None = None
        if resolved_video:
            sampled_frames_dir = output_dir / "sampled_frames"
            candidates = self._extract_temporal_frames(
                resolved_video, sampled_frames_dir, duration, sample_interval_sec
            )
            warnings = [
                f"已从项目参考视频按 {sample_interval_sec:g} 秒间隔抽取 {len(candidates)} 张连续时间帧。"
            ]
        if not candidates:
            raise FileNotFoundError(
                f"没有找到可用关键帧。请先运行 analyze，或把图片放入: {frames_dir}"
            )

        duration = self._duration(evidence, candidates)
        candidates.sort(key=lambda item: item.path.name.lower())
        self._fill_missing_timestamps(candidates, duration)
        candidates.sort(key=lambda item: (float(item.timestamp or 0), item.path.name.lower()))
        stages = self._split_stages(candidates, duration)
        self._borrow_for_empty_stages(stages, candidates, duration, warnings)

        output_dir.mkdir(parents=True, exist_ok=True)
        for stale in output_dir.glob("shot-sheet-*.jpg"):
            stale.unlink()
        manifest_stages: list[dict[str, Any]] = []
        stage_outputs: list[Path] = []
        for index, (name, stage_frames) in enumerate(zip(self.STAGES, stages), start=1):
            selected = self._even_sample(stage_frames, max_per_stage)
            output = output_dir / f"stage-{index:02d}-{name}.jpg"
            self._render_collage(
                selected,
                output,
                title=f"{index:02d} {name.upper()}",
                columns=3,
                image_module=Image,
                image_ops=ImageOps,
                image_draw=ImageDraw,
                image_font=ImageFont,
            )
            stage_outputs.append(output)
            start = duration * (index - 1) / 3
            end = duration * index / 3
            manifest_stages.append({
                "index": index,
                "name": name,
                "time_range": {"start": round(start, 3), "end": round(end, 3)},
                "output": str(output.resolve()),
                "candidate_count": len(stage_frames),
                "selected_count": len(selected),
                "frames": [
                    {
                        "path": str(frame.path.resolve()),
                        "timestamp": round(float(frame.timestamp or 0), 3),
                        "source": frame.source,
                        "borrowed": frame.borrowed,
                    }
                    for frame in selected
                ],
            })

        overview = output_dir / "reference-overview-3stage.jpg"
        self._render_stage_overview(
            stage_outputs,
            overview,
            image_module=Image,
            image_ops=ImageOps,
            image_draw=ImageDraw,
            image_font=ImageFont,
        )

        shot_sheets: list[dict[str, Any]] = []
        for sheet_index in range(0, len(candidates), frames_per_sheet):
            group = candidates[sheet_index:sheet_index + frames_per_sheet]
            output = output_dir / f"shot-sheet-{sheet_index // frames_per_sheet + 1:02d}.jpg"
            self._render_numbered_sheet(
                group,
                output,
                first_shot_number=sheet_index + 1,
                sheet_number=sheet_index // frames_per_sheet + 1,
                frames_per_sheet=frames_per_sheet,
                image_module=Image,
                image_ops=ImageOps,
                image_draw=ImageDraw,
                image_font=ImageFont,
            )
            shot_sheets.append({
                        "index": sheet_index // frames_per_sheet + 1,
                "output": str(output.resolve()),
                "frames": [
                    {
                        "shot_number": sheet_index + offset + 1,
                        "path": str(frame.path.resolve()),
                        "timestamp": round(float(frame.timestamp or 0), 3),
                        "source": frame.source,
                        "borrowed": frame.borrowed,
                    }
                    for offset, frame in enumerate(group)
                ],
            })

        return {
            "status": "ok",
            "source_video": str(resolved_video) if resolved_video else (evidence.source if evidence else ""),
            "frames_dir": str(frames_dir.resolve()),
            "sampled_frames_dir": str(sampled_frames_dir.resolve()) if sampled_frames_dir else None,
            "output_dir": str(output_dir.resolve()),
            "overview": str(overview.resolve()),
            "shot_sheets": shot_sheets,
            "layout": {
                "stages": 3, "columns": 3, "max_per_stage": max_per_stage,
                "shot_sheet_columns": 3,
                "frames_per_shot_sheet": frames_per_sheet,
                "shot_sheet_rows": math.ceil(frames_per_sheet / 3),
                "sample_interval_sec": sample_interval_sec,
            },
            "duration": round(duration, 3),
            "total_candidates": len(candidates),
            "stages": manifest_stages,
            "warnings": warnings,
        }

    def _collect_candidates(
        self, evidence: VideoEvidence | None, frames_dir: Path
    ) -> tuple[list[_FrameCandidate], list[str]]:
        candidates: list[_FrameCandidate] = []
        warnings: list[str] = []
        seen: set[str] = set()

        def add(raw_path: Any, timestamp: Any, source: str) -> None:
            if not raw_path:
                return
            path = self._resolve_frame_path(Path(str(raw_path)), frames_dir)
            if not path or not path.is_file():
                warnings.append(f"跳过不存在的关键帧: {raw_path}")
                return
            key = str(path.resolve()).casefold()
            if key in seen:
                return
            try:
                parsed_time = float(timestamp) if timestamp is not None else None
            except (TypeError, ValueError):
                parsed_time = None
            seen.add(key)
            candidates.append(_FrameCandidate(path, parsed_time, source))

        if evidence:
            for item in evidence.frames:
                timestamp = item.get("timestamp", item.get("time"))
                add(item.get("path") or item.get("frame"), timestamp, "evidence")
                add(item.get("start_frame"), item.get("start", timestamp), "evidence.start_frame")
                add(item.get("end_frame"), item.get("end", timestamp), "evidence.end_frame")

        if frames_dir.exists():
            for path in sorted(frames_dir.iterdir(), key=lambda item: item.name.lower()):
                if path.is_file() and path.suffix.lower() in self.IMAGE_SUFFIXES:
                    add(path, None, "frames_dir")
        elif not candidates:
            warnings.append(f"关键帧目录不存在: {frames_dir}")
        return candidates, warnings

    @staticmethod
    def _resolve_video(video: Path | None, evidence: VideoEvidence | None) -> Path | None:
        if video and video.is_file():
            return video.resolve()
        if evidence and evidence.source and Path(evidence.source).is_file():
            return Path(evidence.source).resolve()
        return None

    @staticmethod
    def _sample_timestamps(duration: float, interval: float) -> list[float]:
        if duration <= 0:
            return [0.0]
        timestamps = [
            index * interval
            for index in range(math.floor(duration / interval) + 1)
            if index * interval < duration
        ]
        if not timestamps or timestamps[0] != 0:
            timestamps.insert(0, 0.0)
        end_timestamp = max(duration - 0.05, 0.0)
        if end_timestamp - timestamps[-1] > 1e-3:
            timestamps.append(end_timestamp)
        return timestamps

    def _extract_temporal_frames(
        self, video: Path, frames_dir: Path, duration: float, interval: float
    ) -> list[_FrameCandidate]:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg:
            raise RuntimeError("按秒提取关键帧需要 ffmpeg")
        if duration <= 0 and ffprobe:
            probe = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(video)],
                capture_output=True, text=True, check=True,
            )
            duration = float(probe.stdout.strip() or 0)
        if duration <= 0:
            raise RuntimeError("无法读取视频时长，无法按秒提取关键帧")
        frames_dir.mkdir(parents=True, exist_ok=True)
        for stale in frames_dir.glob("frame-*.*"):
            stale.unlink()
        candidates: list[_FrameCandidate] = []
        for index, timestamp in enumerate(self._sample_timestamps(duration, interval), start=1):
            seek = min(timestamp, max(duration - 0.05, 0.0))
            output = frames_dir / f"frame-{index:03d}-{timestamp:07.3f}s.png"
            result = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-ss", f"{seek:.6f}", "-i", str(video), "-frames:v", "1",
                 "-c:v", "png", "-compression_level", "2", str(output)],
                capture_output=True, text=True,
            )
            if result.returncode != 0 or not output.is_file():
                raise RuntimeError(f"ffmpeg 提取 {timestamp:.3f}s 帧失败: {result.stderr.strip()}")
            candidates.append(_FrameCandidate(output, timestamp, "video.sampled"))
        return candidates

    @staticmethod
    def _resolve_frame_path(path: Path, frames_dir: Path) -> Path | None:
        if path.is_absolute() and path.exists():
            return path
        if path.exists():
            return path.resolve()
        fallback = frames_dir / path.name
        return fallback.resolve() if fallback.exists() else None

    @staticmethod
    def _duration(evidence: VideoEvidence | None, candidates: list[_FrameCandidate]) -> float:
        if evidence:
            try:
                duration = float(evidence.metadata.get("duration", 0) or 0)
            except (TypeError, ValueError):
                duration = 0
            if duration > 0:
                return duration
        known = [float(item.timestamp) for item in candidates if item.timestamp is not None]
        return max(max(known, default=0), float(max(len(candidates) - 1, 1)))

    @staticmethod
    def _fill_missing_timestamps(candidates: list[_FrameCandidate], duration: float) -> None:
        count = len(candidates)
        for index, candidate in enumerate(candidates):
            if candidate.timestamp is None:
                candidate.timestamp = duration * index / max(count - 1, 1)
            candidate.timestamp = min(max(float(candidate.timestamp), 0.0), duration)

    @staticmethod
    def _split_stages(candidates: list[_FrameCandidate], duration: float) -> list[list[_FrameCandidate]]:
        stages: list[list[_FrameCandidate]] = [[], [], []]
        for candidate in candidates:
            timestamp = float(candidate.timestamp or 0)
            index = min(int(timestamp / max(duration, 1e-9) * 3), 2)
            stages[index].append(candidate)
        return stages

    @staticmethod
    def _borrow_for_empty_stages(
        stages: list[list[_FrameCandidate]],
        candidates: list[_FrameCandidate],
        duration: float,
        warnings: list[str],
    ) -> None:
        for index, stage in enumerate(stages):
            if stage:
                continue
            midpoint = duration * (index + 0.5) / 3
            nearest = min(candidates, key=lambda item: abs(float(item.timestamp or 0) - midpoint))
            stage.append(_FrameCandidate(nearest.path, nearest.timestamp, nearest.source, borrowed=True))
            warnings.append(f"{KeyframeCurationAgent.STAGES[index]} 阶段没有独立关键帧，已借用最近帧。")

    @staticmethod
    def _even_sample(frames: list[_FrameCandidate], limit: int) -> list[_FrameCandidate]:
        if len(frames) <= limit:
            return frames
        if limit == 1:
            return [frames[len(frames) // 2]]
        indexes = [round(index * (len(frames) - 1) / (limit - 1)) for index in range(limit)]
        return [frames[index] for index in indexes]

    @staticmethod
    def _render_collage(
        frames: list[_FrameCandidate],
        output: Path,
        title: str,
        columns: int,
        image_module: Any,
        image_ops: Any,
        image_draw: Any,
        image_font: Any,
    ) -> None:
        tile_width = 480
        tile_height = 720
        header_height = 58
        label_height = 32
        gap = 12
        rows = max(1, math.ceil(len(frames) / columns))
        width = columns * tile_width + (columns + 1) * gap
        height = header_height + rows * (tile_height + label_height) + (rows + 1) * gap
        canvas = image_module.new("RGB", (width, height), "#161616")
        draw = image_draw.Draw(canvas)
        font = image_font.load_default()
        draw.text((gap, 20), title, fill="white", font=font)

        for index, frame in enumerate(frames):
            row, column = divmod(index, columns)
            x = gap + column * (tile_width + gap)
            y = header_height + gap + row * (tile_height + label_height + gap)
            with image_module.open(frame.path) as opened:
                normalized = image_ops.exif_transpose(opened).convert("RGB")
                fitted = image_ops.contain(normalized, (tile_width, tile_height))
                tile = image_module.new("RGB", (tile_width, tile_height), "black")
                tile.paste(fitted, ((tile_width - fitted.width) // 2, (tile_height - fitted.height) // 2))
                canvas.paste(tile, (x, y))
            label = f"{index + 1:02d}  {float(frame.timestamp or 0):.2f}s"
            if frame.borrowed:
                label += "  borrowed"
            draw.text((x + 8, y + tile_height + 9), label, fill="#eeeeee", font=font)

        canvas.save(output, format="JPEG", quality=92, optimize=True, progressive=True)

    @staticmethod
    def _render_stage_overview(
        stage_outputs: list[Path],
        output: Path,
        *,
        image_module: Any,
        image_ops: Any,
        image_draw: Any,
        image_font: Any,
    ) -> None:
        """Stack the three stage collages into one ordered reference image."""
        panel_width = 1200
        gap = 20
        header_height = 46
        font = image_font.load_default()
        panels: list[Any] = []
        for index, path in enumerate(stage_outputs, start=1):
            with image_module.open(path) as opened:
                normalized = image_ops.exif_transpose(opened).convert("RGB")
                ratio = panel_width / normalized.width
                panel_height = max(1, round(normalized.height * ratio))
                panel = image_ops.contain(normalized, (panel_width, panel_height))
                canvas = image_module.new("RGB", (panel_width, panel_height + header_height), "#161616")
                draw = image_draw.Draw(canvas)
                draw.text((12, 15), f"Stage {index:02d}", fill="white", font=font)
                canvas.paste(panel, ((panel_width - panel.width) // 2, header_height))
                panels.append(canvas)
        if not panels:
            return
        total_height = sum(panel.height for panel in panels) + gap * (len(panels) - 1)
        overview = image_module.new("RGB", (panel_width, total_height), "#0d0d0d")
        y = 0
        for panel in panels:
            overview.paste(panel, (0, y))
            y += panel.height + gap
        overview.save(output, format="JPEG", quality=92, optimize=True, progressive=True)

    @staticmethod
    def _render_numbered_sheet(
        frames: list[_FrameCandidate],
        output: Path,
        *,
        first_shot_number: int,
        sheet_number: int,
        frames_per_sheet: int,
        image_module: Any,
        image_ops: Any,
        image_draw: Any,
        image_font: Any,
    ) -> None:
        """Render sequential frames as a numbered storyboard sheet."""
        tile_width, tile_height = 480, 720
        header_height, gap = 58, 10
        columns = 3
        rows = max(1, math.ceil(frames_per_sheet / columns))
        width = columns * tile_width + (columns + 1) * gap
        height = rows * (header_height + tile_height) + (rows + 1) * gap
        canvas = image_module.new("RGB", (width, height), "#f1f3f6")
        font = image_font.load_default()
        for offset in range(frames_per_sheet):
            row, column = divmod(offset, columns)
            x = gap + column * (tile_width + gap)
            y = gap + row * (header_height + tile_height + gap)
            draw = image_draw.Draw(canvas)
            draw.rectangle((x, y, x + tile_width, y + header_height), fill="white")
            draw.text((x + 12, y + 12), f"Shot {first_shot_number + offset:02d}", fill="#1f2937", font=font)
            if offset < len(frames):
                draw.text(
                    (x + 12, y + 34), f"{float(frames[offset].timestamp or 0):.3f}s",
                    fill="#4b5563", font=font,
                )
            image_y = y + header_height
            if offset < len(frames):
                frame = frames[offset]
                with image_module.open(frame.path) as opened:
                    normalized = image_ops.exif_transpose(opened).convert("RGB")
                    fitted = image_ops.contain(normalized, (tile_width, tile_height))
                    tile = image_module.new("RGB", (tile_width, tile_height), "black")
                    tile.paste(fitted, ((tile_width - fitted.width) // 2, (tile_height - fitted.height) // 2))
                    canvas.paste(tile, (x, image_y))
            else:
                draw.rectangle((x, image_y, x + tile_width, image_y + tile_height), fill="#d9dde3")
        canvas.save(output, format="JPEG", quality=92, optimize=True, progressive=True)


class AnalyzerAgent:
    """Collect observable media facts; it must not invent interpretation."""

    display_name = "视频拆解师"

    def run(self, video: Path, artifacts_dir: Path | None = None) -> VideoEvidence:
        evidence = VideoEvidence(source=str(video.resolve()))
        if not video.exists():
            evidence.warnings.append(f"文件不存在: {video}")
            return evidence

        artifacts_dir = artifacts_dir or video.parent / f"{video.stem}-analysis"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        shots_script = Path.home() / ".codex" / "skills" / "video-shots" / "scripts" / "video-shots.mjs"
        node = shutil.which("node")
        if node and shots_script.exists():
            self._run_video_shots(node, shots_script, video, artifacts_dir, evidence)
        else:
            evidence.warnings.append("未找到 ReelBench video-shots 或 Node.js，将退回 ffprobe 基础分析。")

        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            evidence.warnings.append("未找到 ffprobe；仅记录文件信息，未读取视频流元数据。")
            evidence.metadata = {"size_bytes": video.stat().st_size, "suffix": video.suffix.lower()}
            return evidence

        command = [
            ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(video)
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            payload = json.loads(result.stdout)
            fmt = payload.get("format", {})
            evidence.metadata = {
                "duration": float(fmt.get("duration", 0) or 0),
                "format_name": fmt.get("format_name", ""),
                "size_bytes": int(fmt.get("size", 0) or 0),
                "streams": payload.get("streams", []),
            }
        except (subprocess.CalledProcessError, json.JSONDecodeError, ValueError) as exc:
            evidence.warnings.append(f"ffprobe 读取失败: {exc}")
        return evidence

    @staticmethod
    def _run_video_shots(node: str, script: Path, video: Path, artifacts_dir: Path, evidence: VideoEvidence) -> None:
        shots_path = artifacts_dir / "shots.json"
        track_path = artifacts_dir / "track.json"
        seed = subprocess.run(
            [node, str(script), "seed", str(video), "--track", str(track_path)],
            capture_output=True, text=True,
        )
        if seed.returncode != 0:
            evidence.warnings.append(f"video-shots seed 失败: {seed.stderr.strip()}")
            return
        shots_path.write_text(seed.stdout, encoding="utf-8")
        try:
            shots = json.loads(seed.stdout)
        except json.JSONDecodeError as exc:
            evidence.warnings.append(f"video-shots 输出不是有效 JSON: {exc}")
            return

        frames_dir = artifacts_dir / "frames"
        sheets_dir = artifacts_dir / "sheets"
        subprocess.run(
            [node, str(script), "frames", str(shots_path), "--video", str(video), "--dir", str(frames_dir)],
            capture_output=True, text=True,
        )
        subprocess.run(
            [node, str(script), "sheet", str(shots_path), "--dir", str(frames_dir), "--out", str(sheets_dir)],
            capture_output=True, text=True,
        )
        for mode, filename in (("--md", "shots.md"), ("--html", "shots-report.html")):
            rendered = subprocess.run(
                [node, str(script), "render", str(shots_path), mode, "--track", str(track_path),
                 "--frames", str(frames_dir), "--video", str(video)],
                capture_output=True, text=True,
            )
            if rendered.returncode == 0:
                (artifacts_dir / filename).write_text(rendered.stdout, encoding="utf-8")
            else:
                evidence.warnings.append(f"video-shots {mode} 失败: {rendered.stderr.strip()}")

        meta = shots.get("meta", {})
        evidence.metadata["video_shots"] = {
            "shots_path": str(shots_path), "track_path": str(track_path),
            "duration": meta.get("durationSeconds"), "fps": meta.get("fps"),
            "width": meta.get("width"), "height": meta.get("height"), "aspect": meta.get("aspect"),
        }
        evidence.scenes = shots.get("shots", [])
        evidence.frames = [
            {"shot_id": shot.get("id"), "start": shot.get("start"), "end": shot.get("end"),
             "start_frame": str(frames_dir / f"{shot.get('id')}a.jpg"),
             "end_frame": str(frames_dir / f"{shot.get('id')}b.jpg")}
            for shot in evidence.scenes
        ]
        evidence.style = {"aspect": meta.get("aspect"), "width": meta.get("width"), "height": meta.get("height")}
        evidence.audio = {"has_audio": meta.get("hasAudio", False)}


class StoryPlannerAgent:
    """Turn evidence into an editable shot/segment plan."""

    display_name = "复刻策划师"

    def run(self, evidence: VideoEvidence, segment_max_sec: int, aspect_ratio: str) -> ReplicationPlan:
        duration = float(evidence.metadata.get("duration", 0) or 0)
        if duration <= 0:
            duration = 15.0
        shots = [self._from_evidence(scene) for scene in evidence.scenes]
        if not shots:
            shots = [Shot(
                id="S01", start=0.0, end=duration,
                goal="保留参考视频的核心信息路径",
                subject="待由视觉分析 agent 补充",
                action="待由镜头分析 agent 补充",
                camera="待由镜头分析 agent 补充",
                continuity="起始状态与结束状态需要在后续拆镜头时锁定",
                risks=["当前为骨架计划，尚未完成逐镜头视觉取证"],
            )]
        segments = self._segment_shots(shots, segment_max_sec)
        flags = ["需要人工审核参考边界、产品/受众和分段上限"]
        return ReplicationPlan(duration, segment_max_sec, aspect_ratio, shots, segments, [], flags)

    @staticmethod
    def _from_evidence(scene: dict[str, Any]) -> Shot:
        frame = scene.get("frame") or "待补充画面描述"
        subjects = scene.get("subjects") or []
        subject = ", ".join(subjects) if subjects else frame
        category = scene.get("category") or "shot"
        rhythm = scene.get("rhythm") or ""
        return Shot(
            id=str(scene.get("id") or "S00"),
            start=float(scene.get("start", 0) or 0),
            end=float(scene.get("end", 0) or 0),
            goal=f"保留 {category} 镜头功能" + (f"，节奏角色：{rhythm}" if rhythm else ""),
            subject=subject,
            action=frame,
            camera=str(scene.get("camera") or "待判断"),
            dialogue=str(scene.get("audio") or ""),
            continuity=str(scene.get("transitionIn") or "cut"),
            risks=[] if scene.get("frame") else ["缺少画面描述"],
        )

    @staticmethod
    def _segment_shots(shots: list[Shot], max_sec: int) -> list[dict[str, Any]]:
        segments: list[dict[str, Any]] = []
        for shot in shots:
            start = shot.start
            while start < shot.end:
                end = min(start + max_sec, shot.end)
                segments.append({"id": f"T{len(segments) + 1:02d}", "start": start, "end": end, "shot_ids": [shot.id]})
                start = end
        return segments


class PromptDirectorAgent:
    """Write self-contained prompts from an approved shot plan."""

    display_name = "提示词导演"

    def run(self, plan: ReplicationPlan) -> ReplicationPlan:
        prompts = []
        shots_by_id = {shot.id: shot for shot in plan.shots}
        for segment in plan.segments:
            segment_shots = [shots_by_id[sid] for sid in segment["shot_ids"]]
            body = []
            for shot in segment_shots:
                body.append(
                    f"{shot.start:.2f}-{shot.end:.2f}s：{shot.action}；主体：{shot.subject}；"
                    f"镜头：{shot.camera}；连续性：{shot.continuity}。"
                )
            prompts.append({
                "segment_id": segment["id"],
                "prompt": (
                    f"竖屏 {plan.aspect_ratio}，写实短视频风格，时长不超过 {plan.segment_max_sec} 秒。"
                    + " ".join(body)
                    + " 保持主体、场景、光线和动作起止状态连续；不要擅自增加字幕、品牌或新场景。"
                ),
            })
        plan.prompts = prompts
        return plan


class QAAgent:
    """Run deterministic gates now; TypeSafe judgments can plug in here later."""

    display_name = "质量验收官"

    def run(self, plan: ReplicationPlan) -> dict[str, Any]:
        flags = list(plan.review_flags)
        if plan.segment_max_sec not in (15, 30):
            flags.append("segment_max_sec 必须为 15 或 30")
        for segment in plan.segments:
            if segment["end"] - segment["start"] > plan.segment_max_sec + 1e-6:
                flags.append(f"{segment['id']} 超过分段时长上限")
        if not plan.prompts:
            flags.append("尚未生成分段提示词")
        return {"status": "review_required" if flags else "approved", "flags": flags}
