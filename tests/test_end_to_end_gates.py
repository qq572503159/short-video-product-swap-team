from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from video_replicator.agents import QAAgent
from video_replicator.newapi_video import NewAPIVideoClient, run_newapi
from video_replicator.orchestrator import Orchestrator
from video_replicator.run_manifest import project_artifact_hashes
from video_replicator.schemas import ReplicationPlan, Shot


def ready_plan() -> ReplicationPlan:
    return ReplicationPlan(
        target_duration=2,
        segment_max_sec=15,
        shots=[Shot(
            id="S01",
            start=0,
            end=2,
            goal="保留镜头功能",
            subject="人物和产品",
            action="手持产品展示",
            camera="平视固定",
        )],
        segments=[{"id": "T01", "start": 0, "end": 2, "shot_ids": ["S01"]}],
        prompts=[{"segment_id": "T01", "prompt": "保留人物和构图，只替换产品"}],
    )


def prepare_approved_project(project: Path, prompt: str = "审核提示词") -> dict[str, str]:
    inputs = project / "inputs"
    analysis = project / "analysis"
    outputs = project / "outputs"
    (inputs / "product_refs").mkdir(parents=True)
    analysis.mkdir(parents=True)
    outputs.mkdir(parents=True)
    (inputs / "reference.mp4").write_bytes(b"video")
    (inputs / "product.json").write_text(json.dumps({
        "name": "测试产品",
        "references": ["inputs/product_refs/product.png"],
    }), encoding="utf-8")
    (inputs / "product_refs" / "product.png").write_bytes(b"product-image")
    (analysis / "replication-framework.json").write_text("{}", encoding="utf-8")
    (analysis / "deep-analysis.json").write_text("{}", encoding="utf-8")
    (analysis / "script-timeline.json").write_text("{}", encoding="utf-8")
    (analysis / "plan.json").write_text(json.dumps(asdict(ready_plan())), encoding="utf-8")
    (outputs / "prompts.json").write_text("{}", encoding="utf-8")
    (outputs / "final_product_swap_prompt.md").write_text(prompt, encoding="utf-8")
    collages = outputs / "reference_collages"
    collages.mkdir()
    sheet = collages / "shot-sheet-01.jpg"
    sheet.write_bytes(b"reference-sheet")
    (collages / "manifest.json").write_text(json.dumps({
        "shot_sheets": [{"output": str(sheet.resolve())}],
    }), encoding="utf-8")
    (outputs / "run-manifest.json").write_text(json.dumps({
        "input_video": {"path": str((inputs / "reference.mp4").resolve())}
    }), encoding="utf-8")
    run_newapi(project_dir=project, prompt=prompt, model="test-model", dry_run=True)
    hashes = project_artifact_hashes(project)
    (outputs / "qa.json").write_text(json.dumps({
        "status": "ready",
        "artifact_hashes": hashes,
        "flags": [],
        "blocking_flags": [],
    }), encoding="utf-8")
    (outputs / "scope-approval.json").write_text(json.dumps({
        "status": "approved",
        "reviewer": "负责人",
        "approved_at": "2026-09-27T00:00:00+08:00",
        "artifact_hashes": hashes,
    }), encoding="utf-8")
    return hashes


