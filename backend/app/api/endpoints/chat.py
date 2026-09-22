import base64
import logging
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from backend.app.schemas.chat import ChatRequest, ChatResponse
from backend.app.agents.coordinator import CoordinatorAgent, AGENT_REGISTRY
from backend.app.services.nvidia_service import NvidiaNIMService

logger = logging.getLogger("chat_endpoint")
router = APIRouter()

coordinator = CoordinatorAgent()
nvidia_service = NvidiaNIMService()

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    Handles standard HTTP chat request.
    Routes the message through the CoordinatorAgent with full history.
    """
    try:
        chat_history = [m.model_dump() for m in request.history] if request.history else []
        logger.info(f"New HTTP message: {request.message}")
        result = await coordinator.run(request.message, chat_history=chat_history)
        return result
    except Exception as e:
        logger.error(f"Error in /chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket endpoint for real-time streaming chat:
      - Text streaming via CoordinatorAgent routing
      - Clinical image analysis streaming via Nvidia NIM VLM
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            user_message = data.get("message")
            chat_history = data.get("history", [])
            image_base64 = data.get("image")

            if not user_message and not image_base64:
                continue

            # Case A: VLM Image Analysis
            if image_base64:
                if "," in image_base64:
                    image_base64 = image_base64.split(",")[1]

                try:
                    image_bytes = base64.b64decode(image_base64)
                except Exception as decode_err:
                    logger.error(f"Failed to decode base64 image: {decode_err}")
                    await websocket.send_json({"type": "error", "detail": "Lỗi giải mã hình ảnh."})
                    continue

                await websocket.send_json({"type": "info", "message": "Đang phân tích hình ảnh cận cảnh bằng Nvidia NIM VLM..."})

                full_answer = ""
                async for token in nvidia_service.chat_completion_stream(
                    user_message or "Phân tích hình ảnh sinh lý này.",
                    history=chat_history,
                    image_bytes=image_bytes,
                ):
                    full_answer += token
                    await websocket.send_json({"type": "token", "content": token})

                await websocket.send_json({"type": "done", "content": full_answer})

            # Case B: Specialized Multi-Agent Routing
            else:
                agent_name = await coordinator.get_route(user_message, chat_history=chat_history)
                await websocket.send_json({"type": "info", "message": f"Routed to: {agent_name}"})

                agent = AGENT_REGISTRY.get(agent_name, AGENT_REGISTRY["general_health_agent"])

                full_answer = ""
                async for token in agent.run_stream(user_message, chat_history=chat_history):
                    full_answer += token
                    await websocket.send_json({"type": "token", "content": token})

                await websocket.send_json({"type": "done", "content": full_answer})

    except WebSocketDisconnect:
        logger.info("Chat WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket Error: {e}")
        try:
            await websocket.send_json({"type": "error", "detail": str(e)})
        except Exception:
            pass
