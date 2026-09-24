# 中文团队角色

| 稳定 ID | 中文名 | 核心职责 |
| --- | --- | --- |
| `workflow_orchestrator` | 总导演 | 初始化、调度、状态与审批关卡 |
| `video_analyzer` | 视频拆解师 | 本地镜头证据、时长、音频和帧 |
| `shot_planner` | 复刻策划师 | 镜头计划、连续性和替换边界 |
| `keyframe_curator` | 关键帧拼图师 | 每秒抽帧、三帧拼图和全局编号 |
| `prompt_director` | 提示词导演 | 合并镜头、产品和负面约束 |
| `quality_reviewer` | 质量验收官 | 生成前门禁与成片视觉验收 |
| `provider_adapter` | 生成执行师 | Provider、dry-run、提交、轮询和下载 |
| `delivery_packager` | 交付打包师 | 成片、素材 ZIP、参数和中文教程 |

底层任务名、类名和文件名可以保持英文，用户界面、进度报告和交付报告使用中文名。

复刻策划师与关键帧拼图师可并行。质量验收官未批准前，生成执行师不得发起付费请求。
