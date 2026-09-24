from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from video_replicator.agents import KeyframeCurationAgent
from video_replicator.schemas import VideoEvidence


class KeyframeCurationAgentTests(unittest.TestCase):
    def test_sample_timestamps_include_a_safe_end_frame(self) -> None:
        timestamps = KeyframeCurationAgent._sample_timestamps(11.749, 1.0)

        self.assertEqual(timestamps[:12], [float(index) for index in range(12)])
        self.assertAlmostEqual(timestamps[-1], 11.699, places=3)
        self.assertLess(max(timestamps), 11.749)

    def test_builds_three_temporal_collages_and_manifest_data(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frames_dir = root / "frames"
            output_dir = root / "outputs"
            frames_dir.mkdir()
            evidence_frames = []
            for index in range(12):
                path = frames_dir / f"frame-{index:02d}.jpg"
                Image.new("RGB", (90, 160), (index * 10, 30, 60)).save(path)
                evidence_frames.append({"path": str(path), "timestamp": float(index)})

            evidence = VideoEvidence(
                source="reference.mp4",
                metadata={"duration": 12},
                frames=evidence_frames,
            )
            result = KeyframeCurationAgent().run(evidence, frames_dir, output_dir, max_per_stage=3)

            self.assertEqual(result["status"], "ok")
            self.assertEqual([stage["selected_count"] for stage in result["stages"]], [3, 3, 3])
            self.assertEqual(result["layout"]["columns"], 3)
            for stage in result["stages"]:
                self.assertTrue(Path(stage["output"]).is_file())

    def test_borrows_nearest_frame_when_a_stage_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frames_dir = root / "frames"
            output_dir = root / "outputs"
            frames_dir.mkdir()
            first = frames_dir / "first.jpg"
            last = frames_dir / "last.jpg"
            Image.new("RGB", (90, 160), "red").save(first)
            Image.new("RGB", (90, 160), "blue").save(last)
            evidence = VideoEvidence(
                source="reference.mp4",
                metadata={"duration": 12},
                frames=[
                    {"path": str(first), "timestamp": 0},
                    {"path": str(last), "timestamp": 12},
                ],
            )

            result = KeyframeCurationAgent().run(evidence, frames_dir, output_dir)

            self.assertTrue(result["stages"][1]["frames"][0]["borrowed"])
            self.assertTrue(any("middle" in warning for warning in result["warnings"]))
            (output_dir / "manifest.json").write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )

    def test_builds_six_frame_sheets_with_global_numbering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frames_dir = root / "frames"
            output_dir = root / "outputs"
            frames_dir.mkdir()
            evidence_frames = []
            for index in range(13):
                path = frames_dir / f"frame-{index:02d}.jpg"
                Image.new("RGB", (90, 160), (index * 10 % 255, 30, 60)).save(path)
                evidence_frames.append({"path": str(path), "timestamp": float(index)})
            evidence = VideoEvidence(source="reference.mp4", metadata={"duration": 13}, frames=evidence_frames)
            result = KeyframeCurationAgent().run(evidence, frames_dir, output_dir, frames_per_sheet=6)
            self.assertEqual(result["layout"]["frames_per_shot_sheet"], 6)
            self.assertEqual(len(result["shot_sheets"]), 3)
            self.assertEqual([f["shot_number"] for f in result["shot_sheets"][1]["frames"]], [7, 8, 9, 10, 11, 12])


if __name__ == "__main__":
    unittest.main()
