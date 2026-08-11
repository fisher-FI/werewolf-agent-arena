# 实现架构总览

狼人杀 Agent 竞技场 —— 落地实现架构。设计依据见 [deep-dive-notes.md](deep-dive-notes.md)，设计文档见 [specs/2025-08-11-architecture-mermaid-design.md](superpowers/specs/2025-08-11-architecture-mermaid-design.md)。

```mermaid
flowchart TD
    %% ═══ 入口 CLI ═══
    RUN["<b>run.py</b><br/>CLI 入口：单局 · 跑批 · 观赛"]

    %% ═══ 编排层 ═══
    subgraph ORCH["orchestrator/ 对局编排"]
        ROOM["<b>room.py</b><br/>单局编排 · 广播 · 暂停/回放"]
        ARENA["<b>arena.py</b><br/>多局并发跑批 · 种子 · 续跑"]
    end

    %% ═══ 引擎层（纯逻辑） ═══
    subgraph ENG["engine/ 游戏引擎（零 AI 依赖，可单测）"]
        GE["<b>game_engine.py</b><br/>状态机 · 阶段流转 · 胜负判定"]
        RULES["<b>rules.py</b><br/>夜间结算 · 投票 · 屠边"]
        VIS["<b>visibility.py</b><br/>信息隔离双闸：写时路由 · 读时遮蔽"]
    end

    %% ═══ Agent 层 ═══
    subgraph AGT["agents/ + prompts/ 角色行为"]
        PA["<b>PlayerAgent</b><br/>基类：observe / act / 记忆"]
        WOLF["<b>wolf.py</b><br/>多狼夜聊协商"]
        MEM["<b>memory.py</b><br/>历史截断 · 摘要"]
        PROMPT["<b>templates.py</b><br/>槽位化 prompt · 6 策略"]
    end

    %% ═══ LLM 后端 ═══
    subgraph BKD["backends/ LLM 接入（可插拔）"]
        MB["<b>ModelBackend</b><br/>统一 query() 接口"]
        OC["<b>openai_compat.py</b><br/>DeepSeek · OpenAI · 通义 · 本地"]
        PARSER["<b>parser.py</b><br/>四级解析链 strict→repair→重prompt→兜底"]
        RETRY["<b>retry.py</b><br/>重试 · 超时 · 非法回退"]
    end

    %% ═══ 数据与展示 ═══
    subgraph DAT["storage/ + web/ 数据与展示"]
        ES["<b>event_store.py</b><br/>事件 + ground truth 落库"]
        STATS["<b>stats.py</b><br/>胜率 × 角色 × 模型"]
        API["<b>web/api.py</b><br/>REST + WebSocket 观战"]
    end

    %% ═══ 连线（三种颜色区分流向） ═══
    RUN --> ROOM
    RUN -. 并发 .-> ARENA
    ARENA --> ROOM
    ROOM --> GE
    GE --> RULES
    GE --> VIS
    ROOM --> PA
    PA --> WOLF
    PA --> MEM
    PA --> PROMPT
    PA --> MB
    MB --> OC
    MB --> PARSER
    MB --> RETRY
    GE --> ES
    ES --> STATS
    ES --> API

    %% 控制流 = 琥珀，数据流 = 青蓝，LLM 调用 = 绿
    linkStyle 0,2,3,4,5,6,7,8,9 stroke:#f5b84c,stroke-width:2px
    linkStyle 1,14,15,16 stroke:#4cc9f0,stroke-width:2px,stroke-dasharray:4 3
    linkStyle 10,11,12,13 stroke:#5eead4,stroke-width:2px
```

## 实现架构总览（渲染图）

![实现架构总览](architecture.svg)

## 图例

| 颜色 | 含义 | 示例 |
|---|---|---|
| 🟠 琥珀 | 控制流（调度 / 校验） | `room.py → game_engine.py` |
| 🔵 青蓝 | 数据流（状态 / 事件） | `game_engine.py → event_store.py` |
| 🟢 绿色 | LLM 调用 | `PlayerAgent → ModelBackend` |

## 关键设计决策

1. **引擎与 AI 解耦**：`engine/` 不依赖任何 LLM 代码，可独立单测、可复现（同 seed）。
2. **信息隔离双闸**：写时按角色路由投递，读时按可见性遮蔽 `[REDACTED]`，事件全量落库审计。
3. **四级解析链**：LLM 输出 strict JSON → 自动修复 → 重 prompt → 规则兜底，杜绝静默失败。
4. **可插拔后端**：所有模型走统一 `query()` 接口，`base_url` 切换 DeepSeek / OpenAI / 通义 / 本地。
