# 🐺 AI 狼人杀

LLM 驱动的 Web 版狼人杀游戏。9 个 AI 玩家自主对局，人类作为上帝视角观战，可以随时暂停、继续，查看每位 AI 的实时推理过程。

## ✨ 特性

- **全自动 AI 对局** — 9 个 AI 玩家由 LLM 驱动，自主发言、投票、使用技能
- **上帝视角** — 人类观战者可以看到所有人的身份、推理过程和博弈策略
- **实时推理展示** — 中央面板展示每位 AI 的推理过程（预知家验人逻辑、狼人刀人策略等）
- **暂停 / 继续** — 随时暂停游戏，观察当前局势；离开页面自动暂停，返回后历史回放
- **断线重连** — WebSocket 自动重连，完整回放所有已发生的游戏事件
- **当前发言高亮** — 紫色呼吸灯边框标识正在发言的玩家
- **Linear 设计风格** — 深色主题、Inter 字体、8px 栅格系统

## 🎮 游戏规则

| 阵营 | 角色 | 人数 | 技能 |
|------|------|------|------|
| 🐺 狼人阵营 | 狼人 | 3 | 夜间集体选择击杀一名玩家 |
| 👼 好人阵营 | 预言家 | 1 | 夜间查验一名玩家的身份（狼/好人） |
| 👼 好人阵营 | 女巫 | 1 | 拥有一瓶解药（救人）和一瓶毒药（毒杀），各限用一次 |
| 👼 好人阵营 | 猎人 | 1 | 被投票出局时可带走一名玩家 |
| 👼 好人阵营 | 平民 | 4 | 无特殊技能，靠推理投票 |

**胜利条件：**
- 🐺 狼人阵营：场上狼人数 ≥ 好人数
- 👼 好人阵营：所有狼人出局

## 🏗️ 技术架构

```
┌──────────────┐    WebSocket    ┌──────────────────┐    HTTP    ┌──────────┐
│  React 前端   │◄──────────────►│   FastAPI 后端    │──────────►│  MiMo LLM │
│  (Vite + TS)  │    REST API    │   (Python 3.9+)  │  OpenAI   │  (小米)    │
└──────────────┘                 └──────────────────┘  兼容 API  └──────────┘
```

**后端：**
- `backend/main.py` — FastAPI 入口，REST API + WebSocket + 静态文件服务
- `backend/ai/adapter.py` — LLM API 适配器（OpenAI 兼容格式，支持 `response_format: json_object`）
- `backend/ai/orchestrator.py` — 游戏流程控制（白天讨论、投票、夜间行动）
- `backend/engine/models.py` — 数据模型（玩家、角色、配置）
- `backend/engine/game.py` — 游戏逻辑（胜利判定、状态更新）

**前端：**
- `frontend/src/pages/Lobby.tsx` — 大厅页面，创建/加入房间
- `frontend/src/pages/Room.tsx` — 游戏主界面（座位 + 时间线 + AI 推理）
- `frontend/src/pages/Settings.tsx` — LLM 配置页面
- `frontend/src/services/api.ts` — API 客户端

## 🚀 快速开始

### 前置要求

- **Python 3.9+**
- **Node.js 18+**
- **Xiaomi MiMo API Key**（或其他 OpenAI 兼容的 LLM API）

### 1. 克隆仓库

```bash
git clone https://github.com/chzisnull/werewolf-ai.git
cd werewolf-ai
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 API Key：

```env
XIAOMI_API_KEY=your-api-key-here
XIAOMI_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
```

> **使用其他 LLM？** 只要是 OpenAI 兼容 API，修改 `XIAOMI_BASE_URL` 即可。例如 OpenRouter、DeepSeek 等。

### 3. 一键启动

```bash
bash start.sh
```

启动脚本会自动：
1. 加载 `.env` 环境变量
2. 安装 Python 依赖
3. 构建前端（首次）
4. 启动服务 → `http://localhost:8822`

### 手动启动

如果需要分别启动：

```bash
# 安装后端依赖
cd backend
pip install -r requirements.txt

# 构建前端
cd ../frontend
npm install
npm run build

# 启动后端（会同时提供前端静态文件服务）
cd ../backend
python -m uvicorn main:app --host 0.0.0.0 --port 8822 --reload
```

### 前端开发模式

```bash
cd frontend
npm install
npm run dev
```

Vite 开发服务器默认在 `http://localhost:5173`，会代理 API 请求到后端。

## 📖 使用指南

### 创建游戏

1. 打开 `http://localhost:8822`
2. 在设置页面配置 LLM 参数（默认已填好 MiMo）
3. 点击「创建房间」→ AI 玩家自动就位
4. 点击「开始游戏」

### 观战模式

- **左侧**：1-5 号玩家座位（身份、阵营、存活状态）
- **右侧**：6-9 号玩家座位
- **中间**：游戏时间线 / AI 推理（可切换标签页）
- **顶部**：当前轮次、阶段、暂停/继续按钮

### 暂停机制

- 点击顶部「暂停」按钮手动暂停
- 关闭浏览器标签页自动暂停
- 重新打开页面自动回放历史 + 继续游戏

## 🔧 配置说明

在游戏内的设置页面可以调整：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| API Base URL | LLM 服务地址 | `https://token-plan-cn.xiaomimimo.com/v1` |
| API Key | 认证密钥 | 从 `.env` 读取 |
| Model | 模型名称 | `mimo-v2.5-pro` |
| Temperature | 创造性（0-1） | `0.7` |
| Max Tokens | 最大输出长度 | `2048` |

## 📁 项目结构

```
werewolf-ai/
├── start.sh                 # 一键启动脚本
├── .env                     # 环境变量（不提交）
├── .env.example             # 环境变量模板
├── .gitignore
├── README.md
│
├── backend/
│   ├── main.py              # FastAPI 入口
│   ├── requirements.txt     # Python 依赖
│   ├── ai/
│   │   ├── adapter.py       # LLM API 适配器
│   │   └── orchestrator.py  # 游戏流程编排
│   ├── engine/
│   │   ├── models.py        # 数据模型
│   │   └── game.py          # 游戏逻辑
│   └── static/              # 前端构建产物
│
└── frontend/
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── App.tsx
        ├── main.tsx
        ├── services/api.ts
        └── pages/
            ├── Lobby.tsx     # 大厅
            ├── Lobby.css
            ├── Room.tsx      # 游戏房间
            ├── Room.css
            ├── Settings.tsx  # 设置
            └── Settings.css
```

## 🤝 贡献

欢迎提交 Issue 和 PR！

## 📄 License

MIT
