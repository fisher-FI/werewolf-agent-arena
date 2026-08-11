import asyncio, sys, os
sys.path.insert(0, '.')
os.environ['XIAOMI_API_KEY'] = 'sk-3sI92baHekMZohmnAbWqEBD2iPSlVBkKL38iaF0n7CBS0IouMbmVCXS3s6J1kDva'
os.environ['XIAOMI_BASE_URL'] = 'https://opencode.ai/zen/go/v1'

from engine.models import Player, AIConfig
from ai.orchestrator import Room

async def main():
    cfg = AIConfig(provider='deepseek', model='deepseek-v4-flash',
                   api_key=os.environ['XIAOMI_API_KEY'],
                   base_url=os.environ['XIAOMI_BASE_URL'],
                   temperature=0.7, max_tokens=600)
    room = Room(board_id='ywls')
    for i in range(1, 13):
        room.add_player(Player(id=f'p{i}', name=f'玩家{i}', seat=i, player_type='ai'))
    room.setup_ai_adapters(cfg)
    room.delay_factor = 0.0
    start = asyncio.get_event_loop().time()
    await asyncio.wait_for(room.start_game(), timeout=900)
    elapsed = asyncio.get_event_loop().time() - start
    w = room.engine.state.winner
    print(f"\n=== 对局完成 ===")
    print(f"耗时: {elapsed:.0f}秒 ({elapsed/60:.1f}分钟)")
    print(f"天数: {room.engine.state.day_count}")
    print(f"胜者: {w.value}, 原因: {room.engine.state.winner_reason}")
    print(f"LLM 调用: {len(room.game_reasonings)} 次, 事件: {len(room.game_events)} 条")
    # 死亡记录
    for e in room.game_events:
        if e.get('event_type') == 'player_death':
            print(f"  💀 {e.get('content')}")
    # 最后3个事件
    for e in room.game_events[-3:]:
        print(f"  [末] {e.get('event_type')}: {e.get('content','')[:60]}")

asyncio.run(main())
