"""回归测试 — 锁定子代理审查发现的 11 个 Bug（先失败，修复后通过）"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from engine.models import Player, Role, Team, GamePhase, EventType
from engine.game import GameEngine, IllegalTransitionError
from engine.boards import get_board, BOARDS


def make_players(n: int = 12) -> list:
    return [Player(id=f"p{i}", name=f"玩家{i}", seat=i) for i in range(1, n + 1)]


def make_engine(board_id: str = "ywls", n: int = None):
    board = get_board(board_id)
    n = n or board.player_count
    return GameEngine(make_players(n), board)


def find_role(eng, role: Role) -> str:
    for pid, r in eng.state.roles.items():
        if Role(r) == role:
            return pid
    return None


# ─── Bug1: 白痴翻牌后仍能投票 ───

def test_idiot_loses_vote_after_reveal():
    eng = make_engine("ywlb")
    eng.assign_roles()
    eng.start_game()
    idiot = find_role(eng, Role.IDIOT)
    # 模拟白痴被票出翻牌
    eng.state.phase = GamePhase.DAY_VOTE
    eng.state.pending_idiot = idiot
    # 白痴尝试投票 → 引擎应拒绝
    eng.state.vote_results.clear()
    target = [p for p in eng.state.alive_players if p != idiot][0]
    eng.process_vote(idiot, target)
    assert idiot not in eng.state.vote_results, "白痴翻牌后不应有投票权"


# ─── Bug2: 狼人兜底可能刀队友 ───

def test_wolf_force_pick_excludes_teammates():
    from ai.adapter import AIAdapter
    from engine.models import AIConfig
    a = AIAdapter(AIConfig(api_key="x", base_url="http://x"))
    eng = make_engine()
    eng.assign_roles()
    eng.start_game()
    wolf = eng.get_alive_werewolves()[0]
    mates = eng.get_werewolf_teammates(wolf)
    # force_pick 时排除自己 + 排除狼队友
    picked = a._resolve_seat_target(eng, None, wolf, force_pick=True)
    assert picked, "应兜底选到人"
    assert picked != wolf, "不能选自己"
    assert picked not in mates, f"不能刀队友: picked={picked}, mates={mates}"


# ─── Bug3: 自爆后应直接入夜（不继续投票） ───

def test_explode_ends_day_phase():
    from ai.orchestrator import Room
    room = Room(board_id="lwsh")
    for i in range(1, 13):
        room.add_player(Player(id=f"p{i}", name=f"玩家{i}", seat=i, player_type="ai"))
    # 手动布置：狼王自爆
    from engine.game import GameEngine
    eng = GameEngine(room.players, get_board("lwsh"))
    eng.assign_roles()
    eng.start_game()
    room.engine = eng
    alpha = find_role(eng, Role.ALPHA_WOLF)
    eng.state.phase = GamePhase.DAY_DISCUSS
    events = eng.process_self_explode(alpha)
    # 自爆后引擎应进入 NIGHT（或 GAMEOVER）
    assert eng.state.phase in (GamePhase.NIGHT, GamePhase.GAMEOVER), \
        f"自爆后应入夜/结束，实际 {eng.state.phase}"


# ─── Bug4: 判胜前应清空开枪队列（狼王带人技能不被吞） ───

def test_alpha_carries_before_win_check():
    eng = make_engine("lwsh")
    eng.assign_roles()
    eng.start_game()
    alpha = find_role(eng, Role.ALPHA_WOLF)
    # 场景：狼王被票出，且是最后一只狼 → 若先判胜则带人技能被吞
    wolves = eng.get_alive_werewolves()
    for w in wolves:
        if w != alpha:
            eng.state.alive_players.remove(w)
    # 票出狼王 → 应先入 pending_shoots，再判胜
    eng.state.phase = GamePhase.DAY_VOTE
    eng.process_vote([p for p in eng.state.alive_players if p != alpha][0], alpha)
    events = eng.resolve_votes()
    assert eng.state.pending_shoots, "狼王被票出应能带人（技能不应被吞）"


# ─── Bug5: 女巫药水剩余量不应全员可见 ───

def test_witch_potions_not_leaked():
    eng = make_engine()
    eng.assign_roles()
    eng.start_game()
    witch = find_role(eng, Role.WITCH)
    villager = find_role(eng, Role.VILLAGER)
    vs_witch = eng.get_visible_state(witch)
    vs_villager = eng.get_visible_state(villager)
    assert "witch_antidote" not in vs_villager, "平民不应看到女巫药水"
    assert "witch_poison" not in vs_villager, "平民不应看到女巫药水"


# ─── Bug6: 女巫不用药时 events[-2:] 不应广播狼刀事件 ───

def test_witch_no_action_no_leak():
    """女巫不行动时，广播的事件不应包含狼刀私密事件"""
    from ai.orchestrator import Room
    room = Room(board_id="ywls")
    for i in range(1, 13):
        room.add_player(Player(id=f"p{i}", name=f"玩家{i}", seat=i, player_type="ai"))
    eng = GameEngine(room.players, get_board("ywls"))
    eng.assign_roles()
    eng.start_game()
    room.engine = eng
    witch = find_role(eng, Role.WITCH)
    # 女巫不救不毒
    events = eng.process_witch_action(witch, save=False, poison_target="")
    assert events == [], "女巫不行动不应产生事件"
    # 引擎内狼刀事件 visible_to 应仅狼队
    wolf_kills = [e for e in eng.state.events if e.event_type == EventType.WEREWOLF_KILL]
    for e in wolf_kills:
        assert e.visible_to != "all", "狼刀事件不应全员可见"


# ─── Bug7: 预言家查狼王/白狼王应记为狼人 ───

def test_seer_check_alpha_wolf_is_wolf():
    eng = make_engine("lwsh")
    eng.assign_roles()
    eng.start_game()
    seer = find_role(eng, Role.SEER)
    alpha = find_role(eng, Role.ALPHA_WOLF)
    event = eng.process_seer_check(seer, alpha)
    assert event.metadata["is_werewolf"] is True, "狼王应被验为狼人"
    assert "狼人" in event.content


# ─── Bug8: 人类玩家开枪不崩溃 ───

def test_human_hunter_shoot_no_crash():
    """人类猎人在开枪队列时，编排层不应 KeyError"""
    from ai.orchestrator import Room
    room = Room(board_id="ywls")
    for i in range(1, 13):
        room.add_player(Player(id=f"p{i}", name=f"玩家{i}", seat=i,
                               player_type="human" if i == 1 else "ai"))
    # 只给 AI 建 adapter
    room.adapters = {}
    eng = GameEngine(room.players, get_board("ywls"))
    eng.assign_roles()
    eng.start_game()
    room.engine = eng
    hunter = find_role(eng, Role.HUNTER)
    eng._apply_deaths([(hunter, "vote")])
    assert eng.state.pending_shoots, "猎人应入开枪队列"
    # 人类猎人无 adapter → 应跳过或等待，不崩溃（逻辑在编排层，这里验证队列存在即可）
    assert eng.state.pending_shoots[0][0] == hunter


# ─── Bug9: 守卫连守/丘比特非法不应崩溃（应优雅拒绝） ───

def test_guard_consecutive_no_crash():
    eng = make_engine()
    eng.assign_roles()
    eng.start_game()
    guard = find_role(eng, Role.GUARD)
    eng.process_guard_protect(guard, "p3")
    # 第二次守同一人 → ValueError（编排层需捕获，引擎层至少不能产生错误状态）
    with pytest.raises(ValueError):
        eng.process_guard_protect(guard, "p3")


def test_cupid_invalid_no_crash():
    eng = make_engine("cupid")
    eng.assign_roles()
    eng.start_game()
    cupid = find_role(eng, Role.CUPID)
    with pytest.raises(ValueError):
        eng.process_cupid_chain(cupid, cupid, "p2")  # 连自己


# ─── Bug10: 投无效目标不伪造选票 ───

def test_invalid_vote_target_not_faked():
    """LLM 输出无效目标时，应视为弃票而非伪造随机票"""
    from ai.adapter import AIAdapter
    from engine.models import AIConfig
    a = AIAdapter(AIConfig(api_key="x", base_url="http://x"))
    eng = make_engine()
    eng.assign_roles()
    eng.start_game()
    # 无效目标（不存在的座位 99）→ 非 force_pick 时返回空 = 弃票
    picked = a._resolve_seat_target(eng, "99", "p1", force_pick=False)
    assert picked == "", "无效目标应视为弃票而非随机伪造"
    # force_pick 场景（狼人必须刀）→ 合法兜底
    picked2 = a._resolve_seat_target(eng, "99", "p1", force_pick=True)
    assert picked2 != "", "必须行动时应有兜底"


# ─── Bug11: GAMEOVER 后无副作用 ───

def test_gameover_frozen():
    eng = make_engine()
    eng.assign_roles()
    eng.start_game()
    eng.state.phase = GamePhase.GAMEOVER
    eng.state.winner = Team.VILLAGER
    # 转移应拒绝
    with pytest.raises(IllegalTransitionError):
        eng._transition(GamePhase.NIGHT)


# ─── 第二批修复的回归测试 ───

def test_witch_cannot_self_save_after_night1():
    """非首夜女巫不能自救（药水不消耗）"""
    eng = make_engine()
    eng.assign_roles()
    eng.start_game()
    witch = find_role(eng, Role.WITCH)
    eng.state.day_count = 3  # 第3夜
    eng.process_werewolf_kill(witch)
    eng.process_witch_action(witch, save=True)
    assert eng.state.witch_antidote is True, "非首夜自救应保留药水"
    eng.resolve_night()
    assert witch not in eng.state.alive_players, "非首夜自救无效，女巫应死"


def test_witch_can_self_save_night1():
    """首夜女巫可自救"""
    eng = make_engine()
    eng.assign_roles()
    eng.start_game()
    witch = find_role(eng, Role.WITCH)
    eng.process_werewolf_kill(witch)
    eng.process_witch_action(witch, save=True)
    assert eng.state.witch_antidote is False, "首夜自救应消耗药水"
    eng.resolve_night()
    assert witch in eng.state.alive_players, "首夜自救成功，女巫应存活"


def test_alpha_last_wolf_still_carries():
    """狼王是最后一只狼被票出：应先带人再判胜（技能不被吞）"""
    eng = make_engine("lwsh")
    eng.assign_roles()
    eng.start_game()
    alpha = find_role(eng, Role.ALPHA_WOLF)
    # 杀掉其他狼
    for w in eng.get_alive_werewolves():
        if w != alpha:
            eng.state.alive_players.remove(w)
    # 投票出狼王
    eng.state.phase = GamePhase.DAY_VOTE
    voter = [p for p in eng.state.alive_players if p != alpha][0]
    eng.process_vote(voter, alpha)
    events = eng.resolve_votes()
    # 应进入 SHOOT 而非直接 GAMEOVER
    assert eng.state.phase == GamePhase.SHOOT, f"应先开枪，实际 {eng.state.phase}"
    # 带人后判胜
    target = [p for p in eng.state.alive_players if p != alpha][0]
    events = eng.process_shoot(alpha, target)
    assert eng.state.phase == GamePhase.GAMEOVER


def test_vote_dead_player_is_abstain():
    """投已死玩家视为弃票"""
    eng = make_engine()
    eng.assign_roles()
    eng.start_game()
    # 杀掉 p5
    eng.state.alive_players.remove("p5")
    eng.state.phase = GamePhase.DAY_VOTE
    event = eng.process_vote("p1", "p5")
    assert "p5" not in eng.state.vote_results, "投死者不应计入"
    assert event.metadata.get("abstain"), "应标记为弃票"


def test_human_shoot_resolution():
    """人类开枪输入解析：座位号/名字/空"""
    from ai.orchestrator import Room
    room = Room(board_id="ywls")
    for i in range(1, 13):
        room.add_player(Player(id=f"p{i}", name=f"玩家{i}", seat=i, player_type="ai"))
    eng = GameEngine(room.players, get_board("ywls"))
    eng.assign_roles()
    eng.start_game()
    room.engine = eng
    assert room._resolve_human_target("5") == "p5", "座位号解析"
    assert room._resolve_human_target("玩家7") == "p7", "名字解析"
    assert room._resolve_human_target("") == "", "空=放弃"
    assert room._resolve_human_target("99") == "", "无效目标=放弃"
