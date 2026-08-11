"""完整对局冒烟（验收版）：真 LLM 12 人预女猎守，全面断言"""
import asyncio, sys, os, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.WARNING)

os.environ['XIAOMI_API_KEY'] = 'sk-3sI92baHekMZohmnAbWqEBD2iPSlVBkKL38iaF0n7CBS0IouMbmVCXS3s6J1kDva'
os.environ['XIAOMI_BASE_URL'] = 'https://opencode.ai/zen/go/v1'

from engine.models import Player, AIConfig, Team, Role
from ai.orchestrator import Room

RESULTS = []

def check(name: str, cond: bool, detail: str = ""):
    RESULTS.append((name, cond, detail))
    print(f"  {'PASS' if cond else 'FAIL'} {name}" + (f" -- {detail}" if detail else ""), flush=True)

async def main():
    cfg = AIConfig(provider='deepseek', model='deepseek-v4-flash',
                   api_key=os.environ['XIAOMI_API_KEY'],
                   base_url=os.environ['XIAOMI_BASE_URL'],
                   temperature=0.7, max_tokens=800,
                   reasoning_effort='max')
    room = Room(board_id='ywls')
    for i in range(1, 13):
        room.add_player(Player(id=f'p{i}', name=f'玩家{i}', seat=i, player_type='ai'))
    room.setup_ai_adapters(cfg)
    room.delay_factor = 0.0

    # 进度钩子：打印阶段变化
    orig_broadcast = room.broadcast
    async def tracked_broadcast(event_type, data):
        if event_type == "phase_change":
            print(f"  [进度] d{data.get('day_count')} {data.get('phase')}: {str(data.get('content',''))[:50]}", flush=True)
        await orig_broadcast(event_type, data)
    room.broadcast = tracked_broadcast

    start = asyncio.get_event_loop().time()
    try:
        await asyncio.wait_for(room.start_game(), timeout=3600)
        elapsed = asyncio.get_event_loop().time() - start
    except asyncio.TimeoutError:
        print("TIMEOUT at", room.engine.state.phase, flush=True)
        check("对局在3000s内跑完", False, f"停在 {room.engine.state.phase}")
        return

    print(f"\n=== 对局完成: {elapsed:.0f}s ({elapsed/60:.1f}min), "
          f"{room.engine.state.day_count} 天 ===", flush=True)

    w = room.engine.state.winner
    check("有胜者", w is not None, str(w))
    check("回合数合理(4-15天)", 4 <= room.engine.state.day_count <= 15,
          str(room.engine.state.day_count))

    speeches = [e for e in room.game_events if e.get('event_type') == 'player_speech']
    placeholders = [s for s in speeches
                    if s.get('content') in ('[本回合未发言]', '[AI 暂时无法发言]', '')]
    total_speech = len(speeches)
    check("发言非空率 >=95%", total_speech > 0 and
          (total_speech - len(placeholders)) / total_speech >= 0.95,
          f"{len(placeholders)}/{total_speech} 空发言")

    votes = [e for e in room.game_events if e.get('event_type') == 'vote_cast']
    abstains = [v for v in votes if v.get('metadata', {}).get('abstain')]
    check("投票事件存在", len(votes) > 0, f"{len(votes)} 票")
    check("弃票比例合理(<40%)", len(abstains) / max(len(votes), 1) < 0.4,
          f"{len(abstains)}/{len(votes)} 弃票")

    day1_names = {f"玩家{i}" for i in range(1, 13)}
    late_speeches = [e for e in speeches if (e.get('day_count') or 0) >= 3]
    recalled = [s for s in late_speeches
                if any(n in s.get('content', '') for n in day1_names)]
    check("跨天记忆引用(第3天提第1天人名)", len(late_speeches) == 0 or len(recalled) >= 1,
          f"{len(recalled)}/{len(late_speeches)} 条引用")

    wolf_players = {pid for pid, r in room.engine.state.roles.items()
                    if Role(r).team == Team.WEREWOLF}
    leak_kw = ["我是狼", "我是狼人", "我是狼王", "我白狼王", "狼队", "刀了"]
    leaks = [s for s in speeches
             if s.get('player_id') in wolf_players
             and any(k in s.get('content', '') for k in leak_kw)]
    check("狼人不自曝", len(leaks) == 0, f"{len(leaks)} 条泄露发言")

    deaths = [e for e in room.game_events if e.get('event_type') == 'player_death']
    alive_at_end = len(room.engine.state.alive_players)
    check("死亡数一致", len(deaths) == 12 - alive_at_end,
          f"死亡{len(deaths)} 存活{alive_at_end}")

    calls = len(room.game_reasonings)
    check("LLM调用 <=600", calls <= 600, f"{calls} 次")

    death_with_role = [d for d in deaths if d.get('metadata', {}).get('role')]
    check("死亡事件含角色", len(death_with_role) == len(deaths),
          f"{len(death_with_role)}/{len(deaths)}")

    passed = sum(1 for _, c, _ in RESULTS if c)
    print(f"\n=== 验收: {passed}/{len(RESULTS)} 项通过 ===", flush=True)
    print("SMOKE ACCEPTED" if passed == len(RESULTS) else "SMOKE REJECTED", flush=True)

asyncio.run(main())
