"""
WebSocket endpoint — pushes live job data to the browser every 60s
"""
import asyncio
import json
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

# Track all connected clients
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)

manager = ConnectionManager()


@router.websocket("/trends")
async def websocket_trends(websocket: WebSocket):
    """
    Client connects → receives fresh job trend data every 60 seconds.
    Frontend JS: const ws = new WebSocket('ws://localhost:8000/ws/trends')
    """
    await manager.connect(websocket)
    try:
        while True:
            data = await _get_live_snapshot()
            await websocket.send_json(data)
            await asyncio.sleep(60)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@router.websocket("/risk/{role}")
async def websocket_risk(websocket: WebSocket, role: str):
    """Stream live risk score updates for a specific role."""
    await manager.connect(websocket)
    try:
        while True:
            from ml.risk_model import predict_career_risk
            result = predict_career_risk(role=role, years_exp=3, skill_list=[])
            await websocket.send_json({
                "role":           result.role,
                "risk_score":     result.risk_score,
                "risk_category":  result.risk_category,
                "timestamp":      datetime.utcnow().isoformat(),
            })
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


async def _get_live_snapshot() -> dict:
    """Fetch fresh data from free APIs for the dashboard."""
    try:
        from data.live_feeds import fetch_remoteok_jobs
        remote = await fetch_remoteok_jobs("data")
        return {
            "type":            "trend_update",
            "remote_postings": remote.get("total_postings", 0),
            "timestamp":       datetime.utcnow().isoformat(),
        }
    except Exception:
        return {"type": "heartbeat", "timestamp": datetime.utcnow().isoformat()}
