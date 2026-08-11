# 开源项目深度调研笔记

> 由多个子代理并行克隆源码通读后汇总。调研日期：2025-08-11。

## 1. Guoen0/werewolf_agents_arena（纯 Python 竞技场）

**架构**：`run.py`（主循环+50 局连跑+随机配模型）→ `Room.py`（状态机：`night_action`/`day_action`/`eliminate_player_by_votes`/`is_game_over_when`）→ `Player.py`（OpenAI Agents SDK 封装）→ `prompts.py`（全局规则）→ `stati.py`（离线统计 matplotlib 画图）。

**隔离实现**：每位玩家持有独立 `history`，法官通过 `judge_speech_to_players(message, [玩家列表])` 选择性推送消息——预言家验人结果、狼人刀人信息只发给指定玩家。输出用 pydantic 结构化输出（`Speech`/`Vote`/`Witch` 三模型），按 `output_type` 切换，天然防 prompt 注入。但单狼单预言家（1狼局），无猎人，规则极简。

**可借鉴**：`stati.py` 的按模型×角色胜率、女巫救/毒细分统计思路；`check_player_role` 把验人结果转文本的"法官中转"模式。

**坑**：角色/名字/模型列表写死在 `run.py`；发言顺序固定、无并发（串行 await，50 局很慢）；夜晚结算逻辑有 bug（`save_names==kill_names` 才判定平安夜，多杀去重）；平票即无人出局；无重试/容错，LLM 输出非法名字会静默失败。

## 2. chzisnull/werewolf-ai（FastAPI + React 观战版）

**架构**：`engine/game.py`（纯逻辑状态机 `GameEngine`，事件驱动 `emit`）→ `engine/models.py`（dataclass+枚举：`Role`/`GamePhase`/`GameEvent`/`GameState`）→ `ai/orchestrator.py`（`Room` 编排日夜流程+广播+暂停/回放）→ `ai/adapter.py`（prompt 模板+JSON 解析）→ `main.py`（REST+WebSocket）→ `frontend/`（React 观战 UI）。

**实现亮点**：`GameEvent` 带 `visible_to` 字段控制事件可见性（狼人刀人仅狼队可见、验人仅预言家可见），事件流即回放源；`get_visible_state` 按角色投影可见信息；`_resolve_seat_target` 把座位号/名字容错解析为 player_id，非法输出回退随机；女巫解析靠字符串匹配（"救"/"毒"），脆弱；夜晚 3 个角色串行、每步 `asyncio.sleep` 模拟节奏；狼人只由 1 号狼发言，无狼队协商。

**坑**：女巫行动用 `"救" in resp.content` 字符串猜意图，LLM 输出波动即失效；`sys.path.insert` hack；无持久化、单进程内存 RoomManager；猎人开枪事件只广播不处理；无 API 重试/超时兜底较少。

**综合建议**：借鉴仓库 2 的"纯引擎+事件流+可见性控制"分层（`game.py` 与 AI 解耦、可单测、可回放），借鉴仓库 1 的 pydantic 结构化输出防注入和按模型×角色统计；两者都缺：多狼协商、并发跑局、输出校验重试——正是本项目增量空间。

## 3. WuJunde/werewolf_ai_agents（MetaGPT 完整工程）

**架构**（基于 MetaGPT：Team→Environment→Role→Action→LLM）：
- `examples/werewolf_game/`：游戏本体。`start_game.py` 入口；`roles/` 有 Moderator、BasePlayer 及 Villager/Werewolf/Guard/Seer/Witch 子类；`actions/` 为各角色技能（Speak、Reflect、Hunt、Verify、Protect、Save/Poison、Impersonate、InstructSpeak 等）；`schema.py`+`actions/experience_operation.py` 是 ChromaDB 经验记忆系统；`evals/eval.py` 从日志离线统计投票准确率。
- `metagpt/environment/werewolf_env/`：ExtEnv 版状态机，与 Moderator 逻辑重复且未被调用。

