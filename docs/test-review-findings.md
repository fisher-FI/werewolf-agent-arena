# 测试前审查发现（子代理产出汇总）

## 🔗 前后端契约审查（已完成）

| # | 问题 | 严重度 | 说明 |
|---|---|---|---|
| 1 | **WS 阶段同步缺失** | 中 | 引擎转移 night_resolve/shoot/day_resolve 只发 game_event，前端徽章只由 phase_change 更新 → 头部阶段徽章滞后。建议：前端在 game_event.phase 变化时同步 setPhase |
| 2 | **人类输入链路断裂** | 高 | wait_human_speech/wait_human_vote 前端无 case；添加玩家硬编码 'ai' → 人类玩家会空等 120s 超时 |
| 3 | wolf_discuss 死代码 | 低 | 枚举有但从不发射，前端分支冗余 |
| 4 | room_state 忽略 phase/day_count | 低 | WS 重连后徽章可能陈旧 |
| 5 | game_start 缺 max_players | 低 | 前端靠 players.length 兜底 |

字段对齐健康：vote_cast target_name/abstain、reflection metadata、ai_reasoning 六字段、role_assigned team、game_end winner_label 全对齐。
角色/阶段全覆盖：11 角色 emoji/label、8 阶段徽章。

## ⏳ 待完成
- [x] 测试矩阵设计（四层清单：引擎40/编排15/API10/真LLM冒烟1，预计新增约65个）
- [ ] 规则审查（14 个疑点）

## 🧪 测试矩阵摘要
- **P0（~30）**：状态机全转移、夜晚9组合、猎人5死法、判胜时机、私密事件可见性、5板子全流程、API CRUD+WS回放、真LLM冒烟
- **P1（~25）**：白痴投票权、自爆进夜、记忆系统、弃票/平票循环、人类超时、狼人两轮讨论、调用上限
- **P2（~10）**：随机性统计、药水泄露锁定、屠城模式、断连自动暂停、多客户端并发

## 🐛 已确认的真实 Bug（待修）
| # | Bug | 位置 | 影响 |
|---|---|---|---|
| 1 | 白痴翻牌后仍能投票 | engine：pending_idiot 只记录不拦截 | 规则错误 |
| 2 | 自爆后仍继续投票 | orchestrator：自爆后未直接进夜 | 规则错误 |
| 3 | 女巫药水剩余量全员可见 | engine get_visible_state | 信息泄露 |
| 4 | 人类输入链路断裂 | 前端无 wait_human case、硬编码 ai | 人类玩家空等120s |
| 5 | WS 阶段徽章滞后 | 前端只认 phase_change | UI 显示滞后 |
