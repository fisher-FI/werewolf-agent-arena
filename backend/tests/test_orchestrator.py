"""编排层冒烟测试 — mock LLM 跑完整对局，验证全流程无卡死"""

import sys, os, asyncio, random
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from engine.models import Player, Role, AIConfig
from engine.boards import BOARDS
from ai.adapter import AIResponse
from ai.orchestrator import Room


class FakeAdapter:
    """模拟 LLM：随机但合法的决策"""
    def __init__(self, config=None):
        self.player_id = None

    async def make_speech(self, engine, player_id):
        return AIResponse(content="我怀疑有狼人在隐藏身份，建议观察他们的发言逻辑。",
                          reasoning="根据现有信息，我保持谨慎。",
                          confidence=0.6, thinking_time=0.1)

    async def make_reflection(self, engine, player_id, last_speech):
        # 默认反射：认为无需补充
        return AIResponse(content="", reasoning="我的发言已充分，无需补充。",
                          confidence=0.5, thinking_time=0.1)

    async def cast_vote(self, engine, player_id):
        alive = [p for p in engine.state.alive_players if p != player_id]
        return AIResponse(content="", reasoning="随机投票",
                          action=random.choice(alive), confidence=0.5, thinking_time=0.1)

    async def decide_night_action(self, engine, player_id):
        role = Role(engine.state.roles[player_id])
        alive = [p for p in engine.state.alive_players if p != player_id]
        if role == Role.WITCH:
            # 第一晚救人，之后只毒（随机）
            resp = AIResponse(content="", reasoning="", confidence=0.5, thinking_time=0.1)
            if engine.state.witch_antidote and engine.state.night_actions.get("wolf"):
                resp.save = True
                resp.poison_target = ""
            else:
                resp.save = False
                resp.poison_target = random.choice(alive) if engine.state.witch_poison else ""
            return resp
        if role == Role.CUPID:
            others = alive[:2]
            resp = AIResponse(content="", reasoning="", confidence=0.5, thinking_time=0.1)
            resp.metadata["lovers"] = others
            return resp
        if role == Role.GUARD:
            candidates = [p for p in alive if p != engine.state.guard_last_target]
            return AIResponse(content="", reasoning="", confidence=0.5,
                              action=random.choice(candidates), thinking_time=0.1)
        # 狼人/预言家
        return AIResponse(content="", reasoning="", confidence=0.5,
                          action=random.choice(alive), thinking_time=0.1)

    async def decide_final_wolf_vote(self, engine, player_id, summary):
        alive = [p for p in engine.state.alive_players if p != player_id]
        return AIResponse(content="", reasoning="", confidence=0.5,
                          action=random.choice(alive), thinking_time=0.1)

    async def decide_shoot(self, engine, player_id):
        alive = [p for p in engine.state.alive_players if p != player_id]
        return AIResponse(content="", reasoning="", confidence=0.5,
                          action=random.choice(alive), thinking_time=0.1)

    async def decide_explode(self, engine, player_id):
        return AIResponse(content="", reasoning="", confidence=0.5,
                          action="", poison_target="", thinking_time=0.1)

    async def decide_duel(self, engine, player_id):
        alive = [p for p in engine.state.alive_players if p != player_id]
        return AIResponse(content="", reasoning="", confidence=0.5,
                          action=random.choice(alive), thinking_time=0.1)


def make_room(board_id: str) -> Room:
    room = Room(board_id=board_id)
    room.delay_factor = 0.0   # 测试加速
    board = BOARDS[board_id]
    for i in range(1, board.player_count + 1):
        room.add_player(Player(id=f"p{i}", name=f"玩家{i}", seat=i, player_type="ai"))
    room.adapters = {p.id: FakeAdapter() for p in room.players}
    return room


async def _run_game(room: Room, max_seconds: float = 30):
    """跑一局，最多等 max_seconds 秒"""
    await asyncio.wait_for(room.start_game(), timeout=max_seconds)
    return room


@pytest.mark.asyncio
@pytest.mark.parametrize("board_id", list(BOARDS.keys()))
async def test_full_game_all_boards(board_id):
    room = make_room(board_id)
    try:
        await _run_game(room, max_seconds=20)
    except asyncio.TimeoutError:
        pytest.fail(f"板子 {board_id} 对局卡死（超时20s）")
    assert room.status == "finished", f"板子 {board_id} 未正常结束"
    assert room.engine.state.winner is not None
    # 事件流完整
    end_events = [e for e in room.game_events if e.get("event_type") == "game_end"]
    assert end_events, f"板子 {board_id} 缺少 game_end 事件"
    print(f"\n板子 {board_id} 完成: 胜者={room.engine.state.winner.value}, "
          f"原因={room.engine.state.winner_reason}, 回合={room.engine.state.day_count}")


# 手动注册 asyncio 模式
def pytest_configure(config):
    pass


class FakeReflectiveAdapter(FakeAdapter):
    """带二次思考的假 LLM：发言后总是补充一句"""
    async def make_speech(self, engine, player_id):
        return AIResponse(content="我怀疑有人隐藏身份。",
                          reasoning="观察中", confidence=0.6, thinking_time=0.1)

    async def make_reflection(self, engine, player_id, last_speech):
        return AIResponse(
            content=f"补充：我注意到{last_speech}，补充一点，我认为5号也可疑。",
            reasoning="反思：我的发言有点笼统，补充具体怀疑对象。",
            confidence=0.7, thinking_time=0.1)


@pytest.mark.asyncio
async def test_reflection_adds_second_speech():
    room = make_room("ywls")
    room.delay_factor = 0.0
    # 覆盖为带反思的 adapter
    room.adapters = {p.id: FakeReflectiveAdapter() for p in room.players}
    await _run_game(room, max_seconds=20)
    speeches = [e for e in room.game_events
                if e.get("event_type") == "player_speech"]
    reflections = [e for e in speeches if e.get("metadata", {}).get("reflection")]
    assert reflections, "应有二次思考补充发言"
    assert all("补充" in e["content"] for e in reflections), "补充内容应包含反思文本"
    # 二次思考不应改变玩家状态（纯追加发言）
    assert room.status == "finished"


@pytest.mark.asyncio
async def test_reflection_can_be_disabled():
    room = make_room("ywls")
    room.delay_factor = 0.0
    room.reflection_enabled = False
    room.adapters = {p.id: FakeReflectiveAdapter() for p in room.players}
    await _run_game(room, max_seconds=20)
    reflections = [e for e in room.game_events
                   if e.get("metadata", {}).get("reflection")]
    assert not reflections, "关闭开关后不应有二次思考"
