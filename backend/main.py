"""狼人杀 AI 对局平台 — FastAPI 后端入口"""

from __future__ import annotations
import json
import asyncio
import logging
import uuid
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional
from pydantic import BaseModel

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from engine.models import Player, AIConfig, Role
from engine.boards import BOARDS, get_board
from ai.orchestrator import Room, RoomManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("werewolf")

manager = RoomManager()


def _load_env_file(path: str = None):
    """手动解析 .env（零依赖）"""
    path = path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 加载 .env 环境变量
    _load_env_file()
    # 启动时加载默认 API key
    api_key = os.getenv("XIAOMI_API_KEY", "")
    base_url = os.getenv("XIAOMI_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
    model = os.getenv("XIAOMI_MODEL", "deepseek-v4-flash")
    if api_key:
        manager.default_ai_config.api_key = api_key
        manager.default_ai_config.base_url = base_url
        manager.default_ai_config.model = model
    logger.info(f"Default AI: {manager.default_ai_config.provider}/{manager.default_ai_config.model}")
    yield


app = FastAPI(title="Werewolf AI", lifespan=lifespan)

# 静态文件（前端构建产物）
static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(static_dir):
    app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="assets")


# ─── Pydantic 模型 ───

class CreateRoomReq(BaseModel):
    board_id: Optional[str] = None

class AddPlayerReq(BaseModel):
    name: str
    seat: int
    player_type: str = "ai"
    ai_config: Optional[dict] = None

class UpdateAIConfigReq(BaseModel):
    provider: str = "xiaomi"
    model: str = "mimo-v2.5-pro"
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.8
    personality: str = "一个聪明、善于推理的玩家"
    max_tokens: int = 500

class HumanInputReq(BaseModel):
    player_id: str
    content: str
    input_type: str = "speech"


# ─── API 路由 ───

@app.get("/")
async def index():
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Werewolf AI Server Running", "docs": "/docs"}


@app.get("/api/config/default-ai")
async def get_default_ai_config():
    return manager.default_ai_config.to_dict()


@app.put("/api/config/default-ai")
async def update_default_ai_config(req: UpdateAIConfigReq):
    cfg = manager.default_ai_config
    cfg.provider = req.provider
    cfg.model = req.model
    if req.api_key:
        cfg.api_key = req.api_key
    if req.base_url:
        cfg.base_url = req.base_url
    cfg.temperature = req.temperature
    cfg.personality = req.personality
    cfg.max_tokens = req.max_tokens
    return cfg.to_dict()


@app.post("/api/rooms")
async def create_room(req: CreateRoomReq = None):
    req = req or CreateRoomReq()
    room = manager.create_room(req.board_id)
    return room.to_dict()


@app.get("/api/boards")
async def list_boards():
    """列出可用板子配置"""
    return [
        {"id": b.id, "name": b.name, "desc": b.desc,
         "player_count": b.player_count,
         "roles": [r.value for r in b.roles]}
        for b in BOARDS.values()
    ]


@app.get("/api/rooms")
async def list_rooms():
    return manager.list_rooms()


@app.get("/api/rooms/{room_id}")
async def get_room(room_id: str):
    room = manager.get_room(room_id)
    if not room:
        raise HTTPException(404, "Room not found")
    return room.to_dict()


@app.post("/api/rooms/{room_id}/players")
async def add_player(room_id: str, req: AddPlayerReq):
    room = manager.get_room(room_id)
    if not room:
        raise HTTPException(404, "Room not found")

    ai_cfg = None
    if req.player_type == "ai":
        cfg = manager.default_ai_config
        if req.ai_config:
            ai_cfg = AIConfig(
                provider=req.ai_config.get("provider", cfg.provider),
                model=req.ai_config.get("model", cfg.model),
                api_key=req.ai_config.get("api_key", cfg.api_key),
                base_url=req.ai_config.get("base_url", cfg.base_url),
                temperature=req.ai_config.get("temperature", cfg.temperature),
                personality=req.ai_config.get("personality", cfg.personality),
                max_tokens=req.ai_config.get("max_tokens", cfg.max_tokens),
            )
        else:
            ai_cfg = AIConfig(
                provider=cfg.provider, model=cfg.model,
                api_key=cfg.api_key, base_url=cfg.base_url,
                temperature=cfg.temperature, personality=cfg.personality,
                max_tokens=cfg.max_tokens,
            )

    player = Player(
        id=uuid.uuid4().hex[:8],
        name=req.name,
        seat=req.seat,
        player_type=req.player_type,
        ai_config=ai_cfg,
    )
    if not room.add_player(player):
        raise HTTPException(400, "Cannot add player (room full or game started)")
    return player.to_dict()


