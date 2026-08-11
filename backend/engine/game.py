"""狼人杀游戏引擎 — 显式状态机 + 死亡结算链 + 声明式判胜
支持 12 人场全角色（狼王/白狼王/守卫/白痴/骑士/丘比特），人数由板子配置驱动。
"""

from __future__ import annotations
import random
from collections import Counter
from typing import Optional

from .models import (
    Player, Role, Team, GamePhase, EventType, GameEvent, GameState,
)
from .boards import Board, get_board


class IllegalTransitionError(Exception):
    """非法状态转移"""


# 神职（非狼非民）
GOD_ROLES = {
    Role.SEER, Role.WITCH, Role.HUNTER, Role.GUARD,
    Role.IDIOT, Role.KNIGHT, Role.CUPID,
}

# 猎人被狼刀死不能开枪；其他死因可开枪
HUNTER_NO_SHOOT_REASONS = {"wolf_kill", "lovers"}


class GameEngine:
    """狼人杀游戏引擎（纯逻辑，零 AI 依赖）"""

    # ─── 显式状态转移表：当前状态 → 允许的下一状态 ───
    TRANSITIONS = {
        GamePhase.WAITING:       {GamePhase.NIGHT},
        GamePhase.NIGHT:         {GamePhase.NIGHT_RESOLVE},
        GamePhase.NIGHT_RESOLVE: {GamePhase.SHOOT, GamePhase.DAY_DISCUSS, GamePhase.GAMEOVER},
        GamePhase.SHOOT:         {GamePhase.DAY_DISCUSS, GamePhase.NIGHT, GamePhase.GAMEOVER},
        GamePhase.DAY_DISCUSS:   {GamePhase.DAY_VOTE, GamePhase.GAMEOVER},
        GamePhase.DAY_VOTE:      {GamePhase.DAY_RESOLVE},
        GamePhase.DAY_RESOLVE:   {GamePhase.SHOOT, GamePhase.NIGHT, GamePhase.GAMEOVER},
        GamePhase.GAMEOVER:      set(),
    }

    def __init__(self, players: list[Player], board: Board = None):
        self.players = {p.id: p for p in players}
        self.player_order = [p.id for p in sorted(players, key=lambda x: x.seat)]
        self.board = board or get_board(None)
        self.state = GameState()
        self.state.alive_players = list(self.player_order)

    # ─── 状态控制：唯一改状态的地方 ───

    def _transition(self, next_phase: GamePhase):
        allowed = self.TRANSITIONS[self.state.phase]
        if next_phase not in allowed:
            raise IllegalTransitionError(
                f"非法转移: {self.state.phase.value} → {next_phase.value}")
        self.state.phase = next_phase

    # ─── 角色分配（板子驱动） ───

    def assign_roles(self) -> dict:
        roles = list(self.board.roles)
        random.shuffle(roles)
        if len(roles) != len(self.player_order):
            raise ValueError(
                f"人数不匹配: 板子 {self.board.id} 需要 {len(roles)} 人, "
                f"实际 {len(self.player_order)} 人")
        for pid, role in zip(self.player_order, roles):
            self.players[pid].role = role
            self.state.roles[pid] = role
        return self.state.roles

    # ─── 查询辅助 ───

    def get_player(self, pid: str) -> Optional[Player]:
        return self.players.get(pid)

    def get_alive(self) -> list[str]:
        return list(self.state.alive_players)

    def alive_role(self, role: Role) -> list[str]:
        return [pid for pid in self.state.alive_players
                if self.state.roles.get(pid) == role]

    def get_alive_werewolves(self) -> list[str]:
        """存活狼人（含狼王/白狼王）"""
        return [pid for pid in self.state.alive_players
                if Role(self.state.roles[pid]).team == Team.WEREWOLF]

    def get_werewolf_teammates(self, pid: str) -> list[str]:
        if Role(self.state.roles.get(pid)) not in (Role.WEREWOLF, Role.ALPHA_WOLF, Role.WHITE_WOLF_KING):
            return []
        return [p for p in self.get_alive_werewolves() if p != pid]

    def get_alive_gods(self) -> list[str]:
        return [pid for pid in self.state.alive_players
                if self.state.roles.get(pid) in GOD_ROLES]

    def get_alive_villagers(self) -> list[str]:
        return [pid for pid in self.state.alive_players
                if self.state.roles.get(pid) == Role.VILLAGER]

    def get_alive_good(self) -> list[str]:
        return [pid for pid in self.state.alive_players
                if Role(self.state.roles[pid]).team == Team.VILLAGER]

    def emit(self, event_type: EventType, **kwargs) -> GameEvent:
        event = GameEvent(
            event_type=event_type,
            phase=self.state.phase,
            day_count=self.state.day_count,
            **kwargs,
        )
        self.state.events.append(event)
        return event

    # ─── 游戏开始 ───

    def start_game(self) -> GameEvent:
        self._transition(GamePhase.NIGHT)
        self.state.day_count = 1
        return self.emit(
            EventType.PHASE_CHANGE,
            content=f"游戏开始！板子：{self.board.name}（{len(self.players)}人局）。第1个夜晚降临…",
        )

    # ─── 夜晚行动（不改变阶段，只记录） ───

    def process_guard_protect(self, guard_id: str, target_id: str) -> GameEvent:
        """守卫守人（不能连守同一人）"""
        if self.state.guard_last_target == target_id:
            raise ValueError("守卫不能连续两晚守护同一人")
        self.state.night_actions["guard"] = target_id
        self.state.guard_last_target = target_id
        t = self.players.get(target_id)
        return self.emit(
            EventType.GUARD_PROTECT,
            player_id=guard_id, target_id=target_id,
            target_name=t.name if t else "",
            content=f"守卫守护了 {t.name if t else target_id}",
            visible_to=[guard_id],
        )

    def process_werewolf_kill(self, target_id: str) -> GameEvent:
        self.state.night_actions["wolf"] = target_id
        t = self.players.get(target_id)
        return self.emit(
            EventType.WEREWOLF_KILL,
            player_id=target_id, player_name=t.name if t else "",
            content=f"狼人选择击杀 {t.name if t else target_id}",
            visible_to=self.get_alive_werewolves(),
        )

    def process_witch_action(self, witch_id: str, save: bool = False,
                             poison_target: str = None) -> list:
        """女巫救/毒（各限一次）"""
        events = []
        if save and self.state.witch_antidote:
            self.state.night_actions["witch_save"] = True
            self.state.witch_antidote = False
            events.append(self.emit(
                EventType.WITCH_SAVE, player_id=witch_id,
                content="女巫使用了解药",
                visible_to=[witch_id],
            ))
        if poison_target and self.state.witch_poison:
            self.state.night_actions["witch_poison"] = poison_target
            self.state.witch_poison = False
            t = self.players.get(poison_target)
            events.append(self.emit(
                EventType.WITCH_POISON, player_id=witch_id,
                target_id=poison_target,
                target_name=t.name if t else "",
                content=f"女巫毒杀 {t.name if t else poison_target}",
                visible_to=[witch_id],
            ))
        return events

    def process_seer_check(self, seer_id: str, target_id: str) -> GameEvent:
        t = self.players.get(target_id)
        is_wolf = Role(self.state.roles[target_id]).team == Team.WEREWOLF
        self.state.night_actions["seer"] = target_id
        return self.emit(
            EventType.SEER_CHECK,
            player_id=seer_id, target_id=target_id,
            target_name=t.name if t else "",
            content=f"查验结果：{t.name if t else target_id} 是{'狼人' if is_wolf else '好人'}",
            visible_to=[seer_id],
            metadata={"is_werewolf": is_wolf},
        )

    def process_cupid_chain(self, cupid_id: str, a_id: str, b_id: str) -> GameEvent:
        """丘比特首夜连情侣（两人不能是自己/同人）"""
        if a_id == b_id or cupid_id in (a_id, b_id):
            raise ValueError("情侣必须是不含丘比特本人的两名不同玩家")
        self.state.lovers = [a_id, b_id]
        names = [self.players[p].name for p in (a_id, b_id)]
        return self.emit(
            EventType.LOVERS_CHAIN, player_id=cupid_id,
            content=f"丘比特连成了情侣：{' ❤️ '.join(names)}",
            visible_to=[cupid_id, a_id, b_id],
            metadata={"lovers": [a_id, b_id]},
        )

    # ─── 夜晚结算（死亡结算链核心） ───

    def resolve_night(self) -> list:
        """结算夜晚：守/救/毒/刀 → 死亡链 → 判胜 → 转移"""
        self._transition(GamePhase.NIGHT_RESOLVE)
        events = []
        actions = self.state.night_actions
        guarded = actions.get("guard")
        wolf_target = actions.get("wolf")
        saved = actions.get("witch_save", False)
        poisoned = actions.get("witch_poison")

        deaths = []  # (pid, reason)
        # 狼刀：被守或被救不死；同守同救必死
        if wolf_target:
            protected = wolf_target == guarded or saved
            same_guard_save = wolf_target == guarded and saved
            if not protected or same_guard_save:
                deaths.append((wolf_target, "wolf_kill"))
        if poisoned:
            deaths.append((poisoned, "poison"))

        events += self._apply_deaths(deaths)

        if not deaths:
            events.append(self.emit(
                EventType.SYSTEM, content="昨晚是平安夜"))

        events += self._after_night_resolve()
        return events

    def _apply_deaths(self, deaths: list) -> list:
        """死亡结算链：死亡 → 殉情/开枪/带人入队 → 下一环"""
        events = []
        queue = list(deaths)
        while queue:
            pid, reason = queue.pop(0)
            if pid not in self.state.alive_players:
                continue
            self.state.alive_players.remove(pid)
            p = self.players.get(pid)
            role = Role(self.state.roles[pid])
            events.append(self.emit(
                EventType.PLAYER_DEATH,
                player_id=pid, player_name=p.name if p else "",
                content=f"{p.name if p else pid} ({role.label})死亡",
                metadata={"role": role.value, "reason": reason},
            ))

            # 猎人开枪（狼刀/殉情死不能开）
            if role == Role.HUNTER and reason not in HUNTER_NO_SHOOT_REASONS:
                self.state.pending_shoots.append((pid, "hunter"))
            # 狼王被票出局带人
            if role == Role.ALPHA_WOLF and reason == "vote":
                self.state.pending_shoots.append((pid, "alpha"))

            # 情侣殉情（殉情不再触发猎人/狼王，防连锁）
            if self.board.has_lovers and pid in self.state.lovers:
                other = [x for x in self.state.lovers if x != pid]
                if other and other[0] in self.state.alive_players:
                    self.state.alive_players.remove(other[0])
                    o = self.players.get(other[0])
                    events.append(self.emit(
                        EventType.LOVERS_DEATH,
                        player_id=other[0], player_name=o.name if o else "",
                        content=f"{o.name if o else other[0]} 因情侣殉情而死亡 💔",
                        metadata={"reason": "lovers"},
                    ))
        return events

    def _after_night_resolve(self) -> list:
        """夜晚结算后：判胜 / 开枪窗口 / 进入白天"""
        events = []
        winner = self.check_winner()
        if winner:
            events += self.end_game(winner)
            return events
        if self.state.pending_shoots:
            self._transition(GamePhase.SHOOT)
            events.append(self.emit(
                EventType.PHASE_CHANGE,
                content="有人可以开枪/带人…",
            ))
        else:
            self._open_day(events)
        return events

    def process_shoot(self, shooter_id: str, target_id: str = None) -> list:
        """处理开枪/带人队列（猎人/狼王），target=None 表示放弃"""
        events = []
        if not self.state.pending_shoots:
            return events
        shooter, kind = self.state.pending_shoots.pop(0)
        if shooter != shooter_id:
            raise ValueError("不是待行动的玩家")
        if target_id:
            events += self._apply_deaths([(target_id, "shoot")])
            s = self.players.get(shooter)
            t = self.players.get(target_id)
            etype = EventType.HUNTER_SHOOT if kind == "hunter" else EventType.ALPHA_SHOOT
            events.append(self.emit(
                etype, player_id=shooter,
                content=f"{s.name if s else shooter} {'开枪带走了' if kind=='hunter' else '发动技能带走了'} {t.name if t else target_id}",
            ))
        else:
            events.append(self.emit(
                EventType.SYSTEM,
                content=f"{self.players[shooter].name} 放弃了技能",
            ))

        winner = self.check_winner()
        if winner:
            events += self.end_game(winner)
            return events
        # 还有待开枪的继续留在 SHOOT，否则进入下一阶段
        if not self.state.pending_shoots:
            if self.state.phase == GamePhase.SHOOT:
                if self.state.day_count == 0 or self._just_voted():
                    self._open_day(events)
                else:
                    self._open_night(events)
        return events

    def _just_voted(self) -> bool:
        return getattr(self.state, "_after_vote", False)

    def _open_day(self, events: list):
        self._transition(GamePhase.DAY_DISCUSS)
        events.append(self.emit(
            EventType.PHASE_CHANGE,
            content=f"天亮了，第{self.state.day_count}天。剩余 {len(self.state.alive_players)} 人。",
        ))

    def _open_night(self, events: list):
        self._transition(GamePhase.NIGHT)
        self.state.night_actions.clear()
        self.state.day_count += 1
        events.append(self.emit(
            EventType.PHASE_CHANGE,
            content=f"进入第{self.state.day_count}个夜晚。所有人闭眼。",
        ))

    # ─── 白天阶段 ───

    def process_speech(self, player_id: str, content: str, reasoning: str = "") -> GameEvent:
        p = self.players.get(player_id)
        return self.emit(
            EventType.PLAYER_SPEECH,
            player_id=player_id, player_name=p.name if p else "",
            content=content, reasoning=reasoning,
        )

    def process_self_explode(self, player_id: str, target_id: str = None) -> list:
        """狼王/白狼王白天自爆带人（讨论阶段）"""
        events = []
        role = Role(self.state.roles[player_id])
        if role not in (Role.ALPHA_WOLF, Role.WHITE_WOLF_KING):
            raise ValueError("只有狼王/白狼王能自爆")
        p = self.players.get(player_id)
        events.append(self.emit(
            EventType.SELF_EXPLODE, player_id=player_id,
            content=f"{p.name if p else player_id}（{role.label}）自爆了！",
        ))
        events += self._apply_deaths([(player_id, "self_explode")])
        if target_id:
            events += self._apply_deaths([(target_id, "shoot")])
            t = self.players.get(target_id)
            events.append(self.emit(
                EventType.ALPHA_SHOOT, player_id=player_id,
                content=f"自爆带走了 {t.name if t else target_id}",
            ))
        winner = self.check_winner()
        if winner:
            events += self.end_game(winner)
        return events

    def process_knight_duel(self, knight_id: str, target_id: str) -> list:
        """骑士白天决斗：目标是狼 → 狼死；不是狼 → 骑士死"""
        events = []
        is_wolf = Role(self.state.roles[target_id]).team == Team.WEREWOLF
        events.append(self.emit(
            EventType.KNIGHT_DUEL, player_id=knight_id,
            content=f"骑士向 {self.players[target_id].name} 发起决斗！",
            metadata={"target_is_wolf": is_wolf},
        ))
        events += self._apply_deaths([(target_id if is_wolf else knight_id, "duel")])
        winner = self.check_winner()
        if winner:
            events += self.end_game(winner)
        return events

    def process_vote(self, voter_id: str, target_id: str) -> GameEvent:
        self.state.vote_results[voter_id] = target_id
        p = self.players.get(voter_id)
        t = self.players.get(target_id)
        return self.emit(
            EventType.VOTE_CAST,
            player_id=voter_id, player_name=p.name if p else "",
            target_id=target_id, target_name=t.name if t else "",
            content=f"{p.name if p else voter_id} 投票给 {t.name if t else target_id}",
        )

    def resolve_votes(self) -> list:
        """结算投票：票出 → 白痴翻牌 / 狼王带人 / 猎人开枪 → 判胜 → 进入夜晚"""
        self._transition(GamePhase.DAY_RESOLVE)
        events = []
        if not self.state.vote_results:
            events.append(self.emit(EventType.SYSTEM, content="无人投票"))
            return events

        counts = Counter(self.state.vote_results.values())
        max_votes = max(counts.values())
        top = [pid for pid, c in counts.items() if c == max_votes]

        detail = []
        for target, c in counts.most_common():
            voters = [v for v, t in self.state.vote_results.items() if t == target]
            detail.append(f"{self.players[target].name}({c}票:{','.join(self.players[v].name for v in voters)})")

        if len(top) > 1:
            events.append(self.emit(
                EventType.VOTE_RESULT,
                content=f"投票结果：{'；'.join(detail)}。平票，无人出局。",
                metadata={"tie": True},
            ))
            self.state.vote_results.clear()
        else:
            eliminated = top[0]
            role = Role(self.state.roles[eliminated])
            events.append(self.emit(
                EventType.VOTE_RESULT, player_id=eliminated,
                content=f"投票结果：{'；'.join(detail)}。{self.players[eliminated].name} 以 {max_votes} 票被放逐。",
                metadata={"eliminated": eliminated},
            ))

            # 白痴被票出 → 翻牌免死
            if role == Role.IDIOT and eliminated in self.state.alive_players:
                self.state.pending_idiot = eliminated
                events.append(self.emit(
                    EventType.IDIOT_REVEAL, player_id=eliminated,
                    content=f"{self.players[eliminated].name}（白痴）翻牌免死！之后失去投票权。",
                ))
            else:
                events += self._apply_deaths([(eliminated, "vote")])
            self.state.vote_results.clear()

        self.state._after_vote = True
        winner = self.check_winner()
        if winner:
            events += self.end_game(winner)
            return events
        if self.state.pending_shoots:
            self._transition(GamePhase.SHOOT)
            events.append(self.emit(
                EventType.PHASE_CHANGE, content="有玩家可以开枪/带人…"))
        else:
            self._open_night(events)
            self.state._after_vote = False
        return events

    # ─── 胜负判定（声明式，优先级：情侣 > 狼 > 好人） ───

    def check_winner(self) -> Optional[Team]:
        wolves = len(self.get_alive_werewolves())
        good = len(self.get_alive_good())

        # 情侣阵营（丘比特板子 + 情侣存活且不同阵营）
        if self.board.has_lovers and len(self.state.lovers) == 2:
            lovers = [p for p in self.state.lovers if p in self.state.alive_players]
            if len(lovers) == 2:
                teams = {Role(self.state.roles[p]).team for p in lovers}
                if teams == {Team.WEREWOLF, Team.VILLAGER}:
                    others = len(self.state.alive_players) - 2
                    if others == 0:
                        self.state.winner_reason = "情侣存活到最后"
                        return Team.LOVERS
                    # 狼全灭且只剩情侣+好人？简化：狼全灭后好人方因情侣存在而无法获胜，
                    # 情侣与好人共存时好人胜（经典：情侣死亡前好人不能赢）

        # 狼胜
        if wolves == 0:
            self.state.winner_reason = "狼人全灭"
            return Team.VILLAGER
        if wolves >= good:
            self.state.winner_reason = f"狼人({wolves}) ≥ 好人({good})"
            return Team.WEREWOLF
        # 屠边：神全灭或民全灭（win_mode=kill_side）
        if self.board.win_mode == "kill_side":
            if not self.get_alive_gods():
                self.state.winner_reason = "神职全灭"
                return Team.WEREWOLF
            if not self.get_alive_villagers():
                self.state.winner_reason = "平民全灭"
                return Team.WEREWOLF
        return None

    def end_game(self, winner: Team) -> list:
        self._transition(GamePhase.GAMEOVER)
        self.state.winner = winner
        roles_reveal = {pid: self.state.roles[pid].value for pid in self.player_order}
        return [self.emit(
            EventType.GAME_END,
            content=f"游戏结束！{'❤️情侣阵营' if winner == Team.LOVERS else '好人阵营' if winner == Team.VILLAGER else '狼人阵营'}获胜！({self.state.winner_reason})",
            metadata={"winner": winner.value, "roles": roles_reveal},
        )]

    # ─── 可见状态投影（信息隔离） ───

    def get_visible_state(self, player_id: str = None) -> dict:
        roles_visible = {}
        if player_id:
            my_role = self.state.roles.get(player_id)
            if my_role and Role(my_role).team == Team.WEREWOLF:
                for pid in self.get_alive_werewolves():
                    roles_visible[pid] = "werewolf"
            if my_role:
                roles_visible[player_id] = my_role.value
            if self.state.lovers and player_id in self.state.lovers:
                for pid in self.state.lovers:
                    roles_visible[pid] = self.state.roles.get(pid)
        return {
            "phase": self.state.phase.value,
            "day_count": self.state.day_count,
            "alive_players": [self.players[pid].to_public_dict() for pid in self.state.alive_players],
            "all_players": [p.to_public_dict() for p in self.players.values()],
            "my_role": self.state.roles.get(player_id),
            "my_id": player_id,
            "roles_visible": roles_visible,
            "lovers": self.state.lovers if (player_id in self.state.lovers
                                            or self.state.roles.get(player_id) == Role.CUPID) else [],
            "witch_antidote": self.state.witch_antidote,
            "witch_poison": self.state.witch_poison,
            "winner": self.state.winner.value if self.state.winner else None,
            "winner_reason": self.state.winner_reason,
        }

    def get_speaker_order(self) -> list[str]:
        alive = list(self.state.alive_players)
        random.shuffle(alive)
        return alive
