from __future__ import annotations

import unittest

from video_replicator.replication_prompt import compile_prompt, validate_framework


class ReplicationPromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.framework = {
            "duration_seconds": 4,
            "aspect_ratio": "9:16",
            "replacement": {"product_name": "新产品", "product_appearance": "以产品图为准"},
            "shots": [
                {
                    "id": "S01",
                    "start": 0,
                    "end": 2,
                    "shot_function": "产品出场",
                    "shot_size": "中景",
                    "angle_composition": "正面构图",
                    "scene_action": "原场景，手拿起产品",
                    "lighting": "柔和光",
                    "expression_emotion": "不露脸，手势自然",
                    "realism_texture": "接触真实",
                    "audio": {"original_dialogue": "原句（不能泄漏）"},
                    "camera_focus": {"movement": "固定机位", "focus": "主体清晰"},
                    "product_state": {"position": "中央", "quantity": "一瓶", "orientation": "正面", "interaction": "手持"},
                    "continuity": {"start": "桌面", "end": "手持"},
                    "confidence": 0.9,
                    "uncertain_items": [],
                },
                {
                    "id": "S02",
                    "start": 2,
                    "end": 4,
                    "shot_function": "细节展示",
                    "shot_size": "近景",
                    "angle_composition": "正面构图",
                    "scene_action": "第二原场景，手指向标签",
                    "lighting": "柔和光",
                    "expression_emotion": "不露脸，手势自然",
                    "realism_texture": "接触真实",
                    "audio": {"original_dialogue": "原句（不能泄漏）"},
                    "camera_focus": {"movement": "硬切后固定", "focus": "主体清晰"},
                    "product_state": {"position": "中央", "quantity": "一瓶", "orientation": "正面", "interaction": "指示"},
                    "continuity": {"start": "桌面", "end": "正面朝向镜头"},
                    "confidence": 0.9,
                    "uncertain_items": [],
                },
            ],
        }
        self.timeline = {
            "product_name": "新产品",
            "segments": [
                {"id": "T01", "start": 0, "end": 2, "adapted_dialogue": "改写后的开场"},
                {"id": "T02", "start": 2, "end": 4, "adapted_dialogue": "改写后的收尾"},
            ],
        }

    def test_prompt_keeps_shot_skeleton_and_uses_rewritten_copy(self) -> None:
        prompt = compile_prompt(self.framework, self.timeline, audio_mode="voiceover")

        self.assertIn("S01（源镜头 未标注）｜0.00-2.00s", prompt)
        self.assertIn("原场景，手拿起产品", prompt)
        self.assertIn("S02（源镜头 未标注）｜2.00-4.00s", prompt)
        self.assertIn("改写后的开场", prompt)
        self.assertIn("改写后的收尾", prompt)
        self.assertNotIn("不能泄漏", prompt)
        self.assertIn("不得重新编排", prompt)
        self.assertIn("同步生成清晰自然的普通话口播", prompt)

    def test_unreviewed_placeholders_block_prompt_generation(self) -> None:
        self.framework["shots"][0]["scene_action"] = "待视觉分析"

        with self.assertRaisesRegex(ValueError, "占位"):
            validate_framework(self.framework, self.timeline)

    def test_nested_unreviewed_placeholders_block_prompt_generation(self) -> None:
        self.framework["shots"][0]["audio"]["sound_effects"] = "待音频分析"

        with self.assertRaisesRegex(ValueError, "占位"):
            validate_framework(self.framework, self.timeline)

    def test_overlapping_or_out_of_range_shots_are_rejected(self) -> None:
        self.framework["shots"][1]["start"] = 1.5

        with self.assertRaisesRegex(ValueError, "时间无效"):
            validate_framework(self.framework, self.timeline)

    def test_uncovered_time_between_shots_is_rejected(self) -> None:
        self.framework["shots"][1]["start"] = 2.2

        with self.assertRaisesRegex(ValueError, "未覆盖"):
            validate_framework(self.framework, self.timeline)

    def test_silent_mode_does_not_include_voiceover_copy(self) -> None:
        prompt = compile_prompt(self.framework, self.timeline, audio_mode="silent")

        self.assertIn("输出静音视频", prompt)
        self.assertNotIn("改写后的开场", prompt)


if __name__ == "__main__":
    unittest.main()
