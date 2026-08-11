# 架构总览图（Mermaid）设计文档

日期：2025-08-11 · 状态：已批准（用户确认）

## 目标

为狼人杀 Agent 竞技场绘制一张 Mermaid 模块依赖总览图，表达**落地实现架构**（非概念蓝图）：模块划分、调用关系、控制流/数据流/LLM 调用的区分。

## 交付物

- 单文件 `docs/architecture.md`，含一张 `flowchart TD` 图
- README 增加一行链接指向该文档
- 用 mermaid-cli 本地渲染 PNG 验证语法与布局

## 图设计

- **四个 subgraph 分组**：`engine/`（纯逻辑核心）、`agents/+prompts/`（角色行为）、`backends/`（LLM 接入）、`storage/+web/`（数据与展示）
- **节点**：约 12 个模块方块，标注文件名与职责
- **入口**：顶部 `run.py`（单局/跑批/观赛）→ Orchestrator，整体自上而下
- **连线三色**（linkStyle）：
  - 琥珀 `#f5b84c` = 控制流（调度/校验）
  - 青蓝 `#4cc9f0` = 数据流（状态/事件）
  - 绿色 `#5eead4` = LLM 调用

## 节点清单

| 分组 | 节点 |
|---|---|
| CLI | run.py |
| orchestrator/ | room.py（单局编排）、arena.py（并发跑批） |
| engine/ | game_engine.py（状态机）、rules.py（结算）、visibility.py（隔离双闸） |
| agents/+prompts/ | PlayerAgent（基类）、wolf.py（多狼协商）、memory.py、templates.py（槽位模板） |
| backends/ | ModelBackend（query()）、openai_compat.py、parser.py（四级解析）、retry.py |
| storage/+web/ | event_store.py、stats.py、web/api.py（REST+WS） |

## 验证标准

1. mmdc 渲染 PNG 成功、无语法错误
2. 图内容与 `docs/deep-dive-notes.md` 总结表一致（引擎解耦、隔离双闸、四级解析、可插拔后端）
