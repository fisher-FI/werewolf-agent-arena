"""完整对局冒烟：真 LLM 12 人预女猎守，跑完为止"""
import asyncio, sys, os, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                    handlers=[logging.FileHandler("smoke.log", encoding="utf-8")])

os.environ['XIAOMI_API_KEY'] = 'sk-3sI92baHekMZohmnAbWqEBD2iPSlVBkKL38iaF0n7CBS0IouMbmVCXS3s6J1kDva'
os.environ['XIAOMI_BASE_URL'] = 'https://opencode.ai/zen/go/v1'

from engine.models import Player, AIConfig
from ai.orchestrator import Room

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

    start = asyncio.get_event_loop().time()
    try:
        await asyncio.wait_for(room.start_game(), timeout=1500)
    except asyncio.TimeoutError:
        print(f"TIMEOUT: phase={room.engine.state.phase} day={room.engine.state.day_count}")
        return
    elapsed = asyncio.get_event_loop().time() - start
    w = room.engine.state.winner
    print(f"DONE in {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"days={room.engine.state.day_count} winner={w.value} reason={room.engine.state.winner_reason}")
    print(f"llm_calls={len(room.game_reasonings)} events={len(room.game_events)}")
    deaths = [e for e in room.game_events if e.get('event_type') == 'player_death']
    for d in deaths:
        print(f"  DEATH: {d.get('content')}")
    # 检查发言质量
    speeches = [e for e in room.game_events if e.get('event_type') == 'player_speech']
    empty = [s for s in speeches if not s.get('content') or s.get('content') == '[本回合未发言]']
    print(f"speeches={len(speeches)} empty_or_placeholder={len(empty)}")

asyncio.run(main())
