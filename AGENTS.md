# AstraQuant 项目指令（AGENTS.md）

## 语言

默认使用中文（简体）回答，代码、命令、API 名称等保持原文。

## 最高原则（违反即视为错误）

**永远不追求速度，永远不做临时解决，要做就做到最优方案。**
完整定义见 `docs/governance/engineering-principles.md`，开始任何开发前必须阅读。

要点：
- 先设计（含出处）→ 用户确认 → 实施；禁止"先跑通再改"。
- 量化模型以开源成熟实现为基础（Qlib 模型 zoo、预训练时序模型、FinRL），不自研低质算法。
- 任何方案必须有论文/官方文档/源码出处，禁止拍脑袋。
- 费用跟随用户配置（FeeSchedule 单一来源），绝不写死。
- 训练/推理特征一致性、防泄漏是底线。

## 开发位置

- 实际开发工作树：`D:\AstraQuant\.worktrees\phase-1-desktop-platform`（分支 `feature/phase-1-desktop-platform`）
- 主仓库根：`D:\AstraQuant`（main，勿直接改动）
- 本地数据/研究产物在 `.astraquant/`（git 忽略），设计文档在 `docs/`

## 验证命令（每次改动后必须全量跑）

```powershell
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy          # 不带参数，与 CI 一致
```

## 禁止事项

- 不要丢弃未提交改动；不要 `git reset --hard` / `git checkout -- .`。
- 不提交密钥/私人持仓数据；不引入假行情、假 AI 情报、假收益。
- 策略必须是注册、版本化、通过发布门槛的；禁止临时写死策略逻辑。
