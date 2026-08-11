"""狼人杀游戏引擎 — 纯逻辑，状态机"""

from __future__ import annotations
import random
from typing import Optional
from .models import (
    Player, Role, Team, GamePhase, EventType, GameEvent, GameState
)


# 标准 9 人局角色分配
STANDARD_ROLES = [
    Role.WEREWOLF, Role.WEREWOLF, Role.WEREWOLF,
    Role.SEER, Role.WITCH, Role.HUNTER,
    Role.VILLAGER, Role.VILLAGER, Role.VILLAGER,
]


class GameEngine:
    """狼人杀游戏引擎"""

    def __init__(self, players: list[Player]):
        self.players = {p.id: p for p in players}
        self.player_order = [p.id for p in sorted(players, key=lambda x: x.seat)]
        self.state = GameState()
        self.state.alive_players = list(self.player_order)

    def assign_roles(self, role_list: list[Role] = None) -> dict[str, Role]:
        """随机分配角色"""
        roles = list(role_list or STANDARD_ROLES)
        if len(roles) < len(self.players):
            # 如果角色不够，用平民补齐
            roles += [Role.VILLAGER] * (len(self.players) - len(roles))
        random.shuffle(roles)

        for pid, role in zip(self.player_order, roles):
            self.players[pid].role = role
            self.state.roles[pid] = role
        return self.state.roles

    def get_player(self, pid: str) -> Optional[Player]:
        return self.players.get(pid)

    def get_alive_werewolves(self) -> list[str]:
        return [pid for pid in self.state.alive_players
                if self.state.roles.get(pid) == Role.WEREWOLF]

    def get_alive_villagers(self) -> list[str]:
        return [pid for pid in self.state.alive_players
                if self.state.roles.get(pid) != Role.WEREWOLF]

    def get_werewolf_teammates(self, pid: str) -> list[str]:
        """获取狼人队友（排除自己）"""
        if self.state.roles.get(pid) != Role.WEREWOLF:
            return []
        return [p for p in self.get_alive_werewolves() if p != pid]

    def emit(self, event_type: EventType, **kwargs) -> GameEvent:
        """创建并记录事件"""
        event = GameEvent(
            event_type=event_type,
            phase=self.state.phase,
            day_count=self.state.day_count,
            **kwargs,
        )
        self.state.events.append(event)
        return event

    # ─── 夜间阶段 ───

    def start_night(self) -> GameEvent:
        """进入夜晚"""
        self.state.phase = GamePhase.NIGHT
        self.state.night_actions.clear()
        self.state.day_count += 1
        return self.emit(
            EventType.PHASE_CHANGE,
            content=f"第{self.state.day_count}个夜晚降临了…所有人闭眼。",
        )

    def process_werewolf_kill(self, target_id: str) -> GameEvent:
        """狼人选择击杀目标"""
        self.state.night_actions["werewolf_kill"] = target_id
        target = self.players.get(target_id)
        return self.emit(
            EventType.WEREWOLF_KILL,
            player_id=target_id,
            player_name=target.name if target else "",
            content=f"狼人选择击杀 {target.name if target else target_id}",
            visible_to=self.get_alive_werewolves(),
        )

    def process_seer_check(self, seer_id: str, target_id: str) -> GameEvent:
        """预言家查验"""
        target = self.players.get(target_id)
        role = self.state.roles.get(target_id)
        is_wolf = role == Role.WEREWOLF
        self.state.night_actions["seer_check"] = {"seer": seer_id, "target": target_id}
        return self.emit(
            EventType.SEER_CHECK,
            player_id=seer_id,
            target_id=target_id,
            target_name=target.name if target else "",
            content=f"查验结果：{target.name if target else target_id} 是{'狼人' if is_wolf else '好人'}",
            visible_to=[seer_id],
            metadata={"is_werewolf": is_wolf},
        )

    def process_witch_action(self, witch_id: str, save: bool = False, poison_target: str = None) -> list[GameEvent]:
        """女巫操作（救人/毒人）"""
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
            target = self.players.get(poison_target)
            events.append(self.emit(
                EventType.WITCH_POISON, player_id=witch_id,
                target_id=poison_target,
                target_name=target.name if target else "",
                content=f"女巫使用了毒药，毒杀 {target.name if target else poison_target}",
                visible_to=[witch_id],
            ))
        return events

    def resolve_night(self) -> list[GameEvent]:
        """结算夜晚"""
        events = []
        deaths = []

        kill_target = self.state.night_actions.get("werewolf_kill")
        saved = self.state.night_actions.get("witch_save", False)
        poisoned = self.state.night_actions.get("witch_poison")

        # 狼人杀人（未被救）
        if kill_target and not saved:
            deaths.append((kill_target, "被狼人击杀"))

        # 女巫毒人
        if poisoned:
            deaths.append((poisoned, "被女巫毒杀"))

        # 执行死亡
        for pid, reason in deaths:
            if pid in self.state.alive_players:
                self.state.alive_players.remove(pid)
                p = self.players.get(pid)
                role = self.state.roles.get(pid)
                name = p.name if p else pid
                role_label = role.label if role else "?"
                evt = self.emit(
                    EventType.PLAYER_DEATH,
                    player_id=pid,
                    player_name=name,
                    content=f"{name} ({role_label}){reason}",
                    metadata={"role": role.value if role else None, "reason": reason},
                )
                events.append(evt)

                # 猎人死后开枪（这里简化为自动选择：不自动开枪，留给人/AI决策）
                if role == Role.HUNTER:
                    events.append(self.emit(
                        EventType.HUNTER_SHOOT,
                        player_id=pid,
                        player_name=p.name if p else "",
                        content=f"{p.name if p else pid} 是猎人，可以开枪！",
                        metadata={"hunter_can_shoot": True},
                    ))

        if not deaths:
            events.append(self.emit(
                EventType.SYSTEM, content="昨晚是平安夜",
            ))

        # 检查胜负
        winner = self.check_winner()
        if winner:
            events += self.end_game(winner)
            return events

        # 进入白天讨论
        self.state.phase = GamePhase.DAY_DISCUSS
        events.append(self.emit(
            EventType.PHASE_CHANGE,
            content=f"天亮了，第{self.state.day_count}天。剩余 {len(self.state.alive_players)} 人。",
        ))
        return events

    # ─── 白天阶段 ───

    def process_speech(self, player_id: str, content: str, reasoning: str = "") -> GameEvent:
        """玩家发言"""
        p = self.players.get(player_id)
        return self.emit(
            EventType.PLAYER_SPEECH,
            player_id=player_id,
            player_name=p.name if p else "",
            content=content,
            reasoning=reasoning,
        )

    def process_vote(self, voter_id: str, target_id: str) -> GameEvent:
        """玩家投票"""
        self.state.vote_results[voter_id] = target_id
        p = self.players.get(voter_id)
        t = self.players.get(target_id)
        return self.emit(
            EventType.VOTE_CAST,
            player_id=voter_id,
            player_name=p.name if p else "",
            target_id=target_id,
            target_name=t.name if t else "",
            content=f"{p.name if p else voter_id} 投票给 {t.name if t else target_id}",
        )

    def resolve_votes(self) -> list[GameEvent]:
        """结算投票"""
        events = []
        if not self.state.vote_results:
            return events

        from collections import Counter
        vote_counts = Counter(self.state.vote_results.values())
        max_votes = max(vote_counts.values())
        top_voted = [pid for pid, count in vote_counts.items() if count == max_votes]

        # 投票详情
        detail_parts = []
        for target, count in vote_counts.most_common():
            t = self.players.get(target)
            voters = [vid for vid, vtarget in self.state.vote_results.items() if vtarget == target]
            voter_names = [self.players[v].name for v in voters if v in self.players]
            detail_parts.append(f"{t.name if t else target}({count}票): {', '.join(voter_names)}")

        if len(top_voted) == 1:
            eliminated = top_voted[0]
            self.state.alive_players.remove(eliminated)
            p = self.players.get(eliminated)
            role = self.state.roles.get(eliminated)
            events.append(self.emit(
                EventType.VOTE_RESULT,
                player_id=eliminated,
                player_name=p.name if p else "",
                content=f"投票结果：{'; '.join(detail_parts)}。{p.name if p else eliminated} 以 {max_votes} 票出局。",
                metadata={"eliminated": eliminated, "votes": dict(vote_counts)},
            ))
            events.append(self.emit(
                EventType.PLAYER_DEATH,
                player_id=eliminated,
                player_name=p.name if p else "",
                content=f"{p.name if p else eliminated} ({role.label if role else '?'}) 被投票出局",
                metadata={"role": role.value if role else None, "reason": "vote"},
            ))
            # 猎人被票出局可以开枪
            if role == Role.HUNTER:
                events.append(self.emit(
                    EventType.HUNTER_SHOOT,
                    player_id=eliminated,
                    player_name=p.name if p else "",
                    content=f"{p.name if p else eliminated} 是猎人，可以开枪！",
                    metadata={"hunter_can_shoot": True},
                ))
        else:
            names = [self.players[pid].name for pid in top_voted if pid in self.players]
            events.append(self.emit(
                EventType.VOTE_RESULT,
                content=f"投票结果：{'; '.join(detail_parts)}。{', '.join(names)} 票数相同，无人出局。",
                metadata={"votes": dict(vote_counts), "tie": True},
            ))

        self.state.vote_results.clear()

        # 检查胜负
        winner = self.check_winner()
        if winner:
            events += self.end_game(winner)
            return events

        # 进入夜晚
        self.state.phase = GamePhase.NIGHT
        self.state.day_count += 1
        events.append(self.emit(
            EventType.PHASE_CHANGE,
            content=f"进入第{self.state.day_count}个夜晚。所有人闭眼。",
        ))
        return events

    # ─── 胜负判定 ───

    def check_winner(self) -> Optional[Team]:
        wolves = len(self.get_alive_werewolves())
        villagers = len(self.get_alive_villagers())
        if wolves == 0:
            return Team.VILLAGER
        if wolves >= villagers:
            return Team.WEREWOLF
        return None

    def end_game(self, winner: Team) -> list[GameEvent]:
        """游戏结束"""
        self.state.phase = GamePhase.GAMEOVER
        self.state.winner = winner
        # 公布所有角色
        roles_reveal = {
            pid: self.state.roles[pid].value
            for pid in self.player_order
        }
        return [self.emit(
            EventType.GAME_END,
            content=f"游戏结束！{'好人阵营' if winner == Team.VILLAGER else '狼人阵营'}获胜！",
            metadata={"winner": winner.value, "roles": roles_reveal},
        )]

    # ─── 辅助 ───

    def get_visible_state(self, player_id: str = None) -> dict:
        """获取对特定玩家可见的游戏状态"""
        roles_visible = {}
        my_role = self.state.roles.get(player_id)
        if my_role == Role.WEREWOLF:
            # 狼人可以看到所有狼人队友
            for pid in self.get_alive_werewolves():
                roles_visible[pid] = Role.WEREWOLF.value
        if my_role:
            roles_visible[player_id] = my_role.value

        return {
            "phase": self.state.phase.value,
            "day_count": self.state.day_count,
            "alive_players": [
                self.players[pid].to_public_dict()
                for pid in self.state.alive_players
            ],
            "all_players": [p.to_public_dict() for p in self.players.values()],
            "my_role": my_role.value if my_role else None,
            "my_id": player_id,
            "roles_visible": roles_visible,
            "winner": self.state.winner.value if self.state.winner else None,
            "witch_antidote": self.state.witch_antidote,
            "witch_poison": self.state.witch_poison,
        }

    def get_speaker_order(self) -> list[str]:
        """获取当前存活玩家的发言顺序（随机）"""
        alive = list(self.state.alive_players)
        random.shuffle(alive)
        return alive
