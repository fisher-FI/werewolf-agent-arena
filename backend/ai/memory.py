"""玩家记忆 — 每玩家全量上下文（不截断，1M 上下文窗口内直接用）"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class PlayerMemory:
    """单个玩家的完整游戏记忆"""
    player_id: str
    own_speeches: list = field(default_factory=list)      # 自己每次发言 (day, content)
    own_reasonings: list = field(default_factory=list)    # 自己每次推理 (day, phase, reasoning)
    own_actions: list = field(default_factory=list)       # 自己的行动 (day, phase, action_desc)
    heard_speeches: list = field(default_factory=list)    # 听到的所有发言 (day, speaker_name, content)
    private_info: list = field(default_factory=list)      # 私密信息（验人/刀人/队友/情侣/药水）
    night_results: list = field(default_factory=list)     # 每晚结果 (day, content)
    vote_history: list = field(default_factory=list)      # 自己投过谁 (day, target_name)

    def record_own_speech(self, day: int, content: str):
        self.own_speeches.append((day, content))

    def record_reasoning(self, day: int, phase: str, reasoning: str):
        if reasoning:
            self.own_reasonings.append((day, phase, reasoning))

    def record_action(self, day: int, phase: str, desc: str):
        self.own_actions.append((day, phase, desc))

    def record_heard(self, day: int, speaker: str, content: str):
        self.heard_speeches.append((day, speaker, content))

    def record_private(self, day: int, info: str):
        self.private_info.append((day, info))

    def record_night(self, day: int, content: str):
        self.night_results.append((day, content))

    def record_vote(self, day: int, target: str):
        self.vote_history.append((day, target))

    def render(self) -> str:
        """渲染为注入 prompt 的完整上下文（全量，不截断）"""
        lines = []

        if self.private_info:
            lines.append("【你掌握的私密信息】")
            for day, info in self.private_info:
                lines.append(f"第{day}天: {info}")

        if self.night_results:
            lines.append("【每晚发生的事】")
            for day, content in self.night_results:
                lines.append(f"第{day}天: {content}")

        if self.own_speeches:
            lines.append("【你历次公开发言】")
            for day, content in self.own_speeches:
                lines.append(f"第{day}天: {content}")

        if self.vote_history:
            lines.append("【你历次投票】")
            for day, target in self.vote_history:
                lines.append(f"第{day}天: 投给了 {target}")

        if self.own_actions:
            lines.append("【你的行动记录】")
            for day, phase, desc in self.own_actions:
                lines.append(f"第{day}天({phase}): {desc}")

        if self.heard_speeches:
            lines.append("【你听到的所有发言（按时间顺序）】")
            for day, speaker, content in self.heard_speeches:
                lines.append(f"第{day}天 {speaker}: {content}")

        if not lines:
            return "（游戏刚开始，你还没有任何记忆）"
        return "\n".join(lines)


class MemoryManager:
    """所有玩家的记忆管理"""

    def __init__(self):
        self.memories: dict[str, PlayerMemory] = {}

    def get(self, player_id: str) -> PlayerMemory:
        if player_id not in self.memories:
            self.memories[player_id] = PlayerMemory(player_id=player_id)
        return self.memories[player_id]

    def render_for(self, player_id: str) -> str:
        return self.get(player_id).render()
