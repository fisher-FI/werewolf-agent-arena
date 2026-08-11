"""AI 适配层 — 通过统一接口调用各种大模型（支持全角色 prompt）"""

from __future__ import annotations
import json
import re
import time
import logging
from typing import Optional
from dataclasses import dataclass, field

import httpx

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from engine.models import (
    Player, Role, GamePhase, EventType, GameEvent, AIConfig, Team,
)
from engine.game import GameEngine

logger = logging.getLogger("werewolf.ai")


# ─── Prompt 模板 ───

GAME_RULES = """标准12人狼人杀规则：
- 阵营：狼人阵营 vs 好人阵营（神职+平民），丘比特板子可能有情侣第三方
- 胜利条件：好人方消灭所有狼人则好人胜；狼人数量≥好人数、或神职全灭、或平民全灭则狼人胜
- 流程：夜晚→白天讨论→投票→循环
- 夜晚行动顺序（按板子）：守卫守人→狼人杀人→女巫救人/毒人→预言家查验→(首夜)丘比特连情侣
- 白天：所有人依次发言，然后投票放逐一人
- 特殊规则：猎人被狼刀死不能开枪；同守同救必死；守卫不能连守同一人；白痴被票出翻牌免死；情侣殉情"""

ROLE_PROMPTS = {
    Role.WEREWOLF: """你是狼人阵营。你的目标：
1. 隐藏狼人身份，伪装成好人
2. 白天发言时制造混乱，引导好人投错票
3. 找出预言家等神职并引导狼人夜间击杀
技巧：适度怀疑但不过激、给一个好人辩护以获取信任、引用别人发言的"漏洞"来增加可信度""",

    Role.ALPHA_WOLF: """你是狼王（狼人阵营）。除了普通狼人的能力，你被投票放逐时可以带走一名玩家。
你的目标：
1. 隐藏身份，伪装成好人
2. 白天发言制造混乱，引导好人投错票
3. 若被放逐，带走最有价值的神职（预言家/女巫）""",

    Role.WHITE_WOLF_KING: """你是白狼王（狼人阵营）。你可以在白天自爆，自爆时带走一名玩家。
你的目标：
1. 隐藏身份，伪装成好人
2. 关键时刻自爆带走预言家/女巫等关键神职
3. 判断自爆时机：局势对狼人不利、或确认了神职身份时""",

    Role.SEER: """你是预言家。你每晚可以查验一人身份。
你的目标：
1. 找合适时机公布查验结果（跳出身份）
2. 引导好人投票淘汰狼人
3. 保护自己不被狼人发现并击杀""",

    Role.WITCH: """你是女巫。你有一瓶解药和一瓶毒药（各一次）。
你的目标：
1. 第一晚通常救人（除非被刀的是狼人——需要判断）
2. 在确认狼人后使用毒药
3. 隐藏身份避免被狼人针对""",

    Role.HUNTER: """你是猎人。死亡时可以开枪带走一人（被狼刀死不能开枪）。
你的目标：如果出局，带走你最怀疑的狼人。你的存在本身就是对狼人的威慑。""",

    Role.GUARD: """你是守卫。每晚可以守护一名玩家免受狼人击杀（不能连续两晚守同一人）。
注意：同守同救（守卫+女巫同时救同一人）会导致被救者死亡！
你的目标：
1. 保护预言家等重要角色
2. 根据夜晚死亡情况推理狼人刀法，调整守护策略
3. 与女巫配合，避免同守同救的悲剧""",

    Role.IDIOT: """你是白痴。被投票放逐时可以翻牌免死（之后失去投票权）。
你的目标：
1. 隐藏身份，让狼人不敢轻易踩你
2. 翻牌时机：确认自己要被放逐时
3. 翻牌后继续发言影响局势""",

    Role.KNIGHT: """你是骑士。白天可以发起一次决斗：挑战一名玩家，若对方是狼人则对方死亡，若不是则你死亡。
你的目标：
1. 在局势不明时用决斗证明关键玩家身份
2. 谨慎选择：决斗错了好人会牺牲自己
3. 最好在怀疑某人是狼人时使用""",

    Role.CUPID: """你是丘比特。首夜可以连两名玩家为情侣（不能连自己）。
注意：情侣中若一狼一好人，则成为第三方阵营（情侣阵营），双方存活到最后时情侣阵营获胜；情侣死亡时另一人殉情。
你的目标：
1. 选择情侣——这决定了整个游戏的格局
2. 保护你的情侣""",

    Role.VILLAGER: """你是平民。没有特殊技能，但你的投票和推理至关重要。
你的目标：仔细分析发言逻辑、找出矛盾点、帮助神职引导局势。""",
}


