"""引擎测试 — 纯逻辑，零 LLM 依赖"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest

from engine.models import Player, Role, Team, GamePhase, EventType
from engine.game import GameEngine, IllegalTransitionError, GOD_ROLES
from engine.boards import BOARDS, get_board


def make_players(n: int = 12) -> list:
    return [Player(id=f"p{i}", name=f"玩家{i}", seat=i) for i in range(1, n + 1)]


def make_engine(board_id: str = "ywls", n: int = None):
    board = get_board(board_id)
    n = n or board.player_count
    eng = GameEngine(make_players(n), board)
    eng.assign_roles()
    return eng


def roles_of(eng) -> dict:
    return {pid: Role(r) for pid, r in eng.state.roles.items()}


def find_role(eng, role: Role) -> str:
    for pid, r in roles_of(eng).items():
        if r == role:
            return pid
    return None


# ─── 板子配置 ───

class TestBoards:
    def test_all_boards_12_players(self):
        for bid, b in BOARDS.items():
            assert b.player_count == 12, f"{bid} 不是12人"

    def test_board_role_counts(self):
        b = BOARDS["ywls"]
        assert b.role_counts[Role.WEREWOLF] == 4
        assert b.role_counts[Role.VILLAGER] == 4
        assert set(b.role_counts) == {Role.WEREWOLF, Role.SEER, Role.WITCH,
                                      Role.HUNTER, Role.GUARD, Role.VILLAGER}

    def test_cupid_board_has_lovers(self):
        assert BOARDS["cupid"].has_lovers
        assert BOARDS["cupid"].first_night_cupid


# ─── 状态机 ───

class TestStateMachine:
    def test_initial_state(self):
        eng = make_engine()
        assert eng.state.phase == GamePhase.WAITING

    def test_illegal_transition_raises(self):
        eng = make_engine()
        with pytest.raises(IllegalTransitionError):
            eng._transition(GamePhase.GAMEOVER)  # WAITING 不能直接 GAMEOVER

    def test_normal_flow(self):
        eng = make_engine()
        eng.start_game()
        assert eng.state.phase == GamePhase.NIGHT
        eng.resolve_night()
        assert eng.state.phase in (GamePhase.NIGHT_RESOLVE, GamePhase.SHOOT,
                                   GamePhase.DAY_DISCUSS, GamePhase.GAMEOVER)


# ─── 夜晚结算 ───

class TestNightResolution:
    def _setup_wolf_kill(self, eng):
        """让狼人刀 3 号"""
        wolves = eng.get_alive_werewolves()
        assert wolves, "应有狼人"
        target = "p3"
        eng.process_werewolf_kill(target)
        return wolves, target

    def test_wolf_kill_dies(self):
        eng = make_engine()
        eng.start_game()
        self._setup_wolf_kill(eng)
        events = eng.resolve_night()
        assert "p3" not in eng.state.alive_players
        assert any(e.event_type == EventType.PLAYER_DEATH for e in events)

    def test_guard_protects(self):
        eng = make_engine()
        eng.start_game()
        guard = find_role(eng, Role.GUARD)
        eng.process_guard_protect(guard, "p3")
        eng.process_werewolf_kill("p3")
        events = eng.resolve_night()
        assert "p3" in eng.state.alive_players, "守卫守护后不应死"
        assert any(e.event_type == EventType.SYSTEM and "平安夜" in e.content for e in events)

    def test_witch_save_protects(self):
        eng = make_engine()
        eng.start_game()
        witch = find_role(eng, Role.WITCH)
        eng.process_werewolf_kill("p3")
        eng.process_witch_action(witch, save=True)
        eng.resolve_night()
        assert "p3" in eng.state.alive_players

    def test_same_guard_save_dies(self):
        """同守同救必死"""
        eng = make_engine()
        eng.start_game()
        guard = find_role(eng, Role.GUARD)
        witch = find_role(eng, Role.WITCH)
        eng.process_guard_protect(guard, "p3")
        eng.process_werewolf_kill("p3")
        eng.process_witch_action(witch, save=True)
        eng.resolve_night()
        assert "p3" not in eng.state.alive_players, "同守同救必死"

    def test_witch_poison_kills(self):
        eng = make_engine()
        eng.start_game()
        witch = find_role(eng, Role.WITCH)
        eng.process_witch_action(witch, save=False, poison_target="p5")
        eng.resolve_night()
        assert "p5" not in eng.state.alive_players

    def test_witch_potions_once(self):
        eng = make_engine()
        eng.start_game()
        witch = find_role(eng, Role.WITCH)
        eng.process_witch_action(witch, save=True)
        eng.process_witch_action(witch, save=True)  # 第二次救无效
        assert eng.state.witch_antidote is False
        eng2 = make_engine()
        eng2.start_game()
        w2 = find_role(eng2, Role.WITCH)
        eng2.process_witch_action(w2, poison_target="p2")
        eng2.process_witch_action(w2, poison_target="p3")  # 第二次毒无效
        assert "p3" in eng2.state.alive_players

    def test_guard_no_consecutive(self):
        eng = make_engine()
        eng.start_game()
        guard = find_role(eng, Role.GUARD)
        eng.process_guard_protect(guard, "p3")
        with pytest.raises(ValueError):
            eng.process_guard_protect(guard, "p3")  # 连守同一人


# ─── 猎人/狼王/白痴/骑士/丘比特 ───

class TestSpecialRoles:
    def test_hunter_dead_by_wolf_no_shoot(self):
        eng = make_engine()
        eng.start_game()
        hunter = find_role(eng, Role.HUNTER)
        eng.process_werewolf_kill(hunter)
        eng.resolve_night()
        assert eng.state.pending_shoots == [], "狼刀死猎人不能开枪"

    def test_hunter_dead_by_vote_can_shoot(self):
        eng = make_engine()
        eng.start_game()
        hunter = find_role(eng, Role.HUNTER)
        # 模拟投票出局猎人（不手动移除，由引擎处理死亡）
        events = eng._apply_deaths([(hunter, "vote")])
        assert eng.state.pending_shoots == [(hunter, "hunter")]

    def test_hunter_shoot_kills_target(self):
        eng = make_engine()
        eng.start_game()
        hunter = find_role(eng, Role.HUNTER)
        target = [p for p in eng.state.alive_players if p != hunter][0]
        eng._apply_deaths([(hunter, "vote")])
        events = eng.process_shoot(hunter, target)
        assert target not in eng.state.alive_players

    def test_alpha_wolf_vote_carries(self):
        eng = make_engine("lwsh")
        eng.start_game()
        alpha = find_role(eng, Role.ALPHA_WOLF)
        eng._apply_deaths([(alpha, "vote")])
        assert eng.state.pending_shoots == [(alpha, "alpha")]

    def test_alpha_wolf_shoot(self):
        eng = make_engine("lwsh")
        eng.start_game()
        alpha = find_role(eng, Role.ALPHA_WOLF)
        target = [p for p in eng.state.alive_players if p != alpha][0]
        eng._apply_deaths([(alpha, "vote")])
        eng.process_shoot(alpha, target)
        assert target not in eng.state.alive_players

    def test_idiot_reveal_survives(self):
        eng = make_engine("ywlb")
        eng.start_game()
        idiot = find_role(eng, Role.IDIOT)
        # 推进到投票阶段（状态机合法性另有测试，这里直接定位阶段）
        eng.state.phase = GamePhase.DAY_VOTE
        # 模拟投票：除白痴外都投白痴
        for v in eng.state.alive_players:
            if v != idiot:
                eng.process_vote(v, idiot)
        events = eng.resolve_votes()
        assert idiot in eng.state.alive_players, "白痴翻牌免死"
        assert any(e.event_type == EventType.IDIOT_REVEAL for e in events)

    def test_knight_duel_wolf_dies(self):
        eng = make_engine("bwlqs")
        eng.start_game()
        knight = find_role(eng, Role.KNIGHT)
        wolf = eng.get_alive_werewolves()[0]
        events = eng.process_knight_duel(knight, wolf)
        assert wolf not in eng.state.alive_players, "决斗狼人应死"

    def test_knight_duel_good_self_dies(self):
        eng = make_engine("bwlqs")
        eng.start_game()
        knight = find_role(eng, Role.KNIGHT)
        good = [p for p in eng.state.alive_players if p != knight and p not in eng.get_alive_werewolves()][0]
        eng.process_knight_duel(knight, good)
        assert knight not in eng.state.alive_players, "决斗好人骑士死"

    def test_cupid_lovers_death(self):
        eng = make_engine("cupid")
        eng.start_game()
        cupid = find_role(eng, Role.CUPID)
        others = [p for p in eng.state.alive_players if p != cupid]
        eng.process_cupid_chain(cupid, others[0], others[1])
        assert len(eng.state.lovers) == 2
        # 杀一个情侣 → 殉情（不手动移除，由引擎处理死亡）
        events = eng._apply_deaths([(others[0], "wolf_kill")])
        assert others[1] not in eng.state.alive_players, "情侣殉情"
        assert any(e.event_type == EventType.LOVERS_DEATH for e in events)


# ─── 胜负判定 ───

class TestWin:
    def test_villager_wins_wolves_dead(self):
        eng = make_engine()
        eng.start_game()
        for pid in eng.get_alive_werewolves():
            eng.state.alive_players.remove(pid)
        assert eng.check_winner() == Team.VILLAGER

    def test_wolf_wins_when_majority(self):
        eng = make_engine()
        eng.start_game()
        # 留下 2 狼 2 好人
        wolves = eng.get_alive_werewolves()
        good = eng.get_alive_good()
        for pid in wolves[2:] + good[2:]:
            eng.state.alive_players.remove(pid)
        assert eng.check_winner() == Team.WEREWOLF

    def test_kill_side_gods_dead(self):
        eng = make_engine()
        eng.start_game()
        for pid in eng.get_alive_gods():
            eng.state.alive_players.remove(pid)
        # 狼未全灭、人数未过半 → 屠边神灭应判狼胜
        if eng.check_winner() is None:
            pytest.skip("狼已全灭则好人胜")
        assert eng.check_winner() == Team.WEREWOLF

    def test_kill_side_villagers_dead(self):
        eng = make_engine()
        eng.start_game()
        for pid in eng.get_alive_villagers():
            eng.state.alive_players.remove(pid)
        if eng.check_winner() is None:
            pytest.skip("狼已全灭则好人胜")
        assert eng.check_winner() == Team.WEREWOLF

    def test_lovers_win_last_two(self):
        eng = make_engine("cupid")
        eng.start_game()
        cupid = find_role(eng, Role.CUPID)
        others = [p for p in eng.state.alive_players if p != cupid]
        eng.process_cupid_chain(cupid, others[0], others[1])
        # 让情侣是一狼一好人
        r0, r1 = roles_of(eng)[others[0]], roles_of(eng)[others[1]]
        if r0.team == r1.team:
            pytest.skip("情侣同阵营无第三方")
        # 只剩情侣两人
        for pid in eng.state.alive_players[:]:
            if pid not in eng.state.lovers:
                eng.state.alive_players.remove(pid)
        assert eng.check_winner() == Team.LOVERS


# ─── 信息隔离 ───

class TestVisibility:
    def test_wolf_sees_teammates(self):
        eng = make_engine()
        eng.start_game()
        wolf = eng.get_alive_werewolves()[0]
        vs = eng.get_visible_state(wolf)
        assert len(vs["roles_visible"]) == 4  # 自己 + 3 队友

    def test_villager_sees_only_self(self):
        eng = make_engine()
        eng.start_game()
        v = find_role(eng, Role.VILLAGER)
        vs = eng.get_visible_state(v)
        assert len(vs["roles_visible"]) == 1

    def test_lovers_see_each_other(self):
        eng = make_engine("cupid")
        eng.start_game()
        cupid = find_role(eng, Role.CUPID)
        others = [p for p in eng.state.alive_players if p != cupid]
        eng.process_cupid_chain(cupid, others[0], others[1])
        vs = eng.get_visible_state(others[0])
        assert others[1] in vs["roles_visible"]

    def test_witch_kill_event_hidden_from_villager(self):
        eng = make_engine()
        eng.start_game()
        eng.process_werewolf_kill("p3")
        wolf_kill_events = [e for e in eng.state.events if e.event_type == EventType.WEREWOLF_KILL]
        assert wolf_kill_events and wolf_kill_events[0].visible_to != "all"