**规则引擎**：无真正状态机：全局 `step_idx` 遍历 19 步 `STEP_INSTRUCTIONS`（守卫→狼人→女巫救/毒→预言家→白天发言→投票→处决），Moderator 本身是个 LLM Agent，负责发指令、用正则 `Player[0-9]+` 解析回复。夜晚结算（step 15）：死者=被猎且未被守/救+被毒；白天结算（step 18）：`Counter.most_common()` 取票王。胜负：狼全灭→好人胜；村民或神职全灭→狼胜。

**狼人协作**：各自独立喊 Kill，多数票胜出，无夜间聊天频道；狼人白天用 `Impersonate` 伪装身份（提示词要求不与同伴撞角色）。女巫靠指令关键词 "save/poison" 路由技能。每次行动=一次 JSON 结构化 prompt（BACKGROUND/HISTORY/STRATEGY/OUTPUT_FORMAT）+ `robust_json_loads` 解析。

**信息隔离**：Message 的 `send_to/restricted_to` + 角色 `addresses`（name/profile）路由，记忆只暴露 `sent_from` 不暴露身份；时间戳前缀防记忆去重。

**亮点**：`Reflect` 动作每轮生成逐玩家分析（声称身份/站队/指控），注入后续发言；经验系统按角色存 ChromaDB、检索 top5 相似局供参考；测试 `test_werewolf_ext_env.py` 纯逻辑无 LLM 依赖。

**坑**：规则逻辑双份实现（ExtEnv 死代码）；正则截取 `content[-10:]` 解析极脆弱；女巫药水次数仅 Moderator 版校验、无连续守夜/平票等规则细节；狼人无真实团队沟通仅多数票；白天天只一轮顺序发言非对话；与 MetaGPT 强耦合、依赖重，测试未覆盖 roles/actions，游戏示例无 CI。

## 4. muranUSTB/werewolf_kills_agentscope（AgentScope 框架）

**架构**：
- `agents.py`：`WerewolfPlayerAgent`（继承 AgentScope `AgentBase`，重写 observe/reply，自管 `self.history`）+ `ModeratorAgent`（主持人，纯消息工厂）
- `game.py`：`WerewolfGame` 主循环 `run()`：夜晚（守卫→狼人→女巫→预言家）→ 结算死亡 → 白天（发言→投票）→ 判胜；信息隔离靠 `_send_private`/`_send_to_wolves`/`_broadcast_public` 三个方法手动推送
- `game_state.py`：`GameState` dataclass（夜晚行动结果）+ `PlayerManager`（编号/角色索引、`check_game_over` 屠边判定）
- `prompts.py`：`RolePrompts`（BASE_PROMPT 槽位格式化）+ `GamePrompts` + `PlanStrategies`（6 种策略）
- `run_game.py`/`main.py`：12 玩家、角色与模型双重 shuffle、每玩家独立模型实例

**AgentScope 用法**：只用 `Msg`、`AgentBase`、`OpenAIChatModel` 和 `MsgHub`。`MsgHub` 仅用于狼人夜聊（`enable_auto_broadcast=True` 讨论 2 轮 → 秘密投票）。消息传递是引擎主动 push 进各玩家 history，非框架群聊；memory 系统完全没用。

**可借鉴**：
1. 双通道输出格式（prompts.py BASE_PROMPT）：思考放 `{}`（仅自己看），动作放 `[[n]]`（供 `extract_target` 正则解析）——轻量可靠的 agent 动作协议
2. 引擎侧显式隔离三方法（`_send_private` 等）——比框架内建广播更可审计
3. 守卫/女巫同守同救必死规则表（`_resolve_night_deaths`）——规则细节完整
4. `GameState`+`PlayerManager` 状态分离、`GamePrompts` 文案集中管理、策略 dict 数据驱动

