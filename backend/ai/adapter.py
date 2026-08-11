"""AI 适配层 — 通过统一接口调用各种大模型"""

from __future__ import annotations
import json
import re
import time
import logging
from typing import Optional
from dataclasses import dataclass

import httpx

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.models import (
    Player, Role, GamePhase, EventType, GameEvent, AIConfig
)
from engine.game import GameEngine


logger = logging.getLogger("werewolf.ai")


# ─── Prompt 模板 ───

GAME_RULES = """标准9人狼人杀规则：
- 阵营：狼人阵营(3狼) vs 好人阵营(预言家+女巫+猎人+3平民)
- 胜利条件：好人方消灭所有狼人则好人胜；狼人数量≥好人数量则狼人胜
- 流程：夜晚→白天讨论→投票→循环
- 夜晚：狼人商量杀人、预言家查验、女巫救人/毒人
- 白天：所有人依次发言，然后投票放逐一人
"""

ROLE_PROMPTS = {
    Role.WEREWOLF: """你是狼人阵营。你的目标：
1. 隐藏狼人身份，伪装成好人
2. 白天发言时制造混乱，引导好人投错票
3. 找出预言家等神职并引导狼人夜间击杀
技巧：适度怀疑但不过激、给一个好人辩护以获取信任、引用别人发言的"漏洞"来增加可信度""",

    Role.SEER: """你是预言家。你每晚可以查验一人身份。
你的目标：
1. 找合适时机公布查验结果（跳出身份）
2. 引导好人投票淘汰狼人
3. 保护自己不被狼人发现并击杀""",

    Role.WITCH: """你是女巫。你有一瓶解药和一瓶毒药（各一次）。
你的目标：
1. 合理使用解药救人
2. 在确认狼人后使用毒药
3. 隐藏身份避免被狼人针对""",

    Role.HUNTER: """你是猎人。死亡时可以开枪带走一人。
你的目标：如果出局，带走你最怀疑的狼人。你的存在本身就是对狼人的威慑。""",

    Role.VILLAGER: """你是平民。没有特殊技能，但你的投票和推理至关重要。
你的目标：仔细分析发言逻辑、找出矛盾点、帮助神职引导局势。""",
}


@dataclass
class AIResponse:
    content: str          # 发言内容
    reasoning: str = ""   # 推理过程
    action: str = ""      # 行动目标 (player_id)
    confidence: float = 0.5
    thinking_time: float = 0.0


