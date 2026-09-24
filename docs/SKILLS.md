# Skill 与外部能力清单

本项目把可复用的流程、代码和配置放在仓库内；第三方 skill 与服务只记录用途和安装来源，不复制其私有实现、用户凭据或客户素材。

## 已随仓库分发

| Skill/模块 | 用途 | 位置 |
| --- | --- | --- |
| `short-video-product-swap-team` | 中文多智能体短视频拆解、对象替换、关键帧拼图、提示词、QA 和交付 | `skills/short-video-product-swap-team/` |
| `video_replicator` | 本地分析、抽帧、深度拆解、转写、时间轴、提示词编译和 New API 调用 | `video_replicator/` |
| New API provider | 连接兼容的视频生成 API，支持 dry-run、提交、轮询、脱敏记录 | `packages/provider-newapi-video/` |
| 项目脚本 | 初始化、诊断、团队运行、Hypit 检查、素材包导出 | `scripts/` |

## 使用过/可选的第三方能力

| 能力 | 用途 | 安装/配置 |
| --- | --- | --- |
| `typesafe-ai` | typed AI 判断、结构化评估和未来的多维文档/视频判断 | 通过 `npx skills add typesafe-ai/skills --skill typesafe-ai` 安装；本机副本位于 `.agents/skills/typesafe-ai/`，不把供应商密钥提交到仓库 |
| ReelBench `video-shots` / `video-sync` | 视觉镜头取证、复核视频 | 按 ReelBench skill 的原始仓库说明安装；本项目通过本地命令调用，不上传原视频 |
| Hypit | provider doctor、check、plan、pricing 和可选工作流运行 | `npm install` 后使用 `hypit.runtime.example.json`；运行时凭据放环境变量 |
| Whisper / `openai-whisper` | 本地音频转写与时间戳对白 | 安装本地 Whisper 或使用团队已有环境；没有 ASR 时必须标记待转写，不猜对白 |
| Gemini Agentic Video | 用户明确允许上传参考视频时做视觉/音频复核 | 单独配置 `GEMINI_API_KEY`；默认关闭，不是生成链路的必需依赖 |
| GPT Image / 图像编辑模型 | 以单张帧为底图替换产品、人物或场景；拼图只做上下文 | 使用目标平台自己的 skill/API；产品参考图和编辑产物留在本地或经授权的公网存储 |
| Seedance / Minimax 等视频模型 | 根据逐镜框架、关键帧拼图和对象参考图生成视频 | 通过本地 New API provider 或其他兼容平台配置；生成前必须计价和审批 |

## 原则

- 第三方 skill 需遵守其原始许可证与使用条款。
- API key、OAuth token、signed URL、客户素材和生成结果不属于 skill，不得提交。
- 同事只需要本仓库 + 自己安装的第三方 skill + 自己的授权配置即可复现流程。
