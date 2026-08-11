"""狼人杀游戏数据模型"""

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


class Role(str, Enum):
    WEREWOLF = "werewolf"
    SEER = "seer"
    WITCH = "witch"
    HUNTER = "hunter"
    VILLAGER = "villager"

    @property
    def team(self) -> Team:
        return Team.WEREWOLF if self == Role.WEREWOLF else Team.VILLAGER

    @property
    def label(self) -> str:
        labels = {
            Role.WEREWOLF: "狼人", Role.SEER: "预言家",
            Role.WITCH: "女巫", Role.HUNTER: "猎人", Role.VILLAGER: "平民",
        }
        return labels[self]

    @property
    def emoji(self) -> str:
        return {
            Role.WEREWOLF: "🐺", Role.SEER: "🔮",
            Role.WITCH: "🧪", Role.HUNTER: "🔫", Role.VILLAGER: "👤",
        }[self]


class GamePhase(str, Enum):
    WAITING = "waiting"
    NIGHT = "night"
    DAY_DISCUSS = "day_discuss"
    DAY_VOTE = "day_vote"
    GAMEOVER = "gameover"


class EventType(str, Enum):
    GAME_START = "game_start"
    PHASE_CHANGE = "phase_change"
    WEREWOLF_KILL = "werewolf_kill"
    SEER_CHECK = "seer_check"
    WITCH_SAVE = "witch_save"
    WITCH_POISON = "witch_poison"
    HUNTER_SHOOT = "hunter_shoot"
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
    provider: str = "xiaomi"           # openai / anthropic / xiaomi / deepseek ...
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
    alive_players: list = field(default_factory=list)    # alive player ids
    night_actions: dict = field(default_factory=dict)    # role -> action
    vote_results: dict = field(default_factory=dict)     # voter_id -> target_id
    events: list = field(default_factory=list)           # list[GameEvent]
    witch_antidote: bool = True
    witch_poison: bool = True
    winner: Optional[Team] = None