class AIAdapter:
    """统一 AI 调用适配器"""

    def __init__(self, config: AIConfig):
        self.config = config
        self._http = httpx.AsyncClient(timeout=60.0)

    async def _call(self, messages: list[dict], temperature: float = None) -> str:
        """统一的 API 调用 — 使用 OpenAI 兼容格式"""
        url = self.config.base_url.rstrip("/")
        # 确保 URL 以 /chat/completions 结尾
        if not url.endswith("/chat/completions"):
            url = url + "/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature or self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "response_format": {"type": "json_object"},
        }

        resp = await self._http.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        # 小米等模型会返回 reasoning_content 字段
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
        if reasoning and not content:
            # 如果只有推理没有正文，把推理当正文
            return reasoning
        if reasoning:
            # content 可能本身已经是 JSON（模型按要求输出了 JSON 格式）
            # 先尝试解析 content，如果合法 JSON 则直接返回（reasoning 作为额外信息）
            try:
                parsed_content = json.loads(content)
                # content 已经是结构化 JSON，注入 reasoning 到其中
                parsed_content["reasoning"] = reasoning
                return json.dumps(parsed_content, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                # content 不是 JSON，合并推理和正文
                return json.dumps({"reasoning": reasoning, "speech": content}, ensure_ascii=False)
        return content

    def _build_system_prompt(self, role: Role, personality: str) -> str:
        role_prompt = ROLE_PROMPTS.get(role, "")
        return f"""{GAME_RULES}

{role_prompt}

你的人设：{personality}

输出要求（严格 JSON）：
{{
  "reasoning": "你的内心推理（观众会看到，但其他玩家看不到）",
  "speech": "你要公开发言的内容（所有玩家可见）",
  "confidence": 0.0到1.0,
  "vote_target": "投票目标座位号（仅投票阶段填写，其他阶段填null）"
}}

注意：只输出 JSON，不要输出其他内容。"""

    def _build_speech_prompt(self, engine: GameEngine, player_id: str) -> str:
        """构建发言阶段提示词"""
        state = engine.state
        player = engine.get_player(player_id)
        role = state.roles.get(player_id)

        alive_names = []
        for pid in state.alive_players:
            p = engine.get_player(pid)
            alive_names.append(f"{p.seat}号({p.name})" if p else pid)

        # 今日已发言
        today_speeches = [
            e for e in state.events
            if e.event_type == EventType.PLAYER_SPEECH
            and e.day_count == state.day_count
            and e.phase == GamePhase.DAY_DISCUSS
        ]
        speeches_text = "\n".join([
            f"【{e.player_name}】：{e.content}" for e in today_speeches
        ]) or "(你是第一个发言的)"

        # 狼人队友信息
        teammates = ""
        if role == Role.WEREWOLF:
            mates = engine.get_werewolf_teammates(player_id)
            if mates:
                mate_names = [engine.get_player(m).name for m in mates if engine.get_player(m)]
                teammates = f"\n你的狼人队友：{', '.join(mate_names)}"

        # 夜间结果摘要
        night_deaths = [
            e for e in state.events
            if e.event_type == EventType.PLAYER_DEATH
            and e.day_count == state.day_count
        ]
        night_summary = "昨晚平安夜" if not night_deaths else \
            "昨晚 " + ", ".join(e.content for e in night_deaths)

        return f"""当前是第{state.day_count}天的讨论阶段。
你是 {player.seat}号 {player.name}，角色是{role.label if role else '未知'}。{teammates}

存活玩家：{', '.join(alive_names)}
{night_summary}

今天已有的发言：
{speeches_text}

请发表你的看法。严格按 JSON 格式输出。"""

    def _build_vote_prompt(self, engine: GameEngine, player_id: str) -> str:
        """构建投票阶段提示词"""
        state = engine.state
        player = engine.get_player(player_id)
        role = state.roles.get(player_id)

        today_speeches = [
            e for e in state.events
            if e.event_type == EventType.PLAYER_SPEECH
            and e.day_count == state.day_count
        ]
        speeches_text = "\n".join([
            f"【{e.player_name}】：{e.content}" for e in today_speeches
        ])

        alive_names = []
        for pid in state.alive_players:
            p = engine.get_player(pid)
            if pid != player_id:
                alive_names.append(f"{p.seat}号({p.name})" if p else pid)

        return f"""当前是第{state.day_count}天的投票阶段。
你是 {player.seat}号 {player.name}，角色是{role.label if role else '未知'}。

今天的发言回顾：
{speeches_text}

可投票的玩家（除你自己）：{', '.join(alive_names)}

请决定你要投票淘汰谁。严格按 JSON 格式输出，vote_target 填目标的座位号数字。"""

    def _build_night_prompt(self, engine: GameEngine, player_id: str) -> str:
        """构建夜间行动提示词"""
        state = engine.state
        player = engine.get_player(player_id)
        role = state.roles.get(player_id)

        alive_names = []
        for pid in state.alive_players:
            p = engine.get_player(pid)
            alive_names.append(f"{p.seat}号({p.name})" if p else pid)

        if role == Role.WEREWOLF:
            # 狼人需要选击杀目标（排除狼队友）
            mates = engine.get_werewolf_teammates(player_id)
            targets = [pid for pid in state.alive_players if pid not in mates and pid != player_id]
            target_names = [f"{engine.get_player(t).seat}号({engine.get_player(t).name})" for t in targets if engine.get_player(t)]
            return f"""现在是第{state.day_count}个夜晚。你是狼人。
可击杀目标：{', '.join(target_names)}
请选择今晚要击杀谁。严格按 JSON 格式输出，vote_target 填目标座位号数字。"""

        elif role == Role.SEER:
            targets = [pid for pid in state.alive_players if pid != player_id]
            target_names = [f"{engine.get_player(t).seat}号({engine.get_player(t).name})" for t in targets if engine.get_player(t)]
            return f"""现在是第{state.day_count}个夜晚。你是预言家。
可查验目标：{', '.join(target_names)}
请选择今晚要查验谁。严格按 JSON 格式输出，vote_target 填目标座位号数字。"""

        elif role == Role.WITCH:
            kill_target = state.night_actions.get("werewolf_kill")
            killed_name = engine.get_player(kill_target).name if kill_target and engine.get_player(kill_target) else "无人"
            prompt = f"""现在是第{state.day_count}个夜晚。你是女巫。
今晚被杀的人是：{killed_name}
你还有解药：{'是' if state.witch_antidote else '否'}
你还有毒药：{'是' if state.witch_poison else '否'}

请决定：
- 是否使用解药救人？（speech 里说明）
- 是否使用毒药？（vote_target 填要毒的人的座位号，不用毒则填 null）
严格按 JSON 格式输出。"""
            return prompt

        return f"现在是第{state.day_count}个夜晚。严格按 JSON 格式输出。"

    def _parse_response(self, raw: str) -> dict:
        """解析 AI 输出的 JSON"""
        # 尝试提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        # fallback
        return {"speech": raw, "reasoning": "", "confidence": 0.3}

    async def make_speech(self, engine: GameEngine, player_id: str) -> AIResponse:
        """白天发言"""
        start = time.time()
        role = engine.state.roles.get(player_id)
        messages = [
            {"role": "system", "content": self._build_system_prompt(role, self.config.personality)},
            {"role": "user", "content": self._build_speech_prompt(engine, player_id)},
        ]
        try:
            raw = await self._call(messages)
            parsed = self._parse_response(raw)
            return AIResponse(
                content=parsed.get("speech", raw),
                reasoning=parsed.get("reasoning", ""),
                confidence=float(parsed.get("confidence", 0.5)),
                thinking_time=round(time.time() - start, 1),
            )
        except Exception as e:
            logger.error(f"AI speech error: {e}")
            return AIResponse(
                content="[AI 暂时无法发言]",
                reasoning=f"Error: {str(e)}",
                thinking_time=round(time.time() - start, 1),
            )

    async def cast_vote(self, engine: GameEngine, player_id: str) -> AIResponse:
        """投票"""
        start = time.time()
        role = engine.state.roles.get(player_id)
        messages = [
            {"role": "system", "content": self._build_system_prompt(role, self.config.personality)},
            {"role": "user", "content": self._build_vote_prompt(engine, player_id)},
        ]
        try:
            raw = await self._call(messages)
            parsed = self._parse_response(raw)
            # 解析 vote_target — 可能是座位号
            action = self._resolve_seat_target(engine, parsed.get("vote_target"), player_id)
            return AIResponse(
                content=parsed.get("speech", ""),
                reasoning=parsed.get("reasoning", ""),
                action=action,
                confidence=float(parsed.get("confidence", 0.5)),
                thinking_time=round(time.time() - start, 1),
            )
        except Exception as e:
            logger.error(f"AI vote error: {e}")
            # 随机投一个
            alive = [p for p in engine.state.alive_players if p != player_id]
            return AIResponse(
                content="[AI 暂时无法投票]",
                reasoning=f"Error: {str(e)}",
                action=alive[0] if alive else "",
                thinking_time=round(time.time() - start, 1),
            )

    async def decide_night_action(self, engine: GameEngine, player_id: str) -> AIResponse:
        """夜间行动"""
        start = time.time()
        role = engine.state.roles.get(player_id)
        messages = [
            {"role": "system", "content": self._build_system_prompt(role, self.config.personality)},
            {"role": "user", "content": self._build_night_prompt(engine, player_id)},
        ]
        try:
            raw = await self._call(messages)
            parsed = self._parse_response(raw)
            action = self._resolve_seat_target(engine, parsed.get("vote_target"), player_id)
            return AIResponse(
                content=parsed.get("speech", ""),
                reasoning=parsed.get("reasoning", ""),
                action=action,
                confidence=float(parsed.get("confidence", 0.5)),
                thinking_time=round(time.time() - start, 1),
            )
        except Exception as e:
            logger.error(f"AI night action error: {e}")
            return AIResponse(
                content="[AI 暂时无法行动]",
                reasoning=f"Error: {str(e)}",
                thinking_time=round(time.time() - start, 1),
            )

    def _resolve_seat_target(self, engine: GameEngine, target, exclude_id: str) -> str:
        """把座位号/名字解析为 player_id"""
        if not target:
            return ""
        # 如果已经是 player_id
        if target in engine.players:
            return target
        # 尝试按座位号匹配
        try:
            seat = int(target)
            for pid in engine.state.alive_players:
                p = engine.get_player(pid)
                if p and p.seat == seat and pid != exclude_id:
                    return pid
        except (ValueError, TypeError):
            pass
        # 随机选一个（排除自己）
        alive = [p for p in engine.state.alive_players if p != exclude_id]
        return alive[0] if alive else ""

    async def close(self):
        await self._http.aclose()
