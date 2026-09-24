from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path

from .newapi_video import run_newapi
from .orchestrator import Orchestrator, load_evidence, load_plan
from .replication_prompt import compile_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="video-replicator", description="短视频复刻多智能体工作流 MVP")
    sub = parser.add_subparsers(dest="command", required=True)

    analyze = sub.add_parser("analyze", help="提取视频可观察证据")
    analyze.add_argument("video", type=Path)
    analyze.add_argument("--project", type=Path, default=Path("projects/demo"))

    plan = sub.add_parser("plan", help="根据 evidence 生成镜头/分段计划")
    plan.add_argument("evidence", type=Path)
    plan.add_argument("--project", type=Path, default=Path("projects/demo"))
    plan.add_argument("--segment-max", type=int, choices=(15, 30), required=True)
    plan.add_argument("--aspect-ratio", default="9:16")

    prompts = sub.add_parser("prompts", help="根据 plan 生成分段提示词")
    prompts.add_argument("plan", type=Path)
    prompts.add_argument("--project", type=Path, default=Path("projects/demo"))

    run = sub.add_parser("run", help="执行 analyze -> plan -> prompts -> qa")
    run.add_argument("video", type=Path)
    run.add_argument("--project", type=Path, default=Path("projects/demo"))
    run.add_argument("--segment-max", type=int, choices=(15, 30), required=True)
    run.add_argument("--aspect-ratio", default="9:16")

    team_run = sub.add_parser("team-run", help="由中文多智能体团队执行本地拆解、抽帧、规划、提示词和质检")
    team_run.add_argument("video", type=Path)
    team_run.add_argument("--project", type=Path, default=Path("projects/demo"))
    team_run.add_argument("--segment-max", type=int, choices=(15, 30), default=15)
    team_run.add_argument("--aspect-ratio", default="9:16")
    team_run.add_argument("--transcription-language", default=None, help="本地 Whisper 语言代码；不填则自动检测")
    team_run.add_argument("--transcription-model", default="small", help="本地 Whisper 模型，例如 tiny/base/small/medium/turbo")

    sync = sub.add_parser("sync", help="生成带分镜信息的复核视频")
    sync.add_argument("video", type=Path)
    sync.add_argument("--project", type=Path, default=Path("projects/demo"))
    sync.add_argument("--shots", type=Path)
    sync.add_argument("--chrome", type=Path)
    sync.add_argument("--timeout", type=int, default=120, help="video-sync 最长运行秒数")

    keyframes = sub.add_parser("keyframes", help="按时间顺序每 N 帧生成一张带编号的参考拼图")
    keyframes.add_argument("--project", type=Path, default=Path("projects/demo"))
    keyframes.add_argument("--evidence", type=Path, help="evidence.json；默认使用项目 analysis/evidence.json")
    keyframes.add_argument("--frames", type=Path, help="关键帧目录；默认使用项目 analysis/frames")
    keyframes.add_argument("--max-per-stage", type=int, default=9, help="每阶段最多选取的帧数（默认 9）")
    keyframes.add_argument("--video", type=Path, help="输入视频；默认使用项目 inputs/reference.mp4")
    keyframes.add_argument("--sample-interval", type=float, default=1.0, help="抽帧间隔秒数（默认 1 秒）")
    keyframes.add_argument("--frames-per-sheet", type=int, choices=(3, 6), default=3, help="每张拼图包含的连续帧数：3 或 6（默认 3）")

    deep = sub.add_parser("deep-analyze", help="生成逐时间片的深度视频拆解 JSON 和 Markdown")
    deep.add_argument("--project", type=Path, default=Path("projects/demo"))
    deep.add_argument("--evidence", type=Path, help="evidence.json；默认使用项目 analysis/evidence.json")
    deep.add_argument("--manifest", type=Path, help="关键帧 manifest；默认使用 outputs/reference_collages/manifest.json")
    deep.add_argument("--transcript", type=Path, help="可选 ASR JSON，支持 segments/items 数组")
    deep.add_argument("--ocr", type=Path, help="可选 OCR JSON，支持 segments/items 数组")
    deep.add_argument("--segment-seconds", type=float, default=1.0, help="时间片长度，默认 1 秒")

    transcribe = sub.add_parser("transcribe", help="本地提取音频并用 Whisper 生成带时间戳转写")
    transcribe.add_argument("video", type=Path)
    transcribe.add_argument("--project", type=Path, default=Path("projects/demo"))
    transcribe.add_argument("--language", default=None, help="语言代码，例如 zh、en；不填则自动检测")
    transcribe.add_argument("--model", default="small", help="Whisper 模型，例如 tiny/base/small/medium/turbo")

    gemini = sub.add_parser("gemini-review", help="上传参考视频到 Gemini，进行 Agentic 视觉和音频复核")
    gemini.add_argument("video", type=Path)
    gemini.add_argument("--project", type=Path, default=Path("projects/demo"))
    gemini.add_argument("--model", default="gemini-3.8-flash")

    timeline = sub.add_parser("script-timeline", help="从深度拆解生成可编辑文案和字幕时间轴")
    timeline.add_argument("--project", type=Path, default=Path("projects/demo"))
    timeline.add_argument("--deep-analysis", type=Path, help="deep-analysis.json；默认使用项目 analysis/deep-analysis.json")
    timeline.add_argument("--product-name", default="")
    timeline.add_argument("--voice-mode", choices=("original_audio", "new_tts", "new_human_voice"), default="new_tts")

    replication_prompt = sub.add_parser("replication-prompt", help="从逐镜复刻蓝图和改写时间轴编译生成提示词")
    replication_prompt.add_argument("--framework", type=Path, required=True, help="replication-framework.json")
    replication_prompt.add_argument("--timeline", type=Path, required=True, help="script-timeline.json")
    replication_prompt.add_argument("--output", type=Path, required=True, help="输出 UTF-8 提示词文件")
    replication_prompt.add_argument("--audio-mode", choices=("silent", "ambient", "music", "voiceover", "full"), default="voiceover")

    newapi = sub.add_parser("newapi", help="使用 New API 生成视频（默认仅 dry-run）")
    newapi.add_argument("--prompt", help="生成提示词")
    newapi.add_argument("--prompt-file", type=Path, help="从 UTF-8 文件读取提示词")
    newapi.add_argument("--project", type=Path, default=Path("projects/demo"))
    newapi.add_argument("--model", default=None, help="模型 ID，默认读取 NEW_API_MODEL（当前推荐 minimax-h3-f）")
    newapi.add_argument("--duration", type=int, default=10, choices=range(1, 16), metavar="1-15")
    newapi.add_argument("--ratio", default="9:16")
    newapi.add_argument("--resolution", default="768p")
    newapi.add_argument("--reference-image-url", action="append", default=[], help="公网参考图 URL，可重复")
    newapi.add_argument("--reference-video-url", action="append", default=[], help="公网参考视频 URL，可重复")
    newapi.add_argument("--generate-audio", action=argparse.BooleanOptionalAction, default=False, help="请求视频模型同步生成音频")
    newapi.add_argument("--submit", action="store_true", help="提交真实生成任务；需同时传 --confirm-billing")
    newapi.add_argument("--confirm-billing", action="store_true", help="确认第三方 API 可能产生费用")
    newapi.add_argument("--poll-interval", type=float, default=3.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    orchestrator = Orchestrator(args.project) if hasattr(args, "project") else None
    if args.command == "analyze":
        result = orchestrator.analyze(args.video)
    elif args.command == "plan":
        result = orchestrator.plan(load_evidence(args.evidence), args.segment_max, args.aspect_ratio)
    elif args.command == "prompts":
        result = orchestrator.prompts(load_plan(args.plan))
    elif args.command == "run":
        result = orchestrator.run(args.video, args.segment_max, args.aspect_ratio)
    elif args.command == "team-run":
        result = orchestrator.team_run(args.video, args.segment_max, args.aspect_ratio, args.transcription_language, args.transcription_model)
    elif args.command == "sync":
        result = orchestrator.sync(args.video, args.shots, args.chrome, args.timeout)
    elif args.command == "keyframes":
        result = orchestrator.keyframes(
            args.evidence, args.frames, args.max_per_stage, args.video, args.sample_interval, args.frames_per_sheet
        )
    elif args.command == "deep-analyze":
        result = orchestrator.deep_analyze(args.evidence, args.manifest, args.transcript, args.ocr, args.segment_seconds)
    elif args.command == "transcribe":
        result = orchestrator.transcribe(args.video, args.language, args.model)
    elif args.command == "gemini-review":
        result = orchestrator.gemini_review(args.video, args.model)
    elif args.command == "script-timeline":
        result = orchestrator.script_timeline(args.deep_analysis, args.product_name, args.voice_mode)
    elif args.command == "replication-prompt":
        prompt = compile_files(args.framework, args.timeline, args.output, audio_mode=args.audio_mode)
        result = {"status": "compiled", "output": str(args.output), "characters": len(prompt), "audio_mode": args.audio_mode}
    else:
        if args.prompt and args.prompt_file:
            raise SystemExit("--prompt 与 --prompt-file 只能二选一")
        prompt = args.prompt
        if args.prompt_file:
            prompt = args.prompt_file.read_text(encoding="utf-8")
        if not prompt:
            raise SystemExit("newapi 需要 --prompt 或 --prompt-file")
        result = run_newapi(
            project_dir=args.project,
            prompt=prompt,
            model=args.model,
            duration=args.duration,
            ratio=args.ratio,
            resolution=args.resolution,
            reference_images=args.reference_image_url,
            reference_videos=args.reference_video_url,
            generate_audio=args.generate_audio,
            dry_run=not args.submit,
            confirm_billing=args.confirm_billing,
            poll_interval=args.poll_interval,
        )
    payload = result if isinstance(result, dict) else asdict(result) if is_dataclass(result) else result
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
