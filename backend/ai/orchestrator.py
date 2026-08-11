"""房间管理 & AI 调度器 — 协调游戏流程"""

from __future__ import annotations
import asyncio
import json
import uuid
import logging
from typing import Optional

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.models import (
    Player, Role, Team, GamePhase, EventType, GameEvent, AIConfig
)
from engine.game import GameEngine
from ai.adapter import AIAdapter, AIResponse

logger = logging.getLogger("werewolf.room")


class Room:
    """游戏房间"""

    def __init__(self, room_id: str = None):
        self.id = room_id or uuid.uuid4().hex[:8]
        self.players: list[Player] = []
        self.engine: Optional[GameEngine] = None
        self.adapters: dict[str, AIAdapter] = {}   # player_id -> adapter
        self.status: str = "waiting"               # waiting / playing / finished
        self.paused: bool = False                    # 暂停状态
        self.speaker_order: list[str] = []
        self.current_speaker_idx: int = 0
        self._ws_broadcast = None                  # WebSocket 广播回调
        self._wait_for_human: Optional[asyncio.Future] = None
        self.game_events: list[dict] = []           # 存储所有游戏事件（用于回放）
        self.game_reasonings: list[dict] = []       # 存储所有AI推理（用于回放）
        self.connected_clients: int = 0             # 当前连接的客户端数

    async def _check_pause(self):
        """暂停时等待，直到恢复"""
        while self.paused:
            await asyncio.sleep(0.5)

    def set_broadcast(self, callback):
        """设置 WebSocket 广播回调"""
        self._ws_broadcast = callback

    async def broadcast(self, event_type: str, data: dict):
        """广播消息到所有客户端，同时存储用于回放"""
        # 存储游戏事件和推理
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
        """向新连接的客户端发送历史事件"""
        # 发送角色信息
        if self.engine and self.engine.state.roles:
            for pid, role in self.engine.state.roles.items():
                try:
                    await ws.send_text(json.dumps({
                        "type": "role_assigned",
                        "data": {
                            "player_id": pid,
                            "role": role.value,
                            "role_label": role.label,
                            "role_emoji": role.emoji,
                            "team": role.team.value,
                        }
                    }, ensure_ascii=False))
                except Exception:
                    pass

        # 发送所有历史事件
        for evt in self.game_events:
            # 跳过角色事件（已通过 role_assigned 发送）
            if evt.get("event_type") == "_role":
                continue
            try:
                await ws.send_text(json.dumps({
                    "type": "game_event",
                    "data": evt,
                }, ensure_ascii=False))
            except Exception:
                pass

        # 发送所有历史推理
        for r in self.game_reasonings:
            try:
                await ws.send_text(json.dumps({
                    "type": "ai_reasoning",
                    "data": r,
                }, ensure_ascii=False))
            except Exception:
                pass

        # 发送当前暂停状态
        if self.paused:
            try:
                await ws.send_text(json.dumps({
                    "type": "game_paused",
                    "data": {"paused": True},
                }, ensure_ascii=False))
            except Exception:
                pass

    def add_player(self, player: Player) -> bool:
        if len(self.players) >= 9:
            return False
        if self.status != "waiting":
            return False
        self.players.append(player)
        return True

    def remove_player(self, player_id: str):
        self.players = [p for p in self.players if p.id != player_id]

    def setup_ai_adapters(self, default_config: AIConfig):
        """为所有 AI 玩家创建适配器"""
        for p in self.players:
            if p.player_type == "ai":
                config = p.ai_config or default_config
                self.adapters[p.id] = AIAdapter(config)

    async def start_game(self):
        """开始游戏"""
        if len(self.players) < 6:
            raise ValueError("至少需要6个玩家")

        self.status = "playing"
        self.engine = GameEngine(self.players)
        self.engine.assign_roles()

        # 广播游戏开始
        await self.broadcast("game_start", {
            "room_id": self.id,
            "players": [p.to_public_dict() for p in self.players],
        })

        # 通知每个玩家他们的角色（私密）
        for p in self.players:
            role = self.engine.state.roles.get(p.id)
            if role:
                await self.broadcast("role_assigned", {
                    "player_id": p.id,
                    "role": role.value,
                    "role_label": role.label,
                    "role_emoji": role.emoji,
                    "team": role.team.value,
                })

        # 开始第一晚
        await self._run_night()

    async def _run_night(self):
        """执行夜间阶段"""
        self.engine.start_night()
        await self.broadcast("phase_change", {
            "phase": "night",
            "day_count": self.engine.state.day_count,
            "content": f"第{self.engine.state.day_count}个夜晚降临了…所有人闭眼。",
        })
        await asyncio.sleep(2)

        state = self.engine.state

        # 狼人行动
        wolves = self.engine.get_alive_werewolves()
        if wolves:
            await self._check_pause()
            wolf_id = wolves[0]  # 由第一个狼人代表发言
            if wolf_id in self.adapters:
                resp = await self.adapters[wolf_id].decide_night_action(self.engine, wolf_id)
                if resp.action:
                    self.engine.process_werewolf_kill(resp.action)
                    target = self.engine.get_player(resp.action)
                    await self.broadcast("ai_reasoning", {
                        "player_id": wolf_id,
                        "player_name": self.engine.get_player(wolf_id).name,
                        "reasoning": resp.reasoning,
                        "thinking_time": resp.thinking_time,
                        "confidence": resp.confidence,
                        "action": "狼人选择击杀目标",
                    })
            await asyncio.sleep(3)

        # 预言家行动
        seers = [pid for pid in state.alive_players
                 if state.roles.get(pid) == Role.SEER]
        if seers:
            await self._check_pause()
            seer_id = seers[0]
            if seer_id in self.adapters:
                resp = await self.adapters[seer_id].decide_night_action(self.engine, seer_id)
                if resp.action:
                    check_result = self.engine.process_seer_check(seer_id, resp.action)
                    await self.broadcast("ai_reasoning", {
                        "player_id": seer_id,
                        "player_name": self.engine.get_player(seer_id).name,
                        "reasoning": resp.reasoning,
                        "thinking_time": resp.thinking_time,
                        "confidence": resp.confidence,
                        "action": "预言家查验了目标",
                    })
            await asyncio.sleep(3)

        # 女巫行动
        witches = [pid for pid in state.alive_players
                   if state.roles.get(pid) == Role.WITCH]
        if witches:
            await self._check_pause()
            witch_id = witches[0]
            if witch_id in self.adapters:
                resp = await self.adapters[witch_id].decide_night_action(self.engine, witch_id)
                # 分析女巫的决定
                save = "救" in resp.content or "解药" in resp.content
                poison_target = resp.action if resp.action and "毒" in resp.content else None
                self.engine.process_witch_action(witch_id, save=save, poison_target=poison_target)
                await self.broadcast("ai_reasoning", {
                    "player_id": witch_id,
                    "player_name": self.engine.get_player(witch_id).name,
                    "reasoning": resp.reasoning,
                    "thinking_time": resp.thinking_time,
                    "confidence": resp.confidence,
                    "action": "女巫做出决定",
                })
            await asyncio.sleep(3)

        # 结算夜晚
        events = self.engine.resolve_night()
        for event in events:
            await self.broadcast("game_event", event.to_dict())
            if event.event_type == EventType.GAME_END:
                await self._on_game_end()
                return

        # 进入白天讨论
        await asyncio.sleep(1)
        await self._check_pause()
        await self._run_discussion()

    async def _run_discussion(self):
        """执行白天讨论"""
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

            # 广播当前发言者
            await self.broadcast("current_speaker", {
                "player_id": speaker_id,
                "player_name": player.name,
                "action": "speaking",
            })

            if player.player_type == "ai" and speaker_id in self.adapters:
                await self._check_pause()
                # AI 发言
                resp = await self.adapters[speaker_id].make_speech(self.engine, speaker_id)
                event = self.engine.process_speech(speaker_id, resp.content, resp.reasoning)
                await self.broadcast("game_event", event.to_dict())
                await self.broadcast("ai_reasoning", {
                    "player_id": speaker_id,
                    "player_name": player.name,
                    "reasoning": resp.reasoning,
                    "speech": resp.content,
                    "thinking_time": resp.thinking_time,
                    "confidence": resp.confidence,
                })
            elif player.player_type == "human":
                # 等待人类玩家发言
                await self.broadcast("wait_human_speech", {
                    "player_id": speaker_id,
                    "player_name": player.name,
                })
                await self._wait_for_human_input(speaker_id)

            await asyncio.sleep(3)

        # 发言结束，清除高亮
        await self.broadcast("current_speaker", {"player_id": None, "action": "done"})

        # 进入投票
        await self._check_pause()
        await self._run_vote()

    async def _run_vote(self):
        """执行投票阶段"""
        await self.broadcast("phase_change", {
            "phase": "day_vote",
            "day_count": self.engine.state.day_count,
            "content": f"第{self.engine.state.day_count}天，投票阶段开始。",
        })

        # AI 投票
        for pid in self.engine.state.alive_players:
            player = self.engine.get_player(pid)
            if not player:
                continue

            # 广播当前投票者
            await self.broadcast("current_speaker", {
                "player_id": pid,
                "player_name": player.name,
                "action": "voting",
            })

            if player.player_type == "ai" and pid in self.adapters:
                await self._check_pause()
                resp = await self.adapters[pid].cast_vote(self.engine, pid)
                if resp.action:
                    self.engine.process_vote(pid, resp.action)
                    await self.broadcast("game_event",
                        self.engine.state.events[-1].to_dict())
                    await self.broadcast("ai_reasoning", {
                        "player_id": pid,
                        "player_name": player.name,
                        "reasoning": resp.reasoning,
                        "thinking_time": resp.thinking_time,
                        "confidence": resp.confidence,
                        "action": "投票",
                    })
            elif player.player_type == "human":
                await self.broadcast("wait_human_vote", {
                    "player_id": pid,
                    "player_name": player.name,
                })
                await self._wait_for_human_input(pid)

            await asyncio.sleep(2)

        # 投票结束，清除高亮
        await self.broadcast("current_speaker", {"player_id": None, "action": "done"})

        # 结算投票
        await self._check_pause()
        events = self.engine.resolve_votes()
        for event in events:
            await self.broadcast("game_event", event.to_dict())
            if event.event_type == EventType.GAME_END:
                await self._on_game_end()
                return

        # 继续下一个夜晚
        await asyncio.sleep(2)
        await self._run_night()

    async def _wait_for_human_input(self, player_id: str):
        """等待人类玩家输入"""
        loop = asyncio.get_event_loop()
        self._wait_for_human = loop.create_future()
        try:
            await asyncio.wait_for(self._wait_for_human, timeout=120)
        except asyncio.TimeoutError:
            pass
        self._wait_for_human = None

    def receive_human_input(self, player_id: str, content: str, input_type: str = "speech"):
        """接收人类玩家输入"""
        if input_type == "speech":
            self.engine.process_speech(player_id, content)
        elif input_type == "vote":
            self.engine.process_vote(player_id, content)

        if self._wait_for_human and not self._wait_for_human.done():
            self._wait_for_human.set_result(True)

    async def _on_game_end(self):
        """游戏结束处理"""
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
            "winner_label": "好人阵营" if state.winner == Team.VILLAGER else "狼人阵营",
            "roles": roles_reveal,
        })

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "status": self.status,
            "players": [p.to_dict() for p in self.players],
            "player_count": len(self.players),
            "paused": self.paused,
        }
        # 添加当前游戏阶段信息
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

    def create_room(self) -> Room:
        room = Room()
        self.rooms[room.id] = room
        return room

    def get_room(self, room_id: str) -> Optional[Room]:
        return self.rooms.get(room_id)

    def list_rooms(self) -> list[dict]:
        return [r.to_dict() for r in self.rooms.values()]

    def delete_room(self, room_id: str):
        self.rooms.pop(room_id, None)
