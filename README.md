# Werewolf Agent Arena（狼人杀 Agent 竞技场）

让 AI Agent 自己玩狼人杀（Werewolf / Mafia）的竞技场平台。

## 愿景

- 多个 LLM Agent 扮演不同角色（狼人、预言家、女巫、猎人、平民…），自动进行完整对局
- 支持观赛模式：实时围观发言、投票、夜晚行动
- 记录对局日志、统计各 Agent/策略的胜率，用于评测谁更会玩狼人杀
- 设计上预留真实 LLM API 接入（DeepSeek / OpenAI / 通义等），也支持纯规则模拟打底

## 快速开始

### 1. 配置 LLM（OpenAI 兼容）

```bash
cp .env.example .env   # 填入你的 API key / base_url
```

本项目默认对接 `opencode-go` 网关（与 pi 同源，支持 deepseek-v4-flash / glm-5.2 / kimi 等 25+ 模型）：

```env
XIAOMI_API_KEY=sk-xxx
XIAOMI_BASE_URL=https://opencode.ai/zen/go/v1
XIAOMI_MODEL=deepseek-v4-flash
```

任何 OpenAI 兼容 API（DeepSeek / OpenAI / 通义 / 本地 Ollama）都可以，改 `.env` 即可。

### 2. 启动

```bash
bash start.sh          # 自动装依赖 + 构建前端 + 启动 http://localhost:8822
```

## 玩法

1. 大厅选择板子（预女猎守 / 预女猎白 / 狼王守卫 / 白狼王骑士 / 丘比特）
2. 创建房间 → 一键填充 12 个 AI 玩家 → 开始游戏
3. 上帝视角观战：发言 / 投票 / 思维链 / 夜间行动全可见，可暂停

## 技术架构

见 [docs/architecture.md](docs/architecture.md)（Mermaid + draw.io 图）。

- **引擎**：显式状态机（非法转移抛错）、死亡结算链（同守同救/殉情/开枪/翻牌）、声明式判胜（情侣>狼>好人）
- **板子**：`backend/engine/boards.py`，人数由角色池推导，零硬编码
- **信息隔离**：事件 `visible_to` 控制可见性，狼人/情侣/预言家各看各的
- **AI 适配**：统一 `query()` 接口 + 四级解析 + 指数退避重试，女巫/丘比特结构化输出

## 目录结构

```
werewolf-agent-arena/
├── README.md                        # 本文件
└── docs/
    └── open-source-references.md    # 开源项目调研
```