class EndToEndGateTests(unittest.TestCase):
    def test_missing_input_is_blocked_and_manifest_records_hash_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            missing = root / "missing.mp4"
            result = Orchestrator(root / "project").team_run(missing, 15, "9:16")
            self.assertEqual(result["status"], "blocked")
            manifest = json.loads((root / "project" / "outputs" / "run-manifest.json").read_text())
            self.assertEqual(manifest["status"], "blocked")
            self.assertFalse(manifest["input_video"]["exists"])
            self.assertNotIn("sha256", manifest["input_video"])
            history_path = root / "project" / "outputs" / "runs" / manifest["run_id"] / "run-manifest.json"
            self.assertTrue(history_path.is_file())

    def test_input_video_sha256_is_written_to_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "input.mp4"
            video.write_bytes(b"test-video")
            orchestrator = Orchestrator(root / "project")
            orchestrator.analyze(video)
            manifest = json.loads((root / "project" / "outputs" / "run-manifest.json").read_text())
            expected = hashlib.sha256(b"test-video").hexdigest()
            self.assertEqual(manifest["input_video"]["sha256"], expected)
            self.assertEqual(manifest["input_video"]["size_bytes"], len(b"test-video"))
            history_path = root / "project" / "outputs" / "runs" / manifest["run_id"] / "run-manifest.json"
            self.assertTrue(history_path.is_file())

    def test_each_analysis_run_keeps_its_own_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            video = root / "input.mp4"
            video.write_bytes(b"first")
            first = Orchestrator(root / "project")
            first.analyze(video)
            first_id = json.loads((root / "project" / "outputs" / "run-manifest.json").read_text())["run_id"]

            video.write_bytes(b"second")
            second = Orchestrator(root / "project")
            second.analyze(video)
            second_id = json.loads((root / "project" / "outputs" / "run-manifest.json").read_text())["run_id"]

            runs_dir = root / "project" / "outputs" / "runs"
            self.assertNotEqual(first_id, second_id)
            self.assertEqual(len(list(runs_dir.glob("*/run-manifest.json"))), 2)

    def test_final_qa_readies_only_matching_reviewed_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            hashes = prepare_approved_project(project)
            (project / "outputs" / "scope-approval.json").write_text(json.dumps({
                "status": "approved",
                "reviewer": "负责人",
                "approved_at": "2026-09-27T00:00:00Z",
                "artifact_hashes": hashes,
            }), encoding="utf-8")
            manifest_path = project / "outputs" / "run-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["run_id"] = "analysis-run-001"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            orchestrator = Orchestrator(project)
            ready = orchestrator.finalize_qa(project / "inputs" / "reference.mp4")
            self.assertEqual(ready["status"], "ready")
            finalized_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(finalized_manifest["run_id"], "analysis-run-001")
            self.assertTrue((project / "outputs" / "runs" / "analysis-run-001" / "run-manifest.json").is_file())

            (project / "analysis" / "replication-framework.json").write_text("edited after approval", encoding="utf-8")
            stale = orchestrator.finalize_qa(project / "inputs" / "reference.mp4")
            self.assertEqual(stale["status"], "review_required")

    def test_three_statuses_are_explicit(self) -> None:
        plan = ready_plan()
        hashes = {"input_video": "video-hash"}
        blocked = plan
        blocked.review_flags = ["S01 仍含待补充镜头字段"]
        approval = {
            "status": "approved", "reviewer": "负责人",
            "approved_at": "2026-09-27T00:00:00Z", "artifact_hashes": hashes,
        }
        blocked_result = QAAgent().run(blocked, approval, hashes)
        self.assertEqual(blocked_result["status"], "blocked")

        review_result = QAAgent().run(ready_plan(), artifact_hashes=hashes)
        self.assertEqual(review_result["status"], "review_required")

        ready_result = QAAgent().run(ready_plan(), approval, hashes)
        self.assertEqual(ready_result["status"], "ready")

    def test_review_required_cannot_submit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            prepare_approved_project(project)
            (project / "outputs" / "qa.json").write_text(json.dumps({"status": "review_required"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "status='review_required'"):
                run_newapi(
                    project_dir=project,
                    prompt="审核提示词",
                    model="test-model",
                    dry_run=False,
                    confirm_billing=True,
                )

    def test_ready_without_compiled_prompt_cannot_submit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            prepare_approved_project(project)
            (project / "outputs" / "final_product_swap_prompt.md").unlink()
            (project / "outputs" / "qa.json").write_text(json.dumps({"status": "ready"}), encoding="utf-8")
            (project / "outputs" / "scope-approval.json").write_text(json.dumps({
                "status": "approved", "reviewer": "负责人", "approved_at": "2026-09-27T00:00:00Z"
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "已编译提示词"):
                run_newapi(
                    project_dir=project,
                    prompt="测试提示词",
                    model="test-model",
                    dry_run=False,
                    confirm_billing=True,
                )

    def test_provider_rejects_prompt_argument_different_from_approved_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            prepare_approved_project(project)
            (project / "outputs" / "final_product_swap_prompt.md").write_text("未经审核的新提示词", encoding="utf-8")
            updated_hashes = project_artifact_hashes(project)
            (project / "outputs" / "qa.json").write_text(json.dumps({
                "status": "ready", "artifact_hashes": updated_hashes,
            }), encoding="utf-8")
            (project / "outputs" / "scope-approval.json").write_text(json.dumps({
                "status": "approved",
                "reviewer": "负责人",
                "approved_at": "2026-09-27T00:00:00Z",
                "artifact_hashes": updated_hashes,
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "不一致"):
                run_newapi(
                    project_dir=project,
                    prompt="另一份没有审核过的提示词",
                    model="test-model",
                    dry_run=False,
                    confirm_billing=True,
                )

    def test_ready_reaches_mock_provider_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            prepare_approved_project(project)
            captured_payloads: list[dict[str, object]] = []

            class FakeClient:
                def __init__(self) -> None:
                    self.config = SimpleNamespace(model="test-model")

                @staticmethod
                def build_payload(prompt: str, **kwargs: object) -> dict[str, object]:
                    return NewAPIVideoClient.build_payload(prompt, **kwargs)

                def create(self, payload: dict[str, object]) -> dict[str, str]:
                    captured_payloads.append(payload)
                    return {"id": "task-1"}

                @staticmethod
                def task_id(response: dict[str, object]) -> str:
                    return str(response["id"])

                def wait_for_completion(self, task_id: str, **kwargs: object) -> dict[str, object]:
                    return {"status": "completed", "video_url": "https://example.test/video.mp4"}

                @staticmethod
                def result_url(response: dict[str, object]) -> str:
                    return str(response["video_url"])

                def download(self, url: str, destination: Path) -> Path:
                    destination.write_bytes(b"generated")
                    return destination

            with patch("video_replicator.newapi_video.NewAPIVideoClient", FakeClient):
                result = run_newapi(
                    project_dir=project,
                    prompt="审核提示词",
                    model="test-model",
                    dry_run=False,
                    confirm_billing=True,
                    poll_interval=0.001,
                )
            self.assertEqual(result["status"], "completed")
            self.assertTrue(Path(result["output"]).is_file())
            self.assertEqual(captured_payloads[0]["prompt"], "审核提示词")

    def test_newapi_request_parameters_and_signed_urls_are_fingerprinted_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            prepare_approved_project(project)
            fingerprint_path = project / "outputs" / "newapi" / "request-fingerprint.json"
            fingerprint_text = fingerprint_path.read_text(encoding="utf-8")
            self.assertNotIn("signed-secret", fingerprint_text)
            self.assertIn("sha256", json.loads(fingerprint_text))
            with self.assertRaisesRegex(ValueError, "dry-run 审核请求不一致"):
                run_newapi(
                    project_dir=project,
                    prompt="审核提示词",
                    model="test-model",
                    reference_images=["https://example.test/product.png?sig=signed-secret"],
                    dry_run=False,
                    confirm_billing=True,
                )

    def test_ready_status_with_stale_artifact_hashes_cannot_submit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            prepare_approved_project(project)
            (project / "analysis" / "replication-framework.json").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "产物已变化"):
                run_newapi(
                    project_dir=project,
                    prompt="审核提示词",
                    model="test-model",
                    dry_run=False,
                    confirm_billing=True,
                )


if __name__ == "__main__":
    unittest.main()
