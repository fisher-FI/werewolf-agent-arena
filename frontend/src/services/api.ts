const API_BASE = '';

export async function fetchJSON(path: string, options?: RequestInit) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  return res.json();
}

export const api = {
  // Config
  getDefaultAI: () => fetchJSON('/api/config/default-ai'),
  updateDefaultAI: (data: any) => fetchJSON('/api/config/default-ai', { method: 'PUT', body: JSON.stringify(data) }),

  // Rooms
  listRooms: () => fetchJSON('/api/rooms'),
  createRoom: () => fetchJSON('/api/rooms', { method: 'POST' }),
  getRoom: (id: string) => fetchJSON(`/api/rooms/${id}`),
  deleteRoom: (id: string) => fetchJSON(`/api/rooms/${id}`, { method: 'DELETE' }),

  // Players
  addPlayer: (roomId: string, data: any) => fetchJSON(`/api/rooms/${roomId}/players`, { method: 'POST', body: JSON.stringify(data) }),
  removePlayer: (roomId: string, playerId: string) => fetchJSON(`/api/rooms/${roomId}/players/${playerId}`, { method: 'DELETE' }),

  // Game
  startGame: (roomId: string) => fetchJSON(`/api/rooms/${roomId}/start`, { method: 'POST' }),
  pauseGame: (roomId: string) => fetchJSON(`/api/rooms/${roomId}/pause`, { method: 'POST' }),
  resumeGame: (roomId: string) => fetchJSON(`/api/rooms/${roomId}/resume`, { method: 'POST' }),
  humanInput: (roomId: string, data: any) => fetchJSON(`/api/rooms/${roomId}/input`, { method: 'POST', body: JSON.stringify(data) }),
};

// WebSocket connection
export function connectWS(roomId: string, onMessage: (msg: any) => void): WebSocket {
  const clientId = Math.random().toString(36).slice(2, 10);
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${protocol}//${location.host}/ws/${roomId}?client_id=${clientId}`);
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      onMessage(msg);
    } catch {}
  };
  ws.onerror = (e) => console.error('WebSocket error:', e);
  return ws;
}
