# ADR-0001：Phase 0 工程与领域边界

状态：已接受
日期：2026-07-27

## 决策

AstraQuant 使用 Python 3.12 和 uv 建立 Monorepo。首个可执行包
`astraquant-domain` 不依赖 UI、HTTP、数据库或第三方量化框架。

领域包只包含标的标识、订单契约、订单状态、时钟和版本化事件。
vn.py、Qlib、Tauri、FastAPI、DuckDB 和 SQLite 均在后续适配层使用。

## 原因

- Python 3.12 兼容量化与数据生态，避免以本机 Python 3.14 作为隐式基线。
- 无框架领域包可以被回测、Paper、Live 和测试共同复用。
- Windows/Linux CI 尽早发现路径、编码和行尾差异。
- 仓库策略检查防止私人行情、密钥和运行数据库进入 Git。

## 结果

后续模块必须依赖公开领域契约，不能把第三方项目对象直接暴露给 UI
或跨进程接口。领域契约发生不兼容变化时必须显式升级版本。
