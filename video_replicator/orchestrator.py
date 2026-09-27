from __future__ import annotations

from pathlib import Path
import os
import shutil
import subprocess
import uuid

from .agents import AnalyzerAgent, KeyframeCurationAgent, PromptDirectorAgent, QAAgent, StoryPlannerAgent
from .deep_analysis import run_deep_analysis
from .transcription import transcribe_video
from .gemini_review import run_gemini_review
from .script_timeline import run_script_timeline
from .schemas import ReplicationPlan, Shot, VideoEvidence, read_json, write_json
from .run_manifest import (
    input_record,
    missing_review_artifacts,
    project_artifact_hashes,
    utc_now,
    write_run_manifest,
)


class Orchestrator:
    """Small DAG runner. Each node writes one artifact and never edits another node's output."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.analysis_dir = project_dir / "analysis"
        self.output_dir = project_dir / "outputs"
        self.run_id = f"{utc_now().replace(':', '').replace('-', '').replace('.', '')}-{uuid.uuid4().hex[:8]}"
        self.run_manifest_path = self.output_dir / "run-manifest.json"
        self.analysis_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _save_run_manifest(self, manifest: dict) -> None:
        run_id = str(manifest.get("run_id") or self.run_id)
        manifest["run_id"] = run_id
        write_run_manifest(self.run_manifest_path, manifest)
        history_path = self.output_dir / "runs" / run_id / "run-manifest.json"
        write_run_manifest(history_path, manifest)

    def analyze(self, video: Path) -> VideoEvidence:
        started_at = utc_now()
        evidence = AnalyzerAgent().run(video, self.analysis_dir)
        write_json(self.analysis_dir / "evidence.json", evidence)
        self._save_run_manifest({
            "schema_version": "run-manifest@1",
            "run_id": self.run_id,
            "status": "blocked" if not video.is_file() else "review_required",
            "started_at": started_at,
            "updated_at": utc_now(),
            "input_video": input_record(video),
            "steps": [{
                "agent": AnalyzerAgent.display_name,
                "status": "blocked" if not video.is_file() else "completed",
                "output": str((self.analysis_dir / "evidence.json").resolve()),
            }],
            "artifacts": {"evidence": str((self.analysis_dir / "evidence.json").resolve())},
        })
        return evidence

    def deep_analyze(
        self,
        evidence_path: Path | None = None,
        manifest_path: Path | None = None,
        transcript_path: Path | None = None,
        ocr_path: Path | None = None,
        segment_seconds: float = 1.0,
    ) -> dict:
        evidence_path = evidence_path or self.analysis_dir / "evidence.json"
        manifest_path = manifest_path or self.output_dir / "reference_collages" / "manifest.json"
        transcript_path = transcript_path or self.analysis_dir / "transcript.json"
        return run_deep_analysis(
            evidence_path,
            self.analysis_dir,
            manifest_path,
            transcript_path,
            ocr_path,
            segment_seconds,
        )

    def transcribe(self, video: Path, language: str | None = None, model: str = "small") -> dict:
        return transcribe_video(video, self.analysis_dir, language=language, model=model)

    def gemini_review(self, video: Path, model: str = "gemini-3.8-flash") -> dict:
        return run_gemini_review(video, self.analysis_dir, model=model)

    def script_timeline(self, deep_analysis_path: Path | None = None, product_name: str = "", voice_mode: str = "new_tts") -> dict:
        deep_analysis_path = deep_analysis_path or self.analysis_dir / "deep-analysis.json"
        return run_script_timeline(deep_analysis_path, self.analysis_dir, product_name=product_name, voice_mode=voice_mode)

    def plan(self, evidence: VideoEvidence, segment_max_sec: int, aspect_ratio: str) -> ReplicationPlan:
        plan = StoryPlannerAgent().run(evidence, segment_max_sec, aspect_ratio)
        write_json(self.analysis_dir / "plan.json", plan)
        return plan

    def prompts(self, plan: ReplicationPlan) -> ReplicationPlan:
        plan = PromptDirectorAgent().run(plan)
        write_json(self.output_dir / "prompts.json", plan)
        return plan

    def review_context(self, input_video: Path | None = None) -> dict:
        if input_video is None and self.run_manifest_path.is_file():
            manifest = read_json(self.run_manifest_path)
            recorded_video = manifest.get("input_video", {}).get("path")
            input_video = Path(recorded_video) if recorded_video else None
        context = {
            "schema_version": "review-context@1",
            "updated_at": utc_now(),
            "artifact_hashes": project_artifact_hashes(self.project_dir, input_video),
        }
        write_json(self.output_dir / "review-context.json", context)
        return context

    def qa(
        self,
        plan: ReplicationPlan,
        scope_approval_path: Path | None = None,
        input_video: Path | None = None,
    ) -> dict:
        scope_approval_path = scope_approval_path or self.output_dir / "scope-approval.json"
        approval = read_json(scope_approval_path) if scope_approval_path.is_file() else None
        hashes = self.review_context(input_video)["artifact_hashes"]
        result = QAAgent().run(plan, approval, hashes)
        write_json(self.output_dir / "qa.json", result)
        return result

    def finalize_qa(self, input_video: Path | None = None) -> dict:
        plan_path = self.analysis_dir / "plan.json"
        if not plan_path.is_file():
            raise FileNotFoundError(f"缺少分析计划，无法执行最终 QA: {plan_path}")
        plan = load_plan(plan_path)
        result = self.qa(plan, input_video=input_video)
        missing = missing_review_artifacts(result.get("artifact_hashes", {}))
        if missing:
            result["status"] = "blocked"
            result["blocking_flags"].append(
                "缺少最终审核所需产物: " + ", ".join(missing)
            )
            write_json(self.output_dir / "qa.json", result)
        manifest = read_json(self.run_manifest_path) if self.run_manifest_path.is_file() else {}
        manifest.update({
            "status": result["status"],
            "updated_at": utc_now(),
            "qa": result,
            "artifacts": {
                **manifest.get("artifacts", {}),
                "qa": str((self.output_dir / "qa.json").resolve()),
                "review_context": str((self.output_dir / "review-context.json").resolve()),
            },
        })
        self._save_run_manifest(manifest)
        return result

    def keyframes(
        self,
        evidence_path: Path | None = None,
        frames_dir: Path | None = None,
        max_per_stage: int = 9,
        video: Path | None = None,
        sample_interval_sec: float = 1.0,
        frames_per_sheet: int = 3,
    ) -> dict:
        evidence_path = evidence_path or self.analysis_dir / "evidence.json"
        frames_dir = frames_dir or self.analysis_dir / "frames"
        if video is None:
            candidate = self.project_dir / "inputs" / "reference.mp4"
            video = candidate if candidate.is_file() else None
        evidence = load_evidence(evidence_path) if evidence_path.exists() else None
        result = KeyframeCurationAgent().run(
            evidence,
            frames_dir,
            self.output_dir / "reference_collages",
            max_per_stage=max_per_stage,
            video=video,
            sample_interval_sec=sample_interval_sec,
            frames_per_sheet=frames_per_sheet,
        )
        write_json(self.output_dir / "reference_collages" / "manifest.json", result)
        return result

    def run(self, video: Path, segment_max_sec: int, aspect_ratio: str) -> dict:
        evidence = self.analyze(video)
        plan = self.plan(evidence, segment_max_sec, aspect_ratio)
        plan = self.prompts(plan)
        qa = self.qa(plan)
        manifest = read_json(self.run_manifest_path)
        manifest.update({"status": qa["status"], "updated_at": utc_now(), "qa": qa})
        self._save_run_manifest(manifest)
        return {"status": qa["status"], "project_dir": str(self.project_dir), "qa": qa}

    def team_run(self, video: Path, segment_max_sec: int, aspect_ratio: str, transcription_language: str | None = None, transcription_model: str = "small") -> dict:
        steps: list[dict] = []
        evidence = self.analyze(video)
        if not video.is_file():
            qa = {
                "status": "blocked",
                "flags": [],
                "blocking_flags": [f"输入视频不存在: {video.resolve()}"],
            }
            write_json(self.output_dir / "qa.json", qa)
            steps.append({
                "agent": AnalyzerAgent.display_name,
                "status": "blocked",
                "output": str(self.analysis_dir / "evidence.json"),
                "error": qa["blocking_flags"][0],
            })
            result = {
                "status": "blocked",
                "project_dir": str(self.project_dir.resolve()),
                "steps": steps,
                "qa": qa,
                "parameters": {
                    "segment_max_sec": segment_max_sec,
                    "aspect_ratio": aspect_ratio,
                    "transcription_language": transcription_language,
                    "transcription_model": transcription_model,
                },
                "next_gate": "补充有效输入视频后重试",
            }
            write_json(self.output_dir / "team-run-report.json", result)
            manifest = read_json(self.run_manifest_path) if self.run_manifest_path.exists() else {}
            manifest.update({
                "status": "blocked",
                "updated_at": utc_now(),
                "steps": steps,
                "qa": qa,
                "parameters": result["parameters"],
                "artifacts": {
                    **manifest.get("artifacts", {}),
                    "team_report": str((self.output_dir / "team-run-report.json").resolve()),
                    "qa": str((self.output_dir / "qa.json").resolve()),
                },
            })
            self._save_run_manifest(manifest)
            return result
        steps.append({
            "agent": AnalyzerAgent.display_name,
            "status": "completed",
            "output": str(self.analysis_dir / "evidence.json"),
        })
        try:
            transcript = self.transcribe(video, language=transcription_language, model=transcription_model)
            steps.append({
                "agent": "本地语音转写师",
                "status": "completed",
                "output": str(self.analysis_dir / "transcript.json"),
                "segment_count": len(transcript.get("segments", [])),
            })
        except (RuntimeError, FileNotFoundError) as exc:
            steps.append({
                "agent": "本地语音转写师",
                "status": "skipped",
                "output": str(self.analysis_dir / "transcript.json"),
                "error": str(exc),
            })
        keyframes = self.keyframes()
        steps.append({
            "agent": KeyframeCurationAgent.display_name,
            "status": "completed",
            "output": keyframes["output_dir"],
            "shot_sheet_count": len(keyframes.get("shot_sheets", [])),
        })
        plan = self.plan(evidence, segment_max_sec, aspect_ratio)
        steps.append({
            "agent": StoryPlannerAgent.display_name,
            "status": "completed",
            "output": str(self.analysis_dir / "plan.json"),
        })
        plan = self.prompts(plan)
        steps.append({
            "agent": PromptDirectorAgent.display_name,
            "status": "completed",
            "output": str(self.output_dir / "prompts.json"),
        })
        qa = self.qa(plan)
        steps.append({
            "agent": QAAgent.display_name,
            "status": qa["status"],
            "output": str(self.output_dir / "qa.json"),
            "flags": qa["flags"],
        })
        result = {
            "status": qa["status"],
            "project_dir": str(self.project_dir.resolve()),
            "steps": steps,
            "qa": qa,
            "parameters": {
                "segment_max_sec": segment_max_sec,
                "aspect_ratio": aspect_ratio,
                "transcription_language": transcription_language,
                "transcription_model": transcription_model,
            },
            "next_gate": "人工确认产品替换边界、隐私和预计费用后才能提交外部生成",
        }
        write_json(self.output_dir / "team-run-report.json", result)
        manifest = read_json(self.run_manifest_path) if self.run_manifest_path.exists() else {}
        manifest.update({
            "status": qa["status"],
            "updated_at": utc_now(),
            "steps": steps,
            "qa": qa,
            "parameters": result["parameters"],
            "artifacts": {
                **manifest.get("artifacts", {}),
                "team_report": str((self.output_dir / "team-run-report.json").resolve()),
                "qa": str((self.output_dir / "qa.json").resolve()),
                "scope_approval": str((self.output_dir / "scope-approval.json").resolve()),
            },
        })
        self._save_run_manifest(manifest)
        return result

    def sync(self, video: Path, shots_path: Path | None = None, chrome: Path | None = None, timeout_sec: int = 120) -> dict:
        shots_path = shots_path or self.analysis_dir / "shots.json"
        if not shots_path.exists():
            return {"status": "failed", "error": f"找不到 shots.json: {shots_path}"}
        node = shutil.which("node")
        skill_roots = [
            Path(os.environ["CODEX_SKILLS_ROOT"]) if os.environ.get("CODEX_SKILLS_ROOT") else None,
            Path.home() / ".codex" / "skills",
            Path.home() / ".agents" / "skills",
        ]
        script = next(
            (
                root / "video-sync" / "scripts" / "video-sync.mjs"
                for root in skill_roots
                if root and (root / "video-sync" / "scripts" / "video-sync.mjs").exists()
            ),
            Path.home() / ".codex" / "skills" / "video-sync" / "scripts" / "video-sync.mjs",
        )
        if not node or not script.exists():
            return {"status": "failed", "error": "未找到 video-sync 或 Node.js"}
        output = self.output_dir / "synced-shot-review.mp4"
        panels = self.output_dir / "sync-panels"
        frames = self.analysis_dir / "frames"
        command = [
            node, str(script), "export", str(shots_path), "--video", str(video), "--frames", str(frames),
            "--panels", str(panels), "--lang", "zh", "-o", str(output)
        ]
        if chrome:
            command.extend(["--chrome", str(chrome)])
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            return {"status": "failed", "error": f"video-sync 超时（>{timeout_sec}s），面板可能已生成但成片未完成"}
        if result.returncode != 0:
            return {"status": "failed", "error": result.stderr.strip() or result.stdout.strip()}
        return {"status": "ok", "output": str(output), "panels": str(panels)}


def load_evidence(path: Path) -> VideoEvidence:
    data = read_json(path)
    return VideoEvidence(**data)


def load_plan(path: Path) -> ReplicationPlan:
    data = read_json(path)
    data["shots"] = [Shot(**shot) for shot in data.get("shots", [])]
    return ReplicationPlan(**data)
