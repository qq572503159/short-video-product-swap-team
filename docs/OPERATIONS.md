# 运维与同事交付

本文面向需要在 Windows 上接手短视频复刻项目的同事。所有命令默认从仓库根目录执行：

```powershell
Set-Location "<你解压或克隆后的仓库路径>"
```

## 运行前提

- Node.js 与 npm，用于 Hypit 和本地 New API provider。
- Python 3.10 或更高版本，用于 `video_replicator` CLI。
- `ffmpeg`，用于抽帧、音频提取和手动生成包；Chrome 仅在运行 `video-sync` 时需要。
- 一个已授权的 New API token。token 只放在本机用户目录，不放进仓库、运行时 JSON 或日志。

## 一键初始化

先运行只检查并构建的初始化脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\init-workspace.ps1
```

需要自动安装 npm 依赖时显式加开关；需要安装本地 Python 包时再加 `-InstallPython`：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\init-workspace.ps1 `
  -InstallNodeDependencies -InstallPython
```

脚本会检查 `node`、`npm`、`python`、`ffmpeg`，构建
`packages/provider-newapi-video`，并在缺失时创建一个空的环境变量模板。它不会覆盖已有配置，也不会输出 token。

## 密钥配置

配置文件路径：

```text
$HOME\.codex\secrets\newapi.env
```

文件内容只需要按下面的格式填写，`NEW_API_TOKEN` 的真实值在本机手动填写：

```env
NEW_API_URL=https://newapi.megabyai.cc
NEW_API_TOKEN=
NEW_API_MODEL=minimax-h3-f
```

如果 `python` 命令仍指向 3.9，但系统有 Python 3.12，可用 Python Launcher 明确指定解释器：

```powershell
py -3.12 -m pip install -e .
py -3.12 -m video_replicator.cli newapi `
  --prompt-file .\projects\demo-9-16\outputs\final_product_swap_prompt.md `
  --project .\projects\demo-9-16 `
  --model minimax-h3-f
```

初始化脚本会拒绝低于 3.10 的 `python`，以免依赖安装到了不兼容的解释器中。

当前聊天或日志中曾经暴露过的 token 应立即在第三方后台撤销并轮换；不要继续使用已暴露值。不要把 token 放进以下文件：

- `hypit.runtime.json`
- `request*.json`、`create_response.json`、日志和截图
- README、脚本参数、Git 提交或工单

## 本地多智能体流程

以下命令只做本地拆解、抽帧、规划、提示词、质检和手动素材包导出，不提交视频生成任务：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-video-team.ps1 `
  -Project projects/demo-9-16
```

手动生成包也可以单独导出：

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\export-manual-generation-package.ps1 `
  -Project projects/demo-9-16
```

输出在 `projects/demo-9-16/outputs/`，其中 `manual-generation-package.zip` 可交给其他平台操作员。

## New API 直连生成：`minimax-h3-f`

Python 直连链路使用 New API 的 `/v1/videos` 和 `/v1/videos/{task_id}`。默认是 dry-run，只写入脱敏请求，不会产生费用：

```powershell
python -m video_replicator.cli newapi `
  --prompt-file .\projects\demo-9-16\outputs\final_product_swap_prompt.md `
  --project .\projects\demo-9-16 `
  --model minimax-h3-f `
  --duration 10 `
  --ratio 9:16 `
  --resolution 768p
```

参考图和参考视频必须是公网可访问的 `http(s)` URL；本地路径不会被 API 接受。确认人物保留、产品替换、时长、画幅和预算后，才显式提交：

```powershell
python -m video_replicator.cli newapi `
  --prompt-file .\projects\demo-9-16\outputs\final_product_swap_prompt.md `
  --reference-image-url https://example.invalid/product-front-back.png `
  --project .\projects\demo-9-16 `
  --model minimax-h3-f `
  --duration 10 `
  --ratio 9:16 `
  --resolution 768p `
  --submit `
  --confirm-billing
```

`--submit --confirm-billing` 会发起真实任务并可能产生费用。生成文件和脱敏记录写入 `projects/<name>/outputs/newapi/`。

## Hypit 命令与模型边界

Hypit 可用于检查、计划和费用预览：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\hypit-newapi.ps1 doctor --json
powershell -ExecutionPolicy Bypass -File .\scripts\hypit-newapi.ps1 check .\projects\demo-9-16\hypit\product-swap.svml --json
powershell -ExecutionPolicy Bypass -File .\scripts\hypit-newapi.ps1 plan .\projects\demo-9-16\hypit\product-swap.svrun --json
powershell -ExecutionPolicy Bypass -File .\scripts\hypit-newapi.ps1 pricing .\projects\demo-9-16\hypit\product-swap.svrun --json
```

当前 `hypit.runtime.json` 的绑定仍是 `@hypit/seedance@1#seedance-2-mini`，其 wire model 是 `seedance-2.0-mini`。它与 Python 直连的 `minimax-h3-f` 是两条不同链路；不要只修改显示名称来混用模型。当前 Hypit provider 明确不支持 `generateAudio=true`，只能走静音/后期音频路线；需要视频模型原生音频时使用 Python New API 路线，并通过 QA 和费用门禁。真正切换 Hypit 模型前，需要同步更新 capability、provider 契约和运行时配置，并重新做费用与响应格式验证。

## 诊断

诊断脚本不会调用 `POST /v1/videos`，默认只检查本地依赖、关键文件、Hypit 只读命令和文档站点可达性：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\diagnose-workspace.ps1
```

离线环境可跳过网络检查：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\diagnose-workspace.ps1 -SkipNetwork
```

输出只报告配置是否存在，不显示任何 token 内容。若诊断提示环境文件存在但 token 未配置，请在本机编辑该文件后重新执行诊断。

## 常见排查顺序

1. 运行 `init-workspace.ps1`，确认 Node、Python 和 provider 构建均通过。
2. 运行 `diagnose-workspace.ps1 -SkipNetwork`，排除本机依赖问题。
3. 用 `npx hypit doctor`、`check`、`plan` 做 Hypit 只读检查。
4. 用 Python `newapi` 命令做 dry-run，检查 `request.redacted.json` 中的模型、时长、画幅和参考 URL。
5. 只有在预算和输入素材人工确认后，才使用 `--submit --confirm-billing`。