**坑**：
1. `models.py` 的 Pydantic 结构化输出是死代码，从未 import；全靠 `[[n]]` 正则，LLM 不输出就静默失败（target=0→平安夜），无重试/校验——竞技场无人值守场景必炸
2. `agentscope/` 目录为空！代码 `sys.path.insert("agentscope/src")` 要求手动克隆框架源码；`from agentscope.pipeline import MsgHub` 是 1.x API，pip 装最新 2.0.6 不兼容，无 requirements.txt 无版本锁定
3. 投票可投死人、弃票无惩罚；env.json 的 temperature/max_tokens 配置未生效
4. 无胜率统计，只有文本日志；全程顺序 await 无并发；每人 history 全量膨胀，长局 token 成本翻 12 倍
5. README 承诺的文件（test_api.py、AGENTSCOPE_MIGRATION.md）不存在，WebUI 自认未完成

**结论**：设计思路（双通道输出、引擎侧隔离、MsgHub 狼人团聊）值得抄，但 AgentScope 只是薄壳且 API 变动大；竞技场建议自研 asyncio 编排 + OpenAI 兼容客户端。

## 5. KylJin/Werewolf（NeurIPS 2024，一夜狼人，可借鉴价值高）

**架构**：gym 风格分层设计。`onuw/environments/base.py` 定义 `Environment` 抽象类（reset/get_observation/step/check_action/is_terminal）+ `TimeStep`；`werewolf.py` 实现 ONUW 环境，状态全由 `MessagePool` 承载，用 `_current_phase`（Night→各角色→Day→Voting）+ `_switch_to_xxx()` 链式流转，Moderator 消息驱动回合；`arena.py` 是主循环（取玩家→观察→行动→校验→step，无效动作重试5次）；`agents/roles/base.py` 提供各阶段 prompt 模板，新角色只写 role_description；`agents/core/react.py` 纯 LLM、`dpins.py` 加 belief 建模+RL 策略选发言；`backends/` 统一 `query()` 接口可插拔多模型；`training/train.py`+`dataset_process/processor.py` 把日志转 d3rlpy 离线数据集训 CQL。

**解耦**：环境只认 `Message`+`player_name`，动作是 JSON dict（如 `{"player":"xx","thought":".."}`），role prompt 约束格式、环境校验，天然可复用。**标准狼人杀只需**：新环境改写夜晚（预言家→女巫→猎人→狼人顺序）、加出局机制、换 role_pool 配置，白天/投票几乎原样。

**可借鉴**：① `message_pool.get_visible_messages` 的 `visible_to` 私密信息机制（夜间信息必须）；② Moderator 消息驱动回合，天然适配 LLM 观察；③ `save_history` 带 ground truth/winner，直接支撑胜率统计；④ JSON 配置驱动建局。

**坑**：完整历史无截断致 token 膨胀；`check_action` 未实现；依赖旧 openai SDK 与 d3rlpy 旧 API，训练链路现跑不通。

## 6. HMJiangGatech/GPT4-werewolf

**架构**：单文件 `agent_cn.py`（600 行）：`GameMaster` 主循环 + `PlayerBot` 各持完整 chat_history，夜晚行动是纯随机规则代码，LLM 只管白天发言/投票；规则全塞进一个 `GAME_PROMPT` 字符串；无环境/agent 分离、无校验，投票靠字符串匹配玩家名。**可借鉴**：主持人 prompt 注入私密信息（"记住你晚上的信息是…"）与狼人"归票"指令的写法。**坑**：不可扩展、无统计、旧 SDK，仅作 prompt 参考。

## 7. Muqian-Sun/ai-werewolf-agent-teams（字节跳动评测+复盘平台，完整可跑）