@dataclass
class AIResponse:
    content: str
    reasoning: str = ""
    action: str = ""
    save: Optional[bool] = None          # 女巫是否救人
    poison_target: str = ""              # 女巫毒谁 / 自爆带谁 / 开枪带谁
    metadata: dict = field(default_factory=dict)
    confidence: float = 0.5
    thinking_time: float = 0.0


class AIAdapter:
    """统一 AI 调用适配器"""

    def __init__(self, config: AIConfig):
        self.config = config
        self._http = httpx.AsyncClient(timeout=60.0)

    async def _call(self, messages: list[dict], temperature: float = None) -> str:
        """统一的 API 调用 — OpenAI 兼容格式，带重试"""
        url = self.config.base_url.rstrip("/")
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

        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = await self._http.post(url, json=payload, headers=headers)
                if resp.status_code in (429, 500, 502, 503, 504):
                    wait = 2 ** attempt  # 1s, 2s, 4s 指数退避
                    logger.warning(f"LLM {resp.status_code}, {wait}s 后重试 ({attempt+1}/{max_retries})")
                    await __import__("asyncio").sleep(wait)
                    continue
                resp.raise_for_status()
                break
            except httpx.TimeoutException as e:
                if attempt == max_retries - 1:
                    raise
                await __import__("asyncio").sleep(2 ** attempt)
        else:
            raise RuntimeError(f"LLM 请求连续失败 {max_retries} 次")

        data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        reasoning = msg.get("reasoning_content") or ""
        if reasoning and not content:
            return reasoning
        if reasoning:
            try:
                parsed_content = json.loads(content)
                parsed_content["reasoning"] = reasoning
                return json.dumps(parsed_content, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError):
                return json.dumps({"reasoning": reasoning, "speech": content}, ensure_ascii=False)
        return content

    # ─── Prompt 构建 ───

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
  "vote_target": "投票/行动目标座位号（仅需要行动时填写，其他填null）"
}}

注意：只输出 JSON，不要输出其他内容。"""

    def _build_speech_prompt(self, engine: GameEngine, player_id: str) -> str:
        state = engine.state
        player = engine.get_player(player_id)
        role = Role(state.roles.get(player_id))

        alive_names = []
        for pid in state.alive_players:
            p = engine.get_player(pid)
            alive_names.append(f"{p.seat}号({p.name})" if p else pid)

        today_speeches = [
            e for e in state.events
            if e.event_type == EventType.PLAYER_SPEECH
            and e.day_count == state.day_count
            and e.phase == GamePhase.DAY_DISCUSS
        ]
        speeches_text = "\n".join([
            f"【{e.player_name}】：{e.content}" for e in today_speeches
        ]) or "(你是第一个发言的)"

        teammates = ""
        if Role(role).team == Team.WEREWOLF:
            mates = engine.get_werewolf_teammates(player_id)
            if mates:
                mate_names = [engine.get_player(m).name for m in mates if engine.get_player(m)]
                teammates = f"\n你的狼人队友：{', '.join(mate_names)}"

        lovers_info = ""
        if state.lovers and player_id in state.lovers:
            other = [x for x in state.lovers if x != player_id]
            if other:
                o = engine.get_player(other[0])
                lovers_info = f"\n你是情侣之一，你的爱人：{o.name if o else other[0]}。要保护 TA！"

        night_deaths = [
            e for e in state.events
            if e.event_type == EventType.PLAYER_DEATH
            and e.day_count == state.day_count
            and e.phase in (GamePhase.NIGHT_RESOLVE,)
        ]
        night_summary = "昨晚平安夜" if not night_deaths else \
            "昨晚 " + ", ".join(e.content for e in night_deaths)

        return f"""当前是第{state.day_count}天的讨论阶段。
你是 {player.seat}号 {player.name}，角色是{role.label}。{teammates}{lovers_info}

存活玩家：{', '.join(alive_names)}
{night_summary}

今天已有的发言：
{speeches_text}

