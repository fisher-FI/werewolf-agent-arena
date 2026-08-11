# 开源项目调研：狼人杀 Agent

调研时间：2025-08-11，数据来自 GitHub 搜索。

## 最相关的项目

| 项目 | Stars | 语言 | 说明 |
|---|---|---|---|
| [muranUSTB/werewolf_kills_agentscope](https://github.com/muranUSTB/werewolf_kills_agentscope) | 26 | Python | 基于 AgentScope 框架搭建的 AI 狼人杀，最接近我们目标的参考 |
| [junjiem/werewolf-agent](https://github.com/junjiem/werewolf-agent) | 17 | Java | 基于 LLM 的狼人杀 Agent，「玩具」级实现 |
| [WuJunde/werewolf_ai_agents](https://github.com/WuJunde/werewolf_ai_agents) | 7 | Python | autonomous & interactive AI agents 玩狼人杀，基于 MetaGPT，工程化较完整（有 Dockerfile、CI、tests） |
| [Guoen0/werewolf_agents_arena](https://github.com/Guoen0/werewolf_agents_arena) | 5 | Python | 名字与我们的项目几乎相同；结构简单：`Player.py` / `Room.py` / `prompts.py` / `run.py` / `stati.py`，适合作为极简参考 |
| [papakuma213/Multi-Agents-WereWolf](https://github.com/papakuma213/Multi-Agents-WereWolf) | 5 | - | 多 Agent 狼人杀 |
| [Gitsamshi/open_werewolf](https://github.com/Gitsamshi/open_werewolf) | 2 | - | 狼人杀 LLM agent 游戏 |
| [chzisnull/werewolf-ai](https://github.com/chzisnull/werewolf-ai) | 1 | - | LLM 驱动的 Web 版狼人杀，上帝视角观战（与我们想要的观赛模式接近） |
| [Muqian-Sun/ai-werewolf-agent-teams](https://github.com/Muqian-Sun/ai-werewolf-agent-teams) | 2 | - | 字节跳动 AI 狼人杀 Agent Teams：评测 + 复盘平台，9 人板真实 LLM 对局引擎 + 信息隔离 + Trace + 能力排行榜（与我们的竞技场愿景高度重合） |

## 非 LLM / 其他方向的参考

| 项目 | Stars | 说明 |
|---|---|---|
| [KylJin/Werewolf](https://github.com/KylJin/Werewolf) | 12 | One Night Ultimate Werewolf（一夜狼人）环境 + RL 训练的 LLM agent 框架 |
| [HMJiangGatech/GPT4-werewolf](https://github.com/HMJiangGatech/GPT4-werewolf) | 11 | GPT4 一夜狼人 |
| [TylerYep/wolfbot](https://github.com/TylerYep/wolfbot) | 10 | One Night Ultimate Werewolf: AI Edition |

## 结论与建议

1. **最值得参考**：`WuJunde/werewolf_ai_agents`（工程化完整，基于 MetaGPT，有测试/CI）和 `muranUSTB/werewolf_kills_agentscope`（AgentScope 框架）。
2. **极简参考**：`Guoen0/werewolf_agents_arena` —— 结构一目了然（Player/Room/prompts/run/statistics），适合先读代码理解狼人杀 agent 的最小实现。
3. **竞技场/评测方向**：`Muqian-Sun/ai-werewolf-agent-teams` 的定位（评测 + 复盘 + 排行榜）与我们的一致，但 stars 低、较新，参考价值待评估。
4. **决定**：不直接 fork 任何项目，从零搭建我们自己的实现，架构上吸收上述项目优点（信息隔离、prompt 模板化、对局统计）。
