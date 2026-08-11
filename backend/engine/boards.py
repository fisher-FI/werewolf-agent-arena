"""板子配置 — 12 人场 5 种经典板子，人数由角色池推导，零硬编码"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from .models import Role


@dataclass
class Board:
    id: str
    name: str
    desc: str
    roles: list                          # 角色池（长度即人数）
    night_order: list                     # 夜晚行动顺序（技能名）
    has_lovers: bool = False              # 是否有丘比特第三方
    win_mode: str = "kill_side"           # kill_side 屠边 / kill_city 屠城
    first_night_cupid: bool = False       # 首夜丘比特连人

    @property
    def player_count(self) -> int:
        return len(self.roles)

    @property
    def role_counts(self) -> dict:
        from collections import Counter
        return dict(Counter(self.roles))


def _wolves(n: int) -> list:
    return [Role.WEREWOLF] * n


def _villagers(n: int) -> list:
    return [Role.VILLAGER] * n


BOARDS: dict[str, Board] = {
    "ywls": Board(
        id="ywls", name="预女猎守", desc="4狼+预女猎守+4民 · 最经典",
        roles=_wolves(4) + [Role.SEER, Role.WITCH, Role.HUNTER, Role.GUARD] + _villagers(4),
        night_order=["guard", "wolf", "witch", "seer"],
    ),
    "ywlb": Board(
        id="ywlb", name="预女猎白", desc="4狼+预女猎+白痴+4民",
        roles=_wolves(4) + [Role.SEER, Role.WITCH, Role.HUNTER, Role.IDIOT] + _villagers(4),
        night_order=["wolf", "witch", "seer"],
    ),
    "lwsh": Board(
        id="lwsh", name="狼王守卫", desc="3狼+狼王+预女猎守+4民",
        roles=_wolves(3) + [Role.ALPHA_WOLF, Role.SEER, Role.WITCH, Role.HUNTER, Role.GUARD] + _villagers(4),
        night_order=["guard", "wolf", "witch", "seer"],
    ),
    "bwlqs": Board(
        id="bwlqs", name="白狼王骑士", desc="3狼+白狼王+预女猎+骑士+4民",
        roles=_wolves(3) + [Role.WHITE_WOLF_KING, Role.SEER, Role.WITCH, Role.HUNTER, Role.KNIGHT] + _villagers(4),
        night_order=["wolf", "witch", "seer"],
    ),
    "cupid": Board(
        id="cupid", name="丘比特", desc="4狼+预女猎+丘比特+4民 · 第三方阵营",
        roles=_wolves(4) + [Role.SEER, Role.WITCH, Role.HUNTER, Role.CUPID] + _villagers(4),
        night_order=["cupid", "wolf", "witch", "seer"],
        has_lovers=True, first_night_cupid=True,
    ),
}

DEFAULT_BOARD = "ywls"


def get_board(board_id: Optional[str]) -> Board:
    return BOARDS.get(board_id or DEFAULT_BOARD, BOARDS[DEFAULT_BOARD])