请发表你的看法。严格按 JSON 格式输出。"""

    def _build_vote_prompt(self, engine: GameEngine, player_id: str) -> str:
        state = engine.state
        player = engine.get_player(player_id)
        role = Role(state.roles.get(player_id))

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
你是 {player.seat}号 {player.name}，角色是{role.label}。

今天的发言回顾：
{speeches_text}

可投票的玩家（除你自己）：{', '.join(alive_names)}

请决定你要投票淘汰谁。严格按 JSON 格式输出，vote_target 填目标的座位号数字。"""

    def _build_night_prompt(self, engine: GameEngine, player_id: str) -> str:
        """夜间行动 prompt（按角色区分，含狼人讨论上下文）"""
        state = engine.state
        player = engine.get_player(player_id)
        role = Role(state.roles.get(player_id))
        day = state.day_count

        alive_names = []
        for pid in state.alive_players:
            p = engine.get_player(pid)
            alive_names.append(f"{p.seat}号({p.name})" if p else pid)

        if Role(role).team == Team.WEREWOLF:
            mates = engine.get_werewolf_teammates(player_id)
            targets = [pid for pid in state.alive_players if pid not in mates and pid != player_id]
            target_names = [f"{engine.get_player(t).seat}号({engine.get_player(t).name})" for t in targets if engine.get_player(t)]
            mate_names = [engine.get_player(m).name for m in mates if engine.get_player(m)]
            # 今晚已发生的狼人讨论（前几轮提案）
            discuss = [
                e for e in state.events
                if e.event_type == EventType.WOLF_DISCUSS and e.day_count == day
            ]
            discuss_text = "\n".join([f"【{e.player_name}】：{e.content}" for e in discuss])
            extra = f"\n\n狼人内部已讨论：\n{discuss_text}" if discuss_text else ""
            return f"""现在是第{day}个夜晚。你是狼人（队友：{', '.join(mate_names)}）。{extra}
可击杀目标：{', '.join(target_names)}
请选择今晚要击杀谁。严格按 JSON 格式输出，vote_target 填目标座位号数字。"""

        if role == Role.GUARD:
            last = engine.state.guard_last_target
            last_name = engine.get_player(last).name if last and engine.get_player(last) else "无"
            targets = [pid for pid in state.alive_players if pid != player_id]
            target_names = [f"{engine.get_player(t).seat}号({engine.get_player(t).name})" for t in targets if engine.get_player(t)]
            return f"""现在是第{day}个夜晚。你是守卫。
昨晚你守的是：{last_name}（不能连续两晚守同一人）
可守护目标：{', '.join(target_names)}
请选择今晚守护谁。严格按 JSON 格式输出，vote_target 填目标座位号数字。"""

        if role == Role.SEER:
            targets = [pid for pid in state.alive_players if pid != player_id]
            target_names = [f"{engine.get_player(t).seat}号({engine.get_player(t).name})" for t in targets if engine.get_player(t)]
            return f"""现在是第{day}个夜晚。你是预言家。
可查验目标：{', '.join(target_names)}
请选择今晚要查验谁。严格按 JSON 格式输出，vote_target 填目标座位号数字。"""

        if role == Role.WITCH:
            kill_target = state.night_actions.get("wolf")
            killed_name = engine.get_player(kill_target).name if kill_target and engine.get_player(kill_target) else "无人"
            return f"""现在是第{day}个夜晚。你是女巫。
今晚狼人杀的人是：{killed_name}
你还有解药：{'是' if state.witch_antidote else '否'}
你还有毒药：{'是' if state.witch_poison else '否'}

输出严格 JSON：
{{
  "reasoning": "内心推理",
  "speech": "你的决定说明",
  "save": true或false（是否使用解药救人）,
  "poison_target": 毒杀目标座位号或null（不用毒填null）,
  "confidence": 0.0到1.0
}}"""

        if role == Role.CUPID and state.day_count == 1:
            targets = [pid for pid in state.alive_players if pid != player_id]
            target_names = [f"{engine.get_player(t).seat}号({engine.get_player(t).name})" for t in targets if engine.get_player(t)]
            return f"""这是第1个夜晚。你是丘比特。
可连情侣的玩家（不含自己）：{', '.join(target_names)}
输出严格 JSON：
{{
  "reasoning": "你选择情侣的考虑（要考虑阵营平衡）",
  "speech": "说明",
  "lovers": [目标1座位号, 目标2座位号],
  "confidence": 0.0到1.0
}}"""

        return f"现在是第{day}个夜晚。严格按 JSON 格式输出。"

    # ─── 白天特殊行动 prompt ───

    def _build_shoot_prompt(self, engine: GameEngine, player_id: str) -> str:
        """猎人开枪/狼王带人"""
        state = engine.state
        player = engine.get_player(player_id)
        role = Role(state.roles.get(player_id))
        alive_names = []
        for pid in state.alive_players:
            p = engine.get_player(pid)
            if pid != player_id:
                alive_names.append(f"{p.seat}号({p.name})" if p else pid)
        return f"""你（{player.name}，{role.label}）出局了，可以开枪带一人！
可带目标：{', '.join(alive_names)}
输出严格 JSON：{{"reasoning": "...", "vote_target": 目标座位号或null（放弃）}}"""

    def _build_explode_prompt(self, engine: GameEngine, player_id: str) -> str:
        """狼王/白狼王自爆决策"""
        state = engine.state
        player = engine.get_player(player_id)
        role = Role(state.roles.get(player_id))
        alive_names = []
        for pid in state.alive_players:
            p = engine.get_player(pid)
            if pid != player_id:
                alive_names.append(f"{p.seat}号({p.name})" if p else pid)
        return f"""你是 {player.name}（{role.label}）。白天讨论阶段，你可以自爆带走一人（也可以不自爆）。
当前局势很关键：如果局势对狼人有利就继续伪装，不利则自爆。
可带目标：{', '.join(alive_names)}
输出严格 JSON：
{{
  "reasoning": "自爆与否的决策推理",
  "explode": true或false（是否自爆）,
  "vote_target": 自爆带走目标的座位号或null（不自爆填null）
}}"""

    def _build_duel_prompt(self, engine: GameEngine, player_id: str) -> str:
        """骑士决斗决策"""
        state = engine.state
        player = engine.get_player(player_id)
        alive_names = []
        for pid in state.alive_players:
            p = engine.get_player(pid)
            if pid != player_id:
                alive_names.append(f"{p.seat}号({p.name})" if p else pid)
        return f"""你是 {player.name}（骑士）。白天可以发起决斗（只一次）：挑战一人，对方是狼则对方死，不是狼则你死。
可决斗目标：{', '.join(alive_names)}
输出严格 JSON：{{"reasoning": "决斗推理", "vote_target": 目标座位号或null（放弃决斗）}}"""

    # ─── 解析 ───

    def _parse_response(self, raw: str) -> dict:
        json_match = re.search(r'\{[\s\S]*\}', raw)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return {"speech": raw, "reasoning": "", "confidence": 0.3}

    def _resolve_seat_target(self, engine: GameEngine, target, exclude_id: str = "") -> str:
        if not target or target == "null":
            return ""
        if isinstance(target, list):
            target = target[0] if target else None
        if target in engine.players:
            return target
        try:
            seat = int(target)
            for pid in engine.state.alive_players:
                p = engine.get_player(pid)
                if p and p.seat == seat and pid != exclude_id:
                    return pid
        except (ValueError, TypeError):
            pass
        alive = [p for p in engine.state.alive_players if p != exclude_id]
        return alive[0] if alive else ""

    # ─── 行动入口 ───

    async def make_speech(self, engine: GameEngine, player_id: str) -> AIResponse:
        start = time.time()
        role = Role(engine.state.roles.get(player_id))
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
        start = time.time()
        role = Role(engine.state.roles.get(player_id))
        messages = [
            {"role": "system", "content": self._build_system_prompt(role, self.config.personality)},
            {"role": "user", "content": self._build_vote_prompt(engine, player_id)},
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
            logger.error(f"AI vote error: {e}")
            alive = [p for p in engine.state.alive_players if p != player_id]
            return AIResponse(
                content="[AI 暂时无法投票]",
                reasoning=f"Error: {str(e)}",
                action=alive[0] if alive else "",
                thinking_time=round(time.time() - start, 1),
            )

    async def decide_night_action(self, engine: GameEngine, player_id: str) -> AIResponse:
        start = time.time()
        role = Role(engine.state.roles.get(player_id))
        messages = [
            {"role": "system", "content": self._build_system_prompt(role, self.config.personality)},
            {"role": "user", "content": self._build_night_prompt(engine, player_id)},
        ]
        try:
            raw = await self._call(messages)
            parsed = self._parse_response(raw)
            resp = AIResponse(
                content=parsed.get("speech", ""),
                reasoning=parsed.get("reasoning", ""),
                action=self._resolve_seat_target(engine, parsed.get("vote_target"), player_id),
                confidence=float(parsed.get("confidence", 0.5)),
                thinking_time=round(time.time() - start, 1),
            )
            if role == Role.WITCH:
                resp.save = bool(parsed.get("save", False))
                resp.poison_target = self._resolve_seat_target(engine, parsed.get("poison_target"), player_id)
            elif role == Role.CUPID:
                lovers = parsed.get("lovers") or []
                resp.metadata["lovers"] = [
                    self._resolve_seat_target(engine, x, player_id) for x in lovers[:2]
                ]
            return resp
        except Exception as e:
            logger.error(f"AI night action error: {e}")
            return AIResponse(
                content="[AI 暂时无法行动]",
                reasoning=f"Error: {str(e)}",
                thinking_time=round(time.time() - start, 1),
            )

    async def decide_final_wolf_vote(self, engine: GameEngine, player_id: str, summary: str) -> AIResponse:
        """狼人最终投票（看到队友提案后）"""
        start = time.time()
        role = Role(engine.state.roles.get(player_id))
        messages = [
            {"role": "system", "content": self._build_system_prompt(role, self.config.personality)},
            {"role": "user", "content":
                f"现在是第{engine.state.day_count}个夜晚，你们狼人内部讨论杀人目标。\n\n队友们的提案：\n{summary}\n\n"
                f"请投出你的最终一票。严格按 JSON 格式输出，vote_target 填目标座位号。"},
        ]
        try:
            raw = await self._call(messages)
            parsed = self._parse_response(raw)
            return AIResponse(
                content=parsed.get("speech", ""),
                reasoning=parsed.get("reasoning", ""),
                action=self._resolve_seat_target(engine, parsed.get("vote_target"), player_id),
                confidence=float(parsed.get("confidence", 0.5)),
                thinking_time=round(time.time() - start, 1),
            )
        except Exception as e:
            logger.error(f"AI wolf final vote error: {e}")
            return AIResponse(content="", reasoning=str(e),
                              action="", thinking_time=0)

    async def decide_shoot(self, engine: GameEngine, player_id: str) -> AIResponse:
        start = time.time()
        role = Role(engine.state.roles.get(player_id))
        messages = [
            {"role": "system", "content": self._build_system_prompt(role, self.config.personality)},
            {"role": "user", "content": self._build_shoot_prompt(engine, player_id)},
        ]
        try:
            raw = await self._call(messages)
            parsed = self._parse_response(raw)
            return AIResponse(
                content=parsed.get("speech", ""),
                reasoning=parsed.get("reasoning", ""),
                action=self._resolve_seat_target(engine, parsed.get("vote_target"), player_id),
                confidence=float(parsed.get("confidence", 0.5)),
                thinking_time=round(time.time() - start, 1),
            )
        except Exception as e:
            logger.error(f"AI shoot error: {e}")
            return AIResponse(content="", reasoning=str(e), action="",
                              thinking_time=round(time.time() - start, 1))

    async def decide_explode(self, engine: GameEngine, player_id: str) -> AIResponse:
        start = time.time()
        role = Role(engine.state.roles.get(player_id))
        messages = [
            {"role": "system", "content": self._build_system_prompt(role, self.config.personality)},
            {"role": "user", "content": self._build_explode_prompt(engine, player_id)},
        ]
        try:
            raw = await self._call(messages)
            parsed = self._parse_response(raw)
            explode = bool(parsed.get("explode", False))
            target = self._resolve_seat_target(engine, parsed.get("vote_target"), player_id)
            return AIResponse(
                content=parsed.get("speech", ""),
                reasoning=parsed.get("reasoning", ""),
                action="__explode__" if explode else "",
                poison_target=target,
                confidence=float(parsed.get("confidence", 0.5)),
                thinking_time=round(time.time() - start, 1),
            )
        except Exception as e:
            logger.error(f"AI explode error: {e}")
            return AIResponse(content="", reasoning=str(e),
                              thinking_time=round(time.time() - start, 1))

    async def decide_duel(self, engine: GameEngine, player_id: str) -> AIResponse:
        start = time.time()
        role = Role(engine.state.roles.get(player_id))
        messages = [
            {"role": "system", "content": self._build_system_prompt(role, self.config.personality)},
            {"role": "user", "content": self._build_duel_prompt(engine, player_id)},
        ]
        try:
            raw = await self._call(messages)
            parsed = self._parse_response(raw)
            return AIResponse(
                content=parsed.get("speech", ""),
                reasoning=parsed.get("reasoning", ""),
                action=self._resolve_seat_target(engine, parsed.get("vote_target"), player_id),
                confidence=float(parsed.get("confidence", 0.5)),
                thinking_time=round(time.time() - start, 1),
            )
        except Exception as e:
            logger.error(f"AI duel error: {e}")
            return AIResponse(content="", reasoning=str(e),
                              thinking_time=round(time.time() - start, 1))

    async def close(self):
        await self._http.aclose()
