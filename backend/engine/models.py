"""狼人杀游戏数据模型 — 支持 12 人场全角色"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Dict, List
from datetime import datetime
import uuid


# ─── 枚举定义 ───

class Team(str, Enum):
    WEREWOLF = "werewolf"
    VILLAGER = "villager"
    LOVERS = "lovers"          # 第三方阵营（丘比特情侣链）


class Role(str, Enum):
    WEREWOLF = "werewolf"
    ALPHA_WOLF = "alpha_wolf"        # 狼王：被票出局带人 + 白天自爆
    WHITE_WOLF_KING = "white_wolf_king"  # 白狼王：白天自爆带人
    SEER = "seer"
    WITCH = "witch"
    HUNTER = "hunter"
    GUARD = "guard"                  # 守卫：夜晚守人，不能连守
    IDIOT = "idiot"                  # 白痴：被票出局翻牌免死
    KNIGHT = "knight"                # 骑士：白天决斗
    CUPID = "cupid"                  # 丘比特：首夜连情侣
    VILLAGER = "villager"

    @property
    def team(self) -> Team:
        return Team.WEREWOLF if self in (Role.WEREWOLF, Role.ALPHA_WOLF, Role.WHITE_WOLF_KING) else Team.VILLAGER

    @property
    def label(self) -> str:
        labels = {
            Role.WEREWOLF: "狼人", Role.ALPHA_WOLF: "狼王",
            Role.WHITE_WOLF_KING: "白狼王", Role.SEER: "预言家",
            Role.WITCH: "女巫", Role.HUNTER: "猎人", Role.GUARD: "守卫",
            Role.IDIOT: "白痴", Role.KNIGHT: "骑士", Role.CUPID: "丘比特",
            Role.VILLAGER: "平民",
        }
        return labels[self]

    @property
    def emoji(self) -> str:
        return {
            Role.WEREWOLF: "🐺", Role.ALPHA_WOLF: "👑", Role.WHITE_WOLF_KING: "💀",
            Role.SEER: "🔮", Role.WITCH: "🧪", Role.HUNTER: "🔫", Role.GUARD: "🛡️",
            Role.IDIOT: "🤡", Role.KNIGHT: "⚔️", Role.CUPID: "💘", Role.VILLAGER: "👤",
        }[self]


class GamePhase(str, Enum):
    WAITING = "waiting"
    NIGHT = "night"
    NIGHT_RESOLVE = "night_resolve"      # 夜晚结算（死亡公告/被动技能链）
    SHOOT = "shoot"                      # 开枪窗口（猎人/狼王被票出局）
    DAY_DISCUSS = "day_discuss"
    DAY_VOTE = "day_vote"
    DAY_RESOLVE = "day_resolve"          # 票出结算（白痴翻牌/狼王带人/猎人开枪）
    GAMEOVER = "gameover"


class EventType(str, Enum):
    GAME_START = "game_start"
    PHASE_CHANGE = "phase_change"
    WEREWOLF_KILL = "werewolf_kill"
    WOLF_DISCUSS = "wolf_discuss"        # 狼人夜聊发言
    SEER_CHECK = "seer_check"
    WITCH_SAVE = "witch_save"
    WITCH_POISON = "witch_poison"
    GUARD_PROTECT = "guard_protect"      # 守卫守人
    LOVERS_CHAIN = "lovers_chain"        # 丘比特连情侣
    LOVERS_DEATH = "lovers_death"        # 殉情
    HUNTER_SHOOT = "hunter_shoot"
    ALPHA_SHOOT = "alpha_shoot"          # 狼王带人
    SELF_EXPLODE = "self_explode"        # 自爆
    IDIOT_REVEAL = "idiot_reveal"        # 白痴翻牌
    KNIGHT_DUEL = "knight_duel"          # 骑士决斗
    PLAYER_SPEECH = "player_speech"
    AI_REASONING = "ai_reasoning"
    VOTE_CAST = "vote_cast"
    VOTE_RESULT = "vote_result"
    PLAYER_DEATH = "player_death"
    GAME_END = "game_end"
    SYSTEM = "system"


# ─── 数据模型 ───

@dataclass
class AIConfig:
    provider: str = "xiaomi"
    model: str = "mimo-v2.5-pro"
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.8
    personality: str = "一个聪明、善于推理的玩家"
    max_tokens: int = 500

    def to_dict(self) -> dict:
        return {
            "provider": self.provider, "model": self.model,
            "base_url": self.base_url, "temperature": self.temperature,
            "personality": self.personality, "max_tokens": self.max_tokens,
        }


@dataclass
class Player:
    id: str
    name: str
    seat: int
    player_type: str = "ai"            # "human" | "ai"
    ai_config: Optional[AIConfig] = None
    role: Optional[Role] = None
    is_alive: bool = True

    def to_public_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "seat": self.seat,
            "player_type": self.player_type, "is_alive": self.is_alive,
        }

    def to_dict(self) -> dict:
        d = self.to_public_dict()
        d["role"] = self.role.value if self.role else None
        if self.ai_config:
            d["ai_config"] = self.ai_config.to_dict()
        return d


@dataclass
class GameEvent:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: datetime = field(default_factory=datetime.now)
    phase: GamePhase = GamePhase.WAITING
    day_count: int = 0
    event_type: EventType = EventType.SYSTEM
    player_id: Optional[str] = None
    player_name: Optional[str] = None
    target_id: Optional[str] = None
    target_name: Optional[str] = None
    content: str = ""
    reasoning: str = ""
    visible_to: Any = "all"            # "all" | list[str]
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "phase": self.phase.value,
            "day_count": self.day_count,
            "event_type": self.event_type.value,
            "player_id": self.player_id,
            "player_name": self.player_name,
            "target_id": self.target_id,
            "target_name": self.target_name,
            "content": self.content,
            "reasoning": self.reasoning,
            "visible_to": self.visible_to,
            "metadata": self.metadata,
        }


@dataclass
class GameState:
    phase: GamePhase = GamePhase.WAITING
    day_count: int = 0
    roles: dict = field(default_factory=dict)           # player_id -> Role
    alive_players: list = field(default_factory=list)
    night_actions: dict = field(default_factory=dict)   # "guard"/"wolf"/"witch_save"/"witch_poison"/"seer"
    vote_results: dict = field(default_factory=dict)    # voter_id -> target_id
    events: list = field(default_factory=list)
    witch_antidote: bool = True
    witch_poison: bool = True
    guard_last_target: Optional[str] = None             # 守卫上一晚守的人（防连守）
    lovers: list = field(default_factory=list)          # 情侣 player_id 列表（丘比特板子）
    pending_shoots: list = field(default_factory=list)  # 待开枪/带人队列: [(shooter_id, trigger)]
    pending_idiot: Optional[str] = None                 # 待翻牌的白痴
    winner: Optional[Team] = None
    winner_reason: str = ""
