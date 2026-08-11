"""房间管理 & AI 调度器 — 协调游戏流程（支持任意板子/人数）"""

from __future__ import annotations
import asyncio
import json
import random
import uuid
import logging
from collections import Counter
from typing import Optional

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.models import (
    Player, Role, Team, GamePhase, EventType, GameEvent, AIConfig,
)
from engine.game import GameEngine
from engine.boards import Board, get_board
from ai.adapter import AIAdapter, AIResponse
from ai.memory import MemoryManager

logger = logging.getLogger("werewolf.room")


class Room:
    """游戏房间"""

    def __init__(self, room_id: str = None, board_id: str = None):
        self.id = room_id or uuid.uuid4().hex[:8]
        self.board: Board = get_board(board_id)
        self.players: list[Player] = []
        self.engine: Optional[GameEngine] = None
        self.adapters: dict[str, AIAdapter] = {}
        self.status: str = "waiting"
        self.paused: bool = False
        self.speaker_order: list[str] = []
        self.current_speaker_idx: int = 0
        self._ws_broadcast = None
        self._wait_for_human: Optional[asyncio.Future] = None
        self.game_events: list[dict] = []
        self.game_reasonings: list[dict] = []
        self.connected_clients: int = 0
        self.delay_factor: float = 1.0   # 测试置 0 可加速
        self.reflection_enabled: bool = True  # 二次思考开关
        self.memory = MemoryManager()    # 玩家全量记忆

    # ─── 基础 ───

    @property
    def max_players(self) -> int:
        return self.board.player_count

    async def _delay(self, seconds: float):
        """模拟节奏延迟（测试可置 0）"""
        await asyncio.sleep(seconds * self.delay_factor)

    async def _check_pause(self):
        while self.paused:
            await asyncio.sleep(0.5)

    def set_broadcast(self, callback):
        self._ws_broadcast = callback

    async def broadcast(self, event_type: str, data: dict):
        if event_type == "game_event":
            self.game_events.append(data)
        elif event_type == "ai_reasoning":
            self.game_reasonings.append(data)
        elif event_type == "phase_change":
            self.game_events.append({
                "event_type": "phase_change",
                "content": data.get("content", ""),
                "phase": data.get("phase", ""),
                "day_count": data.get("day_count", 0),
                "timestamp": __import__("datetime").datetime.now().isoformat(),
            })
        elif event_type == "role_assigned":
            self.game_events.append({"event_type": "_role", **data})
        if self._ws_broadcast:
            await self._ws_broadcast(event_type, data)

    async def send_history(self, ws):
        if self.engine and self.engine.state.roles:
            for pid, role in self.engine.state.roles.items():
                try:
                    await ws.send_text(json.dumps({
                        "type": "role_assigned",
                        "data": {
                            "player_id": pid, "role": role.value,
                            "role_label": role.label, "role_emoji": role.emoji,
                            "team": role.team.value,
                        }
                    }, ensure_ascii=False))
                except Exception:
                    pass
        for evt in self.game_events:
            if evt.get("event_type") == "_role":
                continue
            try:
                await ws.send_text(json.dumps({
                    "type": "game_event", "data": evt,
                }, ensure_ascii=False))
            except Exception:
                pass
        for r in self.game_reasonings:
            try:
                await ws.send_text(json.dumps({
                    "type": "ai_reasoning", "data": r,
                }, ensure_ascii=False))
            except Exception:
                pass
        if self.paused:
            try:
                await ws.send_text(json.dumps({
                    "type": "game_paused", "data": {"paused": True},
                }, ensure_ascii=False))
            except Exception:
                pass

    def add_player(self, player: Player) -> bool:
        if len(self.players) >= self.max_players:
            return False
        if self.status != "waiting":
            return False
        if any(p.seat == player.seat for p in self.players):
            return False
        self.players.append(player)
        return True

    def remove_player(self, player_id: str):
        self.players = [p for p in self.players if p.id != player_id]

    def setup_ai_adapters(self, default_config: AIConfig):
        for p in self.players:
            if p.player_type == "ai":
                config = p.ai_config or default_config
                adapter = AIAdapter(config)
                adapter.set_memory(self.memory)
                self.adapters[p.id] = adapter

    # ─── 通用工具 ───

    def _alive_names(self) -> str:
        names = []
        for pid in self.engine.state.alive_players:
            p = self.engine.get_player(pid)
            names.append(f"{p.seat}号({p.name})" if p else pid)
        return ", ".join(names)

    async def _act(self, player_id: str, method: str, *args) -> AIResponse:
        """带暂停检查的 AI 行动调用"""
        await self._check_pause()
        resp = await getattr(self.adapters[player_id], method)(self.engine, player_id, *args)
        return resp

    async def _broadcast_ai(self, player_id: str, resp: AIResponse, action_desc: str = ""):
        p = self.engine.get_player(player_id)
        await self.broadcast("ai_reasoning", {
            "player_id": player_id,
            "player_name": p.name if p else "",
            "reasoning": resp.reasoning,
            "speech": resp.content,
            "thinking_time": resp.thinking_time,
            "confidence": resp.confidence,
            "action": action_desc,
        })

    async def _emit_engine_events(self, events: list):
        """广播引擎事件，遇 GAME_END 结束游戏"""
        for event in events:
            await self.broadcast("game_event", event.to_dict())
            if event.event_type == EventType.GAME_END:
                await self._on_game_end()
                return True
        return False

    # ─── 游戏主流程 ───

    async def start_game(self):
        if len(self.players) != self.max_players:
            raise ValueError(f"板子 {self.board.name} 需要 {self.max_players} 人，当前 {len(self.players)} 人")
        self.status = "playing"
        self.engine = GameEngine(self.players, self.board)
        self.engine.assign_roles()

        await self.broadcast("game_start", {
            "room_id": self.id,
            "board": {"id": self.board.id, "name": self.board.name,
                       "max_players": self.max_players},
            "players": [p.to_public_dict() for p in self.players],
        })
        for p in self.players:
            role = self.engine.state.roles.get(p.id)
            if role:
                await self.broadcast("role_assigned", {
                    "player_id": p.id, "role": role.value,
                    "role_label": role.label, "role_emoji": role.emoji,
                    "team": role.team.value,
                })

        self.engine.start_game()
        await self.broadcast("phase_change", {
            "phase": "night", "day_count": 1,
            "content": f"游戏开始！板子：{self.board.name}（{self.max_players}人局）",
        })
        await self._delay(2)
        await self._run_night()

    # ─── 夜晚 ───

    async def _run_night(self):
        """按板子 night_order 调度夜晚行动"""
        await self._check_pause()
        state = self.engine.state
        order = self.board.night_order

        # 首夜丘比特连人
        if self.board.first_night_cupid and state.day_count == 1:
            cupids = self.engine.alive_role(Role.CUPID)
            if cupids:
                resp = await self._act(cupids[0], "decide_night_action")
                target = self._resolve_cupid_target(resp, cupids[0])
                if target and len(target) == 2:
                    try:
                        self.engine.process_cupid_chain(cupids[0], target[0], target[1])
                        await self._emit_engine_events([self.engine.state.events[-1]])
                    except ValueError as e:
                        logger.warning(f"丘比特行动非法被拒绝: {e}")
                await self._delay(2)

        # 守卫守人
        if "guard" in order:
            guards = self.engine.alive_role(Role.GUARD)
            if guards:
                resp = await self._act(guards[0], "decide_night_action")
                if resp.action:
                    try:
                        self.engine.process_guard_protect(guards[0], resp.action)
                        await self._emit_engine_events([self.engine.state.events[-1]])
                        await self._broadcast_ai(guards[0], resp, "守卫守护目标")
                        # 记忆：守卫守护记录
                        t = self.engine.get_player(resp.action)
                        self.memory.get(guards[0]).record_private(
                            state.day_count, f"你守护了 {t.name if t else resp.action}")
                    except ValueError as e:
                        logger.warning(f"守卫行动非法被拒绝: {e}")
                await self._delay(2)

        # 狼人（含狼王/白狼王）：内部讨论 + 共识刀人
        wolves = self.engine.get_alive_werewolves()
        if wolves and "wolf" in order:
            await self._run_wolf_night(wolves)

        # 女巫
        if "witch" in order:
            witches = self.engine.alive_role(Role.WITCH)
            if witches:
                resp = await self._act(witches[0], "decide_night_action")
                witch_events = self.engine.process_witch_action(
                    witches[0], save=resp.save, poison_target=resp.poison_target)
                # 只广播女巫实际产生的行动事件（不广播狼刀等私密事件）
                for e in witch_events:
                    await self._emit_engine_events([e])
                await self._broadcast_ai(witches[0], resp, "女巫行动")
                # 记忆：女巫药水使用
                mem = self.memory.get(witches[0])
                if resp.save:
                    mem.record_private(state.day_count, "你使用了解药救人")
                if resp.poison_target:
                    t = self.engine.get_player(resp.poison_target)
                    mem.record_private(state.day_count,
                                       f"你使用了毒药毒杀 {t.name if t else resp.poison_target}")
                await self._delay(2)

        # 预言家
        if "seer" in order:
            seers = self.engine.alive_role(Role.SEER)
            if seers:
                resp = await self._act(seers[0], "decide_night_action")
                if resp.action:
                    self.engine.process_seer_check(seers[0], resp.action)
                    await self._emit_engine_events([self.engine.state.events[-1]])
                    await self._broadcast_ai(seers[0], resp, "预言家查验")
                    # 记忆：预言家查验结果（私密）——用 team 判定，狼王/白狼王也是狼
                    is_wolf = (Role(self.engine.state.roles[resp.action]).team
                               == Team.WEREWOLF)
                    t = self.engine.get_player(resp.action)
                    self.memory.get(seers[0]).record_private(
                        state.day_count,
                        f"你查验了 {t.name if t else resp.action}，结果是{'狼人' if is_wolf else '好人'}")
                await self._delay(2)

        # 结算夜晚
        await self._check_pause()
        events = self.engine.resolve_night()
        if await self._emit_engine_events(events):
            return
        # 记忆：所有存活玩家记录夜晚结果
        deaths_today = [e for e in events
                        if e.event_type == EventType.PLAYER_DEATH]
        if deaths_today:
            night_note = "昨晚 " + ", ".join(e.content for e in deaths_today)
        else:
            night_note = "昨晚是平安夜"
        for pid in self.engine.state.alive_players:
            self.memory.get(pid).record_night(state.day_count, night_note)
        await self._handle_shoot_window()
        if self.status == "finished":
            return
        await self._delay(1)
        await self._run_discussion()

    async def _run_wolf_night(self, wolves: list):
        """狼人内部讨论：提案 → 汇总 → 必要时最终票 → 多数票共识"""
        if len(wolves) == 1:
            resp = await self._act(wolves[0], "decide_night_action")
            if resp.action:
                self.engine.process_werewolf_kill(resp.action)
                await self._broadcast_ai(wolves[0], resp, "狼人选择击杀目标")
                self._record_wolf_kill(wolves, resp.action)
            await self._delay(2)
            return

        # 第 1 轮：独立提案（并行，节省等待）
        proposals = {}
        async def _propose(wolf_id):
            resp = await self._act(wolf_id, "decide_night_action")
            return wolf_id, resp
        for wolf_id, resp in await asyncio.gather(*[_propose(w) for w in wolves]):
            proposals[wolf_id] = resp.action
            await self._broadcast_ai(wolf_id, resp, "狼人提案")

        def majority(votes: dict) -> Optional[str]:
            counts = Counter(v for v in votes.values() if v)
            if not counts:
                return None
            top = counts.most_common()
            if len(top) == 1 or top[0][1] > top[1][1]:
                return top[0][0]
            return None

        consensus = majority(proposals)

        # 第 2 轮：汇总队友倾向，投最终票（并行）
        if consensus is None:
            summary = self._summarize_proposals(proposals)
            final_votes = {}
            async def _final(wolf_id):
                resp = await self._act(wolf_id, "decide_final_wolf_vote", summary)
                return wolf_id, resp
            for wolf_id, resp in await asyncio.gather(*[_final(w) for w in wolves]):
                final_votes[wolf_id] = resp.action
                await self._broadcast_ai(wolf_id, resp, "狼人最终投票")
            consensus = majority(final_votes)
            if consensus is None:  # 仍平票 → 第一只狼定夺
                consensus = final_votes.get(wolves[0]) or random.choice(
                    [v for v in final_votes.values() if v] or [wolves[0]])

        if consensus:
            self.engine.process_werewolf_kill(consensus)
            await self._emit_engine_events([self.engine.state.events[-1]])
            self._record_wolf_kill(wolves, consensus)
        await self._delay(2)

    def _record_wolf_kill(self, wolves: list, target_id: str):
        """狼人刀人记录到狼队私密记忆"""
        t = self.engine.get_player(target_id)
        tname = t.name if t else target_id
        for wolf_id in wolves:
            self.memory.get(wolf_id).record_private(
                self.engine.state.day_count, f"你们狼队选择击杀 {tname}")

    def _summarize_proposals(self, proposals: dict) -> str:
        parts = []
        for wolf_id, target in proposals.items():
            name = self.engine.get_player(wolf_id).name
            tname = self.engine.get_player(target).name if target and target in self.engine.players else "（弃刀）"
            parts.append(f"{name} 建议击杀 {tname}")
        return "；".join(parts)

    def _resolve_cupid_target(self, resp: AIResponse, cupid_id: str) -> list:
        """解析丘比特选择（从 metadata 里的两个座位）"""
        ids = resp.metadata.get("lovers", []) if resp.metadata else []
        resolved = [self._seat_to_id(x) for x in ids if x]
        alive = [p for p in self.engine.state.alive_players
                 if p != cupid_id]
        resolved = [p for p in resolved if p in alive]
        return resolved[:2] if len(resolved) == 2 else []

    def _seat_to_id(self, target) -> str:
        if target in self.engine.players:
            return target
        try:
            seat = int(target)
            for pid in self.engine.state.alive_players:
                p = self.engine.get_player(pid)
                if p and p.seat == seat:
                    return pid
        except (ValueError, TypeError):
            pass
        return ""

    # ─── 开枪窗口（猎人/狼王） ───

    async def _handle_shoot_window(self):
        """处理 pending_shoots 队列（可能多人在队列）"""
        while self.engine.state.pending_shoots and self.status != "finished":
            await self._check_pause()
            shooter, kind = self.engine.state.pending_shoots[0]
            player = self.engine.get_player(shooter)
            # 人类玩家：广播等待输入（简化：无输入时 120s 后放弃）
            if player and player.player_type == "human":
                self._pending_human_shoot = None
                await self.broadcast("wait_human_shoot", {
                    "player_id": shooter, "player_name": player.name,
                })
                await self._wait_for_human_input(shooter)
                # 人类开枪：有输入则开枪，无输入则放弃（不会崩溃）
                target = getattr(self, "_pending_human_shoot", None)
                events = self.engine.process_shoot(shooter, target)
                if await self._emit_engine_events(events):
                    return
                continue
            resp = await self._act(shooter, "decide_shoot")
            events = self.engine.process_shoot(shooter, resp.action)
            if await self._emit_engine_events(events):
                return
            await self._broadcast_ai(shooter, resp, "开枪/带人")
            await self._delay(2)

    # ─── 白天 ───

    async def _run_discussion(self):
        await self._check_pause()
        await self.broadcast("phase_change", {
            "phase": "day_discuss",
            "day_count": self.engine.state.day_count,
            "content": f"第{self.engine.state.day_count}天，讨论阶段开始。",
        })

        self.speaker_order = self.engine.get_speaker_order()
        self.current_speaker_idx = 0

        for speaker_id in self.speaker_order:
            if speaker_id not in self.engine.state.alive_players:
                continue
            player = self.engine.get_player(speaker_id)
            if not player:
                continue

            await self.broadcast("current_speaker", {
                "player_id": speaker_id, "player_name": player.name, "action": "speaking",
            })

            if player.player_type == "ai" and speaker_id in self.adapters:
                resp = await self._act(speaker_id, "make_speech")
                event = self.engine.process_speech(speaker_id, resp.content, resp.reasoning)
                await self.broadcast("game_event", event.to_dict())
                await self._broadcast_ai(speaker_id, resp)
                # 记忆：自己发言 + 所有存活玩家听到
                self.memory.get(speaker_id).record_own_speech(
                    self.engine.state.day_count, resp.content)
                self.memory.get(speaker_id).record_reasoning(
                    self.engine.state.day_count, "发言", resp.reasoning)
                for other in self.engine.state.alive_players:
                    if other != speaker_id:
                        self.memory.get(other).record_heard(
                            self.engine.state.day_count, player.name, resp.content)

                # ── 二次思考：反思刚才的发言，补充/修正一轮 ──
                if self.reflection_enabled and resp.content and \
                        resp.content != "[AI 暂时无法发言]":
                    await self._check_pause()
                    ref = await self.adapters[speaker_id].make_reflection(
                        self.engine, speaker_id, resp.content)
                    if ref.content:
                        ref_event = self.engine.process_speech(
                            speaker_id, ref.content, ref.reasoning)
                        ref_event.metadata["reflection"] = True
                        await self.broadcast("game_event", ref_event.to_dict())
                        await self._broadcast_ai(speaker_id, ref, "二次思考补充")
                        # 记忆：补充发言也记录
                        self.memory.get(speaker_id).record_own_speech(
                            self.engine.state.day_count, ref.content)
                        for other in self.engine.state.alive_players:
                            if other != speaker_id:
                                self.memory.get(other).record_heard(
                                    self.engine.state.day_count, player.name, ref.content)
            elif player.player_type == "human":
                await self.broadcast("wait_human_speech", {
                    "player_id": speaker_id, "player_name": player.name,
                })
                await self._wait_for_human_input(speaker_id)
            await self._delay(2)

        await self.broadcast("current_speaker", {"player_id": None, "action": "done"})

        # 狼王/白狼王自爆窗口
        await self._check_pause()
        if self.status != "finished":
            await self._run_explode_window()
        if self.status == "finished":
            return

        # 骑士决斗窗口
        await self._check_pause()
        if self.status != "finished":
            await self._run_knight_window()
        if self.status == "finished":
            return

        await self._run_vote()

    async def _run_explode_window(self):
        """狼王/白狼王可自爆：自爆后直接入夜（跳过决斗/投票）"""
        state = self.engine.state
        for pid in list(state.alive_players):
            role = Role(state.roles.get(pid))
            if role in (Role.ALPHA_WOLF, Role.WHITE_WOLF_KING) and pid in self.adapters:
                resp = await self._act(pid, "decide_explode")
                if resp.action == "__explode__" or resp.action == "__explode_and_take__":
                    events = self.engine.process_self_explode(pid, resp.poison_target)
                    await self._emit_engine_events(events)
                    await self._broadcast_ai(pid, resp, "自爆")
                    if self.status == "finished":
                        return
                    # 自爆带走猎人 → 处理开枪队列
                    await self._handle_shoot_window()
                    if self.status == "finished":
                        return
                    # 直接进入夜晚
                    await self.broadcast("phase_change", {
                        "phase": "night",
                        "day_count": self.engine.state.day_count,
                        "content": f"{self.engine.get_player(pid).name} 自爆，直接进入夜晚！",
                    })
                    await self._run_night()
                    return

    async def _run_knight_window(self):
        """骑士决斗（可弃）"""
        state = self.engine.state
        for pid in list(state.alive_players):
            if Role(state.roles.get(pid)) == Role.KNIGHT and pid in self.adapters:
                resp = await self._act(pid, "decide_duel")
                if resp.action:
                    events = self.engine.process_knight_duel(pid, resp.action)
                    await self._emit_engine_events(events)
                    await self._broadcast_ai(pid, resp, "骑士决斗")
                return

    async def _run_vote(self):
        await self._check_pause()
        self.engine.start_vote()
        await self.broadcast("phase_change", {
            "phase": "day_vote",
            "day_count": self.engine.state.day_count,
            "content": f"第{self.engine.state.day_count}天，投票阶段开始。",
        })

        for pid in self.engine.state.alive_players:
            player = self.engine.get_player(pid)
            if not player:
                continue
            await self.broadcast("current_speaker", {
                "player_id": pid, "player_name": player.name, "action": "voting",
            })
            if player.player_type == "ai" and pid in self.adapters:
                resp = await self._act(pid, "cast_vote")
                if resp.action:
                    self.engine.process_vote(pid, resp.action)
                    await self.broadcast("game_event", self.engine.state.events[-1].to_dict())
                    await self._broadcast_ai(pid, resp, "投票")
                    logger.info(f"[投票阶段] {player.name} 投给 {self.engine.get_player(resp.action).name if resp.action in self.engine.players else resp.action}")
                    # 记忆：自己投了谁
                    target_name = (self.engine.get_player(resp.action).name
                                   if resp.action in self.engine.players else resp.action)
                    self.memory.get(pid).record_vote(self.engine.state.day_count, target_name)
                else:
                    # 弃票是合法行为：明确记录并广播
                    event = self.engine.process_abstain(pid)
                    await self.broadcast("game_event", event.to_dict())
                    await self._broadcast_ai(pid, resp, "弃票")
                    logger.info(f"[投票阶段] {player.name} 弃票")
            elif player.player_type == "human":
                await self.broadcast("wait_human_vote", {
                    "player_id": pid, "player_name": player.name,
                })
                await self._wait_for_human_input(pid)
            await self._delay(1.5)

        await self.broadcast("current_speaker", {"player_id": None, "action": "done"})

        await self._check_pause()
        logger.info(f"[投票阶段] 投票收集完毕: {len(self.engine.state.vote_results)}/{len(self.engine.state.alive_players)} 人投票")
        events = self.engine.resolve_votes()
        if await self._emit_engine_events(events):
            return
        await self._handle_shoot_window()
        if self.status == "finished":
            return
        await self._delay(2)
        await self._run_night()

    async def _wait_for_human_input(self, player_id: str):
        loop = asyncio.get_event_loop()
        self._wait_for_human = loop.create_future()
        try:
            await asyncio.wait_for(self._wait_for_human, timeout=120)
        except asyncio.TimeoutError:
            pass
        self._wait_for_human = None

    def receive_human_input(self, player_id: str, content: str, input_type: str = "speech"):
        if input_type == "speech":
            self.engine.process_speech(player_id, content)
        elif input_type == "vote":
            self.engine.process_vote(player_id, content)
        elif input_type == "shoot":
            # 人类开枪：content 为座位号/玩家名，解析后开枪；空=放弃
            target = self._resolve_human_target(content)
            self._pending_human_shoot = target
        if self._wait_for_human and not self._wait_for_human.done():
            self._wait_for_human.set_result(True)

    def _resolve_human_target(self, content: str) -> str:
        """把人类输入解析为 player_id（座位号或名字）"""
        if not self.engine:
            return ""
        content = content.strip()
        if not content:
            return ""  # 空输入 = 放弃
        try:
            seat = int(content)
            for pid in self.engine.state.alive_players:
                p = self.engine.get_player(pid)
                if p and p.seat == seat:
                    return pid
        except ValueError:
            for pid in self.engine.state.alive_players:
                p = self.engine.get_player(pid)
                if p and content in p.name:
                    return pid
        return ""

    async def _on_game_end(self):
        self.status = "finished"
        state = self.engine.state
        roles_reveal = {
            pid: {"role": state.roles[pid].value,
                  "label": state.roles[pid].label,
                  "emoji": state.roles[pid].emoji,
                  "name": self.engine.get_player(pid).name,
                  "alive": pid in state.alive_players}
            for pid in self.engine.player_order
        }
        await self.broadcast("game_end", {
            "winner": state.winner.value if state.winner else None,
            "winner_label": "❤️情侣阵营" if state.winner == Team.LOVERS
                            else "好人阵营" if state.winner == Team.VILLAGER else "狼人阵营",
            "winner_reason": state.winner_reason,
            "roles": roles_reveal,
        })

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "status": self.status,
            "board": {"id": self.board.id, "name": self.board.name, "max_players": self.max_players},
            "players": [p.to_dict() for p in self.players],
            "player_count": len(self.players),
            "paused": self.paused,
        }
        if self.engine:
            d["phase"] = self.engine.state.phase.value
            d["day_count"] = self.engine.state.day_count
        return d


# ─── 全局房间管理 ───

class RoomManager:
    def __init__(self):
        self.rooms: dict[str, Room] = {}
        self.default_ai_config = AIConfig(
            provider="xiaomi",
            model="mimo-v2.5-pro",
            base_url="https://token-plan-cn.xiaomimimo.com/v1",
            api_key="",
            temperature=0.8,
            personality="一个聪明、善于推理的玩家",
        )

    def create_room(self, board_id: str = None) -> Room:
        room = Room(board_id=board_id)
        self.rooms[room.id] = room
        return room

    def get_room(self, room_id: str) -> Optional[Room]:
        return self.rooms.get(room_id)

    def list_rooms(self) -> list[dict]:
        return [r.to_dict() for r in self.rooms.values()]

    def delete_room(self, room_id: str):
        self.rooms.pop(room_id, None)