**架构**：插件化分层：`plugins/`（11 类 121 个插件，manifest.yaml + class_path 反射加载）→ `server/core/`（GameKernel 内核，grep 验证零角色名硬编码）→ `server/game/`（phase_runners 规则编排）→ `server/agents/`（记忆/决策/拼装）→ `server/eval/`（评测/复盘）→ `server/storage/`（31 张表）+ `server/api/` + `web/`（React 10 页面）。255 个 py 文件、789 个测试函数，工程量真实。

**核心机制**：
- 对局引擎：`kernel.py` 的 `setup_game`/`run_round`/`check_win`——phase 顺序由 manifest 的 `transition_to`+`concurrent_with` 图驱动，按 phase id 分发到 `phase_runners.py` 的 `PHASE_HANDLERS`；夜狼用 `wolf_discuss.py` 多轮商议收敛；胜负由 faction 插件 `win_spec` 声明式判定（如 `Or(AllAgentsOfRoleDead(...))`）；config.yaml 配置 3 狼+预女猎+3 民。
- 信息隔离：双闸——`channel_router.py` 写时按 role 订阅投递（无关 Agent 物理收不到，落 channel_events 审计）；`observation_builder.py` 读时按 visibility 插件遮蔽 `[REDACTED:reason]`，ground_truth vs visible 双视图落库。
- Trace：七层全链路落库（观测→记忆/信念→prompt 仓库→拼装→LLM 调用→决策→排行榜），WS 推送+前端逐层下钻；决策 JSON 走 `parser.py` 四级解析链（strict→json_repair→repair prompt→rule_fallback）。
- 复盘：`counterfactual.py` 回放-分叉（同 seed 重放已存决策至 fork 点，换 alt 决策后真 LLM 续演）；`badcase.py` 失误→根因→建议→采纳→验证闭环。
- 排行榜：`leaderboard_sink.py` 按 composition/model/persona/agent_stack 四维聚合 win_rate+24 指标，快照持久化。

**可借鉴**：插件化内核（加角色零核心改动）、双闸隔离、四级 JSON 解析链、SkillPipeline 五 middleware（Trace/Permission/Quota/SpecValidation/Emit）、同 seed 复现+决策全落库支撑反事实下钻。

**坑**：公开仓库只留代码（README 承诺的 23 份 docs/ 和 server/.venv 均未入库）；`pyproject.toml` 无 build-system，`pip install -e .` 失败；测试强依赖真实 PostgreSQL（schema 隔离），无 DB 无法跑；单局约 1 小时（豆包推理模型 54s/call），跑批成本高；LLM provider 仅豆包；仅 1 个公开 commit、无文档难维护。

**结论**：完整可跑的高质量工程（非概念验证），但属"重依赖单机项目"：需自备 PG+豆包 Key。架构与复盘体系参考价值极高，建议借鉴其内核/隔离/Trace 设计，LLM 层换通用 provider、删繁就简自建。

## 总结：对自建竞技场的启示

| 设计点 | 最佳来源 |
|---|---|
| 纯引擎+事件流+可见性分层（可单测/回放） | chzisnull/werewolf-ai、KylJin/Werewolf |
| 结构化输出防注入（pydantic / JSON schema） | Guoen0、MuqianSun 四级解析链 |
| 信息隔离（写时路由 + 读时遮蔽双闸） | MuqianSun、KylJin `visible_to` |
| 多狼夜间协商收敛 | MuqianSun `wolf_discuss.py`、agentscope MsgHub |
| 引擎侧显式私发/群发方法（可审计） | muranUSTB agentscope |
| 胜率×角色×模型统计 | Guoen0 `stati.py` |
| 同 seed 复现 + 决策全落库（反事实复盘） | MuqianSun |
| 轻量双通道输出协议（思考 + `[[n]]` 动作） | muranUSTB prompts |
| 可插拔模型后端（统一 query() 接口） | KylJin `backends/` |
| 主持人 prompt 注入私密信息写法 | HMJiangGatech |

**共同的坑**：历史全量膨胀无截断、无重试/校验静默失败、规则写死、依赖锁不住。
