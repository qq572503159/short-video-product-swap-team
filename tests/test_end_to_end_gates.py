from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from video_replicator.agents import QAAgent
from video_replicator.newapi_video import NewAPIVideoClient, run_newapi
from video_replicator.orchestrator import Orchestrator
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

    def test_three_statuses_are_explicit(self) -> None:
        plan = ready_plan()
        blocked = plan
        blocked.review_flags = ["S01 仍含待补充镜头字段"]
        blocked_result = QAAgent().run(blocked, {"status": "approved", "reviewer": "负责人", "approved_at": "2026-09-24T00:00:00Z"})
        self.assertEqual(blocked_result["status"], "blocked")

        review_result = QAAgent().run(ready_plan())
        self.assertEqual(review_result["status"], "review_required")

        approval = {"status": "approved", "reviewer": "负责人", "approved_at": "2026-09-24T00:00:00Z"}
        ready_result = QAAgent().run(ready_plan(), approval)
        self.assertEqual(ready_result["status"], "ready")

    def test_review_required_cannot_submit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "outputs").mkdir()
            (project / "outputs" / "qa.json").write_text(json.dumps({"status": "review_required"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "status='review_required'"):
                run_newapi(
                    project_dir=project,
                    prompt="测试提示词",
                    dry_run=False,
                    confirm_billing=True,
                )

    def test_ready_without_compiled_prompt_cannot_submit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "outputs").mkdir()
            (project / "outputs" / "qa.json").write_text(json.dumps({"status": "ready"}), encoding="utf-8")
            (project / "outputs" / "scope-approval.json").write_text(json.dumps({
                "status": "approved", "reviewer": "负责人", "approved_at": "2026-09-24T00:00:00Z"
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "已编译提示词"):
                run_newapi(
                    project_dir=project,
                    prompt="测试提示词",
                    dry_run=False,
                    confirm_billing=True,
                )

    def test_ready_reaches_mock_provider_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            (project / "outputs").mkdir()
            (project / "outputs" / "qa.json").write_text(json.dumps({"status": "ready"}), encoding="utf-8")
            (project / "outputs" / "scope-approval.json").write_text(json.dumps({
                "status": "approved", "reviewer": "负责人", "approved_at": "2026-09-24T00:00:00Z"
            }), encoding="utf-8")
            (project / "outputs" / "final_product_swap_prompt.md").write_text("测试提示词", encoding="utf-8")

            class FakeClient:
                def __init__(self) -> None:
                    self.config = SimpleNamespace(model="test-model")

                @staticmethod
                def build_payload(prompt: str, **kwargs: object) -> dict[str, object]:
                    return NewAPIVideoClient.build_payload(prompt, **kwargs)

                def create(self, payload: dict[str, object]) -> dict[str, str]:
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
                    prompt="测试提示词",
                    dry_run=False,
                    confirm_billing=True,
                    poll_interval=0.001,
                )
            self.assertEqual(result["status"], "completed")
            self.assertTrue(Path(result["output"]).is_file())


if __name__ == "__main__":
    unittest.main()