@app.delete("/api/rooms/{room_id}/players/{player_id}")
async def remove_player(room_id: str, player_id: str):
    room = manager.get_room(room_id)
    if not room:
        raise HTTPException(404, "Room not found")
    room.remove_player(player_id)
    return {"ok": True}


@app.post("/api/rooms/{room_id}/start")
async def start_game(room_id: str):
    room = manager.get_room(room_id)
    if not room:
        raise HTTPException(404, "Room not found")
    if len(room.players) != room.max_players:
        raise HTTPException(400, f"板子 {room.board.name} 需要 {room.max_players} 个玩家，当前 {len(room.players)} 人")
    # 初始化 AI 适配器
    room.setup_ai_adapters(manager.default_ai_config)
    # 启动游戏（后台任务）
    asyncio.create_task(room.start_game())
    return {"ok": True, "message": "Game starting..."}


@app.post("/api/rooms/{room_id}/input")
async def human_input(room_id: str, req: HumanInputReq):
    room = manager.get_room(room_id)
    if not room:
        raise HTTPException(404, "Room not found")
    room.receive_human_input(req.player_id, req.content, req.input_type)
    return {"ok": True}


@app.post("/api/rooms/{room_id}/pause")
async def pause_game(room_id: str):
    room = manager.get_room(room_id)
    if not room:
        raise HTTPException(404, "房间不存在")
    room.paused = True
    await room.broadcast("game_paused", {"paused": True})
    return {"ok": True, "paused": True}


@app.post("/api/rooms/{room_id}/resume")
async def resume_game(room_id: str):
    room = manager.get_room(room_id)
    if not room:
        raise HTTPException(404, "房间不存在")
    room.paused = False
    await room.broadcast("game_paused", {"paused": False})
    return {"ok": True, "paused": False}


@app.delete("/api/rooms/{room_id}")
async def delete_room(room_id: str):
    manager.delete_room(room_id)
    return {"ok": True}


# ─── WebSocket ───

class ConnectionManager:
    """管理 WebSocket 连接"""
    def __init__(self):
        self.connections: dict[str, dict[str, WebSocket]] = {}  # room_id -> {client_id: ws}

    async def connect(self, room_id: str, client_id: str, ws: WebSocket):
        await ws.accept()
        if room_id not in self.connections:
            self.connections[room_id] = {}
        self.connections[room_id][client_id] = ws

    def disconnect(self, room_id: str, client_id: str):
        if room_id in self.connections:
            self.connections[room_id].pop(client_id, None)

    async def broadcast(self, room_id: str, event_type: str, data: dict):
        if room_id not in self.connections:
            return
        message = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
        dead = []
        for cid, ws in self.connections[room_id].items():
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self.connections[room_id].pop(cid, None)


ws_manager = ConnectionManager()


@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    client_id = websocket.query_params.get("client_id", uuid.uuid4().hex[:8])
    await ws_manager.connect(room_id, client_id, websocket)

    # 设置房间的广播回调
    room = manager.get_room(room_id)
    if room:
        async def broadcast_fn(event_type: str, data: dict):
            await ws_manager.broadcast(room_id, event_type, data)
        room.set_broadcast(broadcast_fn)
        room.connected_clients += 1

        # 发送当前房间状态
        await websocket.send_text(json.dumps({
            "type": "room_state",
            "data": room.to_dict(),
        }, ensure_ascii=False))

        # 发送历史事件（重连回放）
        if room.status == "playing" or room.status == "finished":
            await room.send_history(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type")

            if msg_type == "human_input" and room:
                room.receive_human_input(
                    msg.get("player_id"),
                    msg.get("content"),
                    msg.get("input_type", "speech"),
                )
    except WebSocketDisconnect:
        ws_manager.disconnect(room_id, client_id)
        if room:
            room.connected_clients = max(0, room.connected_clients - 1)
            # 所有客户端断开时自动暂停
            if room.connected_clients <= 0 and room.status == "playing" and not room.paused:
                room.paused = True
                logger.info(f"房间 {room_id} 无客户端连接，自动暂停")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(room_id, client_id)
        if room:
            room.connected_clients = max(0, room.connected_clients - 1)


# ─── SPA catch-all: serve index.html for client-side routes ───

@app.get("/{full_path:path}")
async def spa_catchall(full_path: str):
    """Serve static files or fallback to index.html for SPA routing"""
    # Try to serve as static file first
    file_path = os.path.join(static_dir, full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    # Fallback to index.html for SPA routes
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Werewolf AI Server Running", "docs": "/docs"}
