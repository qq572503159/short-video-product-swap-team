# 发给同事 Codex 的接手说明

将 `short-video-product-swap-team.zip` 上传或提供给 Codex，然后发送下面这段话：

```text
请解压并检查这个短视频产品替换工具包。先阅读 README.md、docs/OPERATIONS.md、docs/多智能体团队说明.md，以及 skills/short-video-product-swap-team/SKILL.md。

请按以下顺序执行：
1. 不读取、显示或写入任何真实 API key。
2. 运行 scripts/init-workspace.ps1 完成依赖检查和 Provider 构建；如果默认 python 低于 3.10，优先使用 py -3.12。
3. 运行 scripts/diagnose-workspace.ps1 -SkipNetwork 做无付费诊断。
4. 使用 scripts/install-team-skill.ps1 -Force 安装中文团队 Skill。
5. 告诉我还需要提供哪些文件。正常需要：参考视频、产品正反面图、产品多角度图、产品名称和产品描述。
6. 收到素材后，用 scripts/init-video-project.ps1 创建新项目。
7. 用 scripts/run-video-team.ps1 执行本地拆解、每秒抽帧、三帧拼图、提示词、质检、手动生成包和 Hypit 只读预检。
8. 在我明确确认模型、素材、时长、分辨率和费用之前，不得提交任何付费视频生成任务。
9. 最终同时提供：直接生成成片路线，以及可在其他平台使用的 ZIP 素材包和中文教程。

所有面向我的角色名和进度请使用中文。原始参考视频默认只在本地处理，不上传第三方生成平台。
```

## 同事需要准备的素材

- 参考短视频文件。
- 产品正反面图。
- 产品多角度图。
- 产品名称。
- 产品外观、容量、标签文字等必须准确的信息。
- 是否允许使用原音轨，以及最终是否必须无字幕。

## 费用规则

Codex 可以直接运行分析、抽帧、拼图、提示词、测试、诊断、dry-run、Hypit `check/plan/pricing` 和手动素材包导出。真实 API 生成必须在负责人明确确认费用后执行。
