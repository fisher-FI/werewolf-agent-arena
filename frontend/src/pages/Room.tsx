import { useState, useEffect, useRef, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api, connectWS } from '../services/api';
import { ROLE_EMOJI, ROLE_LABEL, TEAM_LABEL, getTeam } from '../constants/roles';
import './Room.css';

export default function Room() {
  const { roomId } = useParams<{ roomId: string }>();
  const navigate = useNavigate();
  const [room, setRoom] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [reasonings, setReasonings] = useState<any[]>([]);
  const [phase, setPhase] = useState('waiting');
  const [dayCount, setDayCount] = useState(0);
  const [gameOver, setGameOver] = useState<any>(null);
  const [addingSeat, setAddingSeat] = useState<number | null>(null);
  const [newName, setNewName] = useState('');
  const [selectedPlayer, setSelectedPlayer] = useState<string | null>(null);
  const [isPaused, setIsPaused] = useState(false);
  const [currentSpeaker, setCurrentSpeaker] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'timeline' | 'reasoning'>('timeline');
  const timelineRef = useRef<HTMLDivElement>(null);
  const reasoningRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const loadRoom = async () => {
    if (!roomId) return;
    try {
      const data = await api.getRoom(roomId);
      setRoom(data);
      if (data.paused !== undefined) setIsPaused(data.paused);
      if (data.phase) setPhase(data.phase);
      if (data.day_count) setDayCount(data.day_count);
    } catch (e) { console.error(e); }
  };

  useEffect(() => { loadRoom(); }, [roomId]);

  useEffect(() => {
    if (!roomId) return;
    const ws = connectWS(roomId, (msg) => {
      switch (msg.type) {
        case 'room_state':
          setRoom(msg.data);
          break;
        case 'game_event':
          if (msg.data.event_type === 'player_death' && msg.data.player_id) {
            setRoom((prev: any) => {
              if (!prev) return prev;
              const players = prev.players.map((p: any) =>
                p.id === msg.data.player_id ? { ...p, is_alive: false } : p
              );
              return { ...prev, players };
            });
          }
          setEvents(prev => [...prev, msg.data]);
          break;
        case 'ai_reasoning':
          setReasonings(prev => [...prev, msg.data]);
          break;
        case 'role_assigned':
          setRoom((prev: any) => {
            if (!prev) return prev;
            const players = prev.players.map((p: any) =>
              p.id === msg.data.player_id
                ? { ...p, role: msg.data.role, role_label: msg.data.role_label, role_emoji: msg.data.role_emoji, team: msg.data.team }
                : p
            );
            return { ...prev, players };
          });
          break;
        case 'phase_change':
          setPhase(msg.data.phase);
          setDayCount(msg.data.day_count);
          setEvents(prev => [...prev, {
            event_type: 'phase_change',
            content: msg.data.content,
            phase: msg.data.phase,
            day_count: msg.data.day_count,
            timestamp: new Date().toISOString(),
          }]);
          break;
        case 'game_start':
          setRoom((prev: any) => prev ? { ...prev, status: 'playing', players: msg.data.players, board: msg.data.board } : prev);
          setEvents([]);
          setReasonings([]);
          break;
        case 'game_end':
          setGameOver(msg.data);
          setPhase('gameover');
          break;
        case 'game_paused':
          setIsPaused(msg.data.paused);
          break;
        case 'current_speaker':
          setCurrentSpeaker(msg.data.player_id || null);
          break;
      }
    });
    wsRef.current = ws;
    return () => ws.close();
  }, [roomId]);

  // 自动滚动
  useEffect(() => {
    if (activeTab === 'timeline' && timelineRef.current) {
      timelineRef.current.scrollTop = timelineRef.current.scrollHeight;
    }
  }, [events, activeTab]);

  useEffect(() => {
    if (activeTab === 'reasoning' && reasoningRef.current) {
      reasoningRef.current.scrollTop = reasoningRef.current.scrollHeight;
    }
  }, [reasonings, activeTab]);

  const playerMap = useMemo(() => {
    const map: Record<string, any> = {};
    room?.players?.forEach((p: any) => { map[p.id] = p; });
    return map;
  }, [room]);

  const seatMap = useMemo(() => {
    const map: Record<number, any> = {};
    room?.players?.forEach((p: any) => { map[p.seat] = p; });
    return map;
  }, [room]);

  // 动态座位：按人数均分左右两列（人数不硬编码）
  const { leftSeats, rightSeats } = useMemo(() => {
    const maxPlayers = room?.board?.max_players || room?.players?.length || 12;
    const seats = Array.from({ length: maxPlayers }, (_, i) => i + 1);
    const mid = Math.ceil(seats.length / 2);
    return { leftSeats: seats.slice(0, mid), rightSeats: seats.slice(mid) };
  }, [room]);

  // 按阶段/天数分组的事件时间线
  const timelineGroups = useMemo(() => {
    const groups: { label: string; events: any[] }[] = [];
    let currentKey = '';
    for (const evt of events) {
      const key = `${evt.day_count || 0}-${evt.phase || 'system'}`;
      if (key !== currentKey) {
        const phaseLabel = evt.phase === 'night' ? `🌙 第${evt.day_count}个夜晚`
          : evt.phase === 'night_resolve' ? `🌙 第${evt.day_count}夜 · 结算`
          : evt.phase === 'shoot' ? `🔫 开枪时刻`
          : evt.phase === 'day_discuss' ? `☀️ 第${evt.day_count}天 · 讨论`
          : evt.phase === 'day_vote' ? `🗳️ 第${evt.day_count}天 · 投票`
          : evt.phase === 'day_resolve' ? `🗳️ 第${evt.day_count}天 · 结算`
          : evt.event_type === 'game_end' ? '🏁 游戏结束'
          : '';
        groups.push({ label: phaseLabel, events: [] });
        currentKey = key;
      }
      groups[groups.length - 1].events.push(evt);
    }
    return groups;
  }, [events]);

  const addAIPlayer = async (seat: number) => {
    if (!roomId) return;
    const name = newName.trim() || `玩家${seat}号`;
    try {
      await api.addPlayer(roomId, { name, seat, player_type: 'ai' });
      setAddingSeat(null);
      setNewName('');
      loadRoom();
    } catch (e: any) { alert(e.message); }
  };

  const removePlayer = async (playerId: string) => {
    if (!roomId) return;
    try {
      await api.removePlayer(roomId, playerId);
      loadRoom();
    } catch (e: any) { alert(e.message); }
  };

  const startGame = async () => {
    if (!roomId) return;
    if (!confirm('确认开始游戏？')) return;
    try {
      await api.startGame(roomId);
    } catch (e: any) { alert(e.message); }
  };

  const togglePause = async () => {
    if (!roomId) return;
    try {
      if (isPaused) {
        await api.resumeGame(roomId);
      } else {
        await api.pauseGame(roomId);
      }
    } catch (e: any) { alert(e.message); }
  };

  const fillAllAI = async () => {
    if (!roomId) return;
    const maxPlayers = room?.board?.max_players || 12;
    const occupied = new Set(room?.players?.map((p: any) => p.seat) || []);
    for (let i = 1; i <= maxPlayers; i++) {
      if (!occupied.has(i)) {
        try {
          await api.addPlayer(roomId, { name: `玩家${i}号`, seat: i, player_type: 'ai' });
        } catch {}
      }
    }
    loadRoom();
  };

  const isPlaying = room?.status === 'playing';
  const isWaiting = room?.status === 'waiting';
  const playerCount = room?.players?.length || 0;
  const maxPlayers = room?.board?.max_players || 12;

  // 座位渲染
  const renderSeat = (seat: number) => {
    const player = seatMap[seat];
    const isSelected = selectedPlayer === player?.id;
    const isDead = isPlaying && player && !player.is_alive;
    const hasRole = isPlaying && player?.role;
    const isSpeaking = currentSpeaker === player?.id;
    return (
      <div
        key={seat}
        className={`seat-slot ${player ? 'occupied' : 'empty'} ${isSelected ? 'selected' : ''} ${isDead ? 'dead' : ''} ${isSpeaking ? 'speaking' : ''}`}
        onClick={() => player && isPlaying && setSelectedPlayer(isSelected ? null : player.id)}
      >
        <div className="seat-number">{seat}号</div>
        {player ? (
          <>
            <div className="seat-name">{player.name}</div>
            {isSpeaking && <div className="speaking-indicator">💬 正在发言...</div>}
            <div className="seat-badges">
              <span className={`badge ${player.player_type === 'ai' ? 'badge-ai' : 'badge-human'}`}>
                {player.player_type === 'ai' ? '智能体' : '人类'}
              </span>
              {isPlaying && (
                <span className={`badge ${player.is_alive ? 'badge-alive' : 'badge-dead'}`}>
                  {player.is_alive ? '存活' : '出局'}
                </span>
              )}
            </div>
            {hasRole && (
              <div className="seat-role">
                <span className="role-emoji">{ROLE_EMOJI[player.role] || '❓'}</span>
                <span className="role-name">{ROLE_LABEL[player.role] || player.role}</span>
                <span className={`role-team team-${getTeam(player.role)}`}>
                  {TEAM_LABEL[getTeam(player.role)]}
                </span>
              </div>
            )}
            {isWaiting && (
              <div className="seat-remove" onClick={(e) => { e.stopPropagation(); removePlayer(player.id); }}>移除</div>
            )}
          </>
        ) : (
          isWaiting && addingSeat === seat ? (
            <div className="add-form" onClick={e => e.stopPropagation()}>
              <input
                placeholder="名称"
                value={newName}
                onChange={e => setNewName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addAIPlayer(seat)}
                autoFocus
              />
              <div className="add-form-btns">
                <button className="btn-primary btn-sm" onClick={() => addAIPlayer(seat)}>添加</button>
                <button className="btn-secondary btn-sm" onClick={() => { setAddingSeat(null); setNewName(''); }}>取消</button>
              </div>
            </div>
          ) : (
            <div className="seat-empty-hint" onClick={() => setAddingSeat(seat)}>+ 添加玩家</div>
          )
        )}
      </div>
    );
  };

  // 事件渲染（全类型，简单文本，无动画）
  const renderEvent = (evt: any, idx: number) => {
    const type = evt.event_type;
    if (type === 'phase_change') return null;
    const p = evt.player_id ? playerMap[evt.player_id] : null;
    return (
      <div key={idx} className={`timeline-event event-${type}`} onClick={() => p && setSelectedPlayer(evt.player_id)}>
        {type === 'player_speech' && (
          <>
            <div className="evt-header">
              <span className="evt-avatar">{p?.role ? (ROLE_EMOJI[p.role] || '👤') : '👤'}</span>
              <span className="evt-player">{evt.player_name}</span>
              <span className="evt-seat">{p?.seat}号</span>
              {evt.metadata?.reflection && <span className="reflection-badge">🤔 二次思考</span>}
            </div>
            <div className="evt-body">{evt.content}</div>
          </>
        )}
        {type === 'vote_cast' && (
          <div className="evt-vote">
            <span className="evt-player">{evt.player_name}</span>
            <span className="vote-arrow">🗳️ →</span>
            <span className="evt-player">{evt.target_name}</span>
          </div>
        )}
        {type === 'vote_result' && <div className="evt-vote-result">📊 {evt.content}</div>}
        {type === 'player_death' && <div className="evt-death">💀 {evt.content}</div>}
        {type === 'game_end' && <div className="evt-end">🏆 {evt.content}</div>}
        {type === 'werewolf_kill' && <div className="evt-wolf-kill">🐺 {evt.content}</div>}
        {type === 'wolf_discuss' && <div className="evt-wolf-discuss">🐺💬 {evt.content}</div>}
        {type === 'seer_check' && <div className="evt-seer">🔮 {evt.content}</div>}
        {type === 'witch_save' && <div className="evt-witch">🧪 {evt.content}</div>}
        {type === 'witch_poison' && <div className="evt-witch">☠️ {evt.content}</div>}
        {type === 'guard_protect' && <div className="evt-guard">🛡️ {evt.content}</div>}
        {type === 'lovers_chain' && <div className="evt-lovers">💘 {evt.content}</div>}
        {type === 'lovers_death' && <div className="evt-lovers">💔 {evt.content}</div>}
        {type === 'hunter_shoot' && <div className="evt-hunter">🔫 {evt.content}</div>}
        {type === 'alpha_shoot' && <div className="evt-hunter">👑 {evt.content}</div>}
        {type === 'self_explode' && <div className="evt-explode">💥 {evt.content}</div>}
        {type === 'idiot_reveal' && <div className="evt-idiot">🤡 {evt.content}</div>}
        {type === 'knight_duel' && <div className="evt-knight">⚔️ {evt.content}</div>}
        {type === 'system' && <div className="evt-system">{evt.content}</div>}
        {!['player_speech','vote_cast','vote_result','player_death','game_end','werewolf_kill',
           'wolf_discuss','seer_check','witch_save','witch_poison','guard_protect','lovers_chain',
           'lovers_death','hunter_shoot','alpha_shoot','self_explode','idiot_reveal','knight_duel',
           'system','phase_change'].includes(type) && (
          <div className="evt-system">{evt.content}</div>
        )}
      </div>
    );
  };

  return (
    <div className="room-page">
      {/* 顶部栏 */}
      <div className="room-header">
        <div className="room-title">
          <h2>🐺 房间 #{roomId} {room?.board?.name && <span className="board-name">[{room.board.name}]</span>}</h2>
          <span className={`phase-badge phase-${phase}`}>
            {phase === 'waiting' && '等待中'}
            {phase === 'night' && `🌙 第${dayCount}个夜晚`}
            {phase === 'night_resolve' && `🌙 结算中`}
            {phase === 'shoot' && '🔫 开枪时刻'}
            {phase === 'day_discuss' && `☀️ 第${dayCount}天 讨论`}
            {phase === 'day_vote' && `🗳️ 第${dayCount}天 投票`}
            {phase === 'day_resolve' && `🗳️ 结算中`}
            {phase === 'gameover' && '🏁 游戏结束'}
          </span>
          {isPlaying && <span className="god-eye-badge">👁️ 上帝视角</span>}
          {isPaused && <span className="pause-badge">⏸ 已暂停</span>}
        </div>
        <div className="room-actions">
          {isWaiting && (
            <>
              <button className="btn-secondary" onClick={fillAllAI}>一键填充</button>
              <button className="btn-primary" onClick={startGame} disabled={playerCount !== maxPlayers}>
                开始游戏 ({playerCount}/{maxPlayers})
              </button>
            </>
          )}
          {isPlaying && !gameOver && (
            <button className={isPaused ? 'btn-primary' : 'btn-warning'} onClick={togglePause}>
              {isPaused ? '▶ 继续' : '⏸ 暂停'}
            </button>
          )}
          <button className="btn-secondary" onClick={() => navigate('/')}>返回大厅</button>
        </div>
      </div>

      {/* 主体：左座位 | 中间进程+推理 | 右座位 */}
      <div className="room-body">
        <div className="room-seats room-seats-left">
          {leftSeats.map(renderSeat)}
        </div>

        <div className="room-center">
          <div className="center-tabs">
            <button
              className={`tab-btn ${activeTab === 'timeline' ? 'active' : ''}`}
              onClick={() => setActiveTab('timeline')}
            >
              📜 游戏进程
            </button>
            <button
              className={`tab-btn ${activeTab === 'reasoning' ? 'active' : ''}`}
              onClick={() => setActiveTab('reasoning')}
            >
              🧠 AI 推理 ({reasonings.length})
            </button>
          </div>

          {activeTab === 'timeline' && (
            <div className="center-panel" ref={timelineRef}>
              {events.length === 0 && <div className="events-empty">等待游戏开始...</div>}
              {timelineGroups.map((group, gi) => (
                <div key={gi} className="timeline-group">
                  {group.label && <div className="timeline-phase-label">{group.label}</div>}
                  {group.events.map((evt, ei) => renderEvent(evt, ei))}
                </div>
              ))}
            </div>
          )}

          {activeTab === 'reasoning' && (
            <div className="center-panel" ref={reasoningRef}>
              {reasonings.length === 0 && <div className="events-empty">暂无推理记录</div>}
              {reasonings.map((r, idx) => {
                const p = playerMap[r.player_id];
                return (
                  <div key={idx} className="reasoning-card" onClick={() => setSelectedPlayer(r.player_id)}>
                    <div className="reasoning-header">
                      <span className="reasoning-avatar">{p?.role ? (ROLE_EMOJI[p.role] || '🤖') : '🤖'}</span>
                      <span className="reasoning-name">{r.player_name}</span>
                      <span className="reasoning-seat">{p?.seat}号</span>
                      <span className="reasoning-time">用时 {r.thinking_time}秒</span>
                    </div>
                    <div className="confidence-bar">
                      <div className="confidence-fill" style={{ width: `${(r.confidence || 0.5) * 100}%` }} />
                    </div>
                    <div className="reasoning-text">{r.reasoning}</div>
                    {r.speech && (
                      <div className="reasoning-speech">
                        <span className="label">发言内容：</span>{r.speech}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="room-seats room-seats-right">
          {rightSeats.map(renderSeat)}
        </div>
      </div>

      {/* 底部：选中玩家详情 / 游戏结束 */}
      {(selectedPlayer && playerMap[selectedPlayer]) ? (
        <div className="player-detail-bar">
          <div className="pdb-header">
            <span className="pdb-avatar">
              {playerMap[selectedPlayer]?.role ? (ROLE_EMOJI[playerMap[selectedPlayer].role] || '👤') : '👤'}
            </span>
            <span className="pdb-name">{playerMap[selectedPlayer].seat}号 · {playerMap[selectedPlayer].name}</span>
            {playerMap[selectedPlayer]?.role && (
              <span className="pdb-role">
                {ROLE_EMOJI[playerMap[selectedPlayer].role]} {ROLE_LABEL[playerMap[selectedPlayer].role]}
                <span className={`role-team team-${getTeam(playerMap[selectedPlayer].role)}`}>
                  {TEAM_LABEL[getTeam(playerMap[selectedPlayer].role)]}
                </span>
              </span>
            )}
            <span className={`badge ${playerMap[selectedPlayer].is_alive ? 'badge-alive' : 'badge-dead'}`}>
              {playerMap[selectedPlayer].is_alive ? '存活' : '出局'}
            </span>
            <button className="btn-close" onClick={() => setSelectedPlayer(null)}>✕ 关闭</button>
          </div>
        </div>
      ) : gameOver ? (
        <div className="gameover-bar">
          <span className="gameover-title">🏆 {gameOver.winner_label} 获胜！{gameOver.winner_reason && `（${gameOver.winner_reason}）`}</span>
          <div className="gameover-roles">
            {Object.entries(gameOver.roles).map(([pid, info]: [string, any]) => (
              <span key={pid} className={`gameover-role ${info.alive ? '' : 'dead'}`}>
                {info.emoji} {info.name} ({info.label}) {!info.alive && '💀'}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
