import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../services/api';
import './Lobby.css';

export default function Lobby() {
  const [rooms, setRooms] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const loadRooms = async () => {
    try {
      const data = await api.listRooms();
      setRooms(data);
    } catch (e) { console.error(e); }
  };

  useEffect(() => { loadRooms(); }, []);

  const createRoom = async () => {
    setLoading(true);
    try {
      const room = await api.createRoom();
      navigate(`/room/${room.id}`);
    } catch (e) { alert('创建房间失败'); }
    setLoading(false);
  };

  return (
    <div className="lobby">
      <div className="lobby-hero">
        <h1>🐺 AI 狼人杀</h1>
        <p>多个 AI 模型同台对弈，观察它们如何推理、伪装和欺骗</p>
        <button className="btn-primary btn-lg" onClick={createRoom} disabled={loading}>
          {loading ? '创建中...' : '+ 创建新房间'}
        </button>
      </div>

      {rooms.length > 0 && (
        <div className="room-list">
          <h2>进行中的房间</h2>
          {rooms.map(room => (
            <div key={room.id} className="room-card" onClick={() => navigate(`/room/${room.id}`)}>
              <div className="room-info">
                <span className="room-id">#{room.id}</span>
                <span className={`room-status status-${room.status}`}>
                  {room.status === 'waiting' ? '等待中' : room.status === 'playing' ? '进行中' : '已结束'}
                </span>
              </div>
              <div className="room-players">
                {room.player_count}/9 玩家
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
