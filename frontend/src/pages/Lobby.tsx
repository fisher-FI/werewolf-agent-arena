import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import './Lobby.css';

export default function Lobby() {
  const [rooms, setRooms] = useState<any[]>([]);
  const [boards, setBoards] = useState<any[]>([]);
  const [selectedBoard, setSelectedBoard] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const loadRooms = async () => {
    try {
      const data = await api.listRooms();
      setRooms(data);
    } catch (e) { console.error(e); }
  };

  const loadBoards = async () => {
    try {
      const data = await api.listBoards();
      setBoards(data);
      if (data.length > 0) setSelectedBoard(data[0].id);
    } catch (e) { console.error(e); }
  };

  useEffect(() => { loadRooms(); loadBoards(); }, []);

  const createRoom = async () => {
    setLoading(true);
    try {
      const room = await api.createRoom(selectedBoard || undefined);
      navigate(`/room/${room.id}`);
    } catch (e) { alert('创建房间失败'); }
    setLoading(false);
  };

  return (
    <div className="lobby">
      <div className="lobby-hero">
        <h1>🐺 AI 狼人杀</h1>
        <p>多个 AI 模型同台对弈，观察它们如何推理、伪装和欺骗</p>
      </div>

      <div className="board-picker">
        <h2>选择板子</h2>
        <div className="board-list">
          {boards.map(b => (
            <div
              key={b.id}
              className={`board-card ${selectedBoard === b.id ? 'active' : ''}`}
              onClick={() => setSelectedBoard(b.id)}
            >
              <div className="board-name">{b.name}</div>
              <div className="board-desc">{b.desc}</div>
              <div className="board-count">{b.player_count} 人局</div>
            </div>
          ))}
        </div>
        <button className="btn-primary btn-lg" onClick={createRoom} disabled={loading}>
          {loading ? '创建中...' : `+ 创建房间（${boards.find(b => b.id === selectedBoard)?.name || ''}）`}
        </button>
      </div>

      {rooms.length > 0 && (
        <div className="room-list">
          <h2>进行中的房间</h2>
          {rooms.map(room => (
            <div key={room.id} className="room-card" onClick={() => navigate(`/room/${room.id}`)}>
              <div className="room-info">
                <span className="room-id">#{room.id}</span>
                <span className="room-board">{room.board?.name || ''}</span>
                <span className={`room-status status-${room.status}`}>
                  {room.status === 'waiting' ? '等待中' : room.status === 'playing' ? '进行中' : '已结束'}
                </span>
              </div>
              <div className="room-players">
                {room.player_count}/{room.board?.max_players || 12} 玩家
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
