import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.tree_service import tree_service
from app.services.ws_manager import manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/tree")
async def ws_tree(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        snapshot = await tree_service.snapshot_message()
        await websocket.send_json(snapshot.model_dump(mode="json"))

        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            if msg_type == "request_snapshot":
                snapshot = await tree_service.snapshot_message()
                await websocket.send_json(snapshot.model_dump(mode="json"))
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ws /ws/tree connection error")
    finally:
        await manager.disconnect(websocket)
