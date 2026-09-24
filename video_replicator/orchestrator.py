from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from .agents import AnalyzerAgent, KeyframeCurationAgent, PromptDirectorAgent, QAAgent, StoryPlannerAgent
from .deep_analysis import run_deep_analysis
from .transcription import transcribe_video
from .gemini_review import run_gemini_review
from .script_timeline import run_script_timeline
from .schemas import ReplicationPlan, Shot, VideoEvidence, read_json, write_json


class Orchestrator:
    """Small DAG runner. Each node writes one artifact and never edits another node's output."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.analysis_dir = project_dir / "analysis"
        self.output_dir = project_dir / "outputs"
        self.analysis_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def analyze(self, video: Path) -> VideoEvidence:
        evidence = AnalyzerAgent().run(video, self.analysis_dir)
        write_json(self.analysis_dir / "evidence.json", evidence)
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

    def qa(self, plan: ReplicationPlan) -> dict:
        result = QAAgent().run(plan)
        write_json(self.output_dir / "qa.json", result)
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
        return {"project_dir": str(self.project_dir), "qa": qa}

    def team_run(self, video: Path, segment_max_sec: int, aspect_ratio: str, transcription_language: str | None = None, transcription_model: str = "small") -> dict:
        steps: list[dict] = []
        evidence = self.analyze(video)
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
            "status": "review_required" if qa["flags"] else "ready_for_generation",
            "project_dir": str(self.project_dir.resolve()),
            "steps": steps,
            "next_gate": "人工确认产品替换边界、隐私和预计费用后才能提交外部生成",
        }
        write_json(self.output_dir / "team-run-report.json", result)
        return result

    def sync(self, video: Path, shots_path: Path | None = None, chrome: Path | None = None, timeout_sec: int = 120) -> dict:
        shots_path = shots_path or self.analysis_dir / "shots.json"
        if not shots_path.exists():
            return {"status": "failed", "error": f"找不到 shots.json: {shots_path}"}
        node = shutil.which("node")
        script = Path.home() / ".codex" / "skills" / "video-sync" / "scripts" / "video-sync.mjs"
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
