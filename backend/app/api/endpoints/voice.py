import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.services.nvidia_service import NvidiaNIMService
from backend.app.services.voice_service import VoiceCallSession

logger = logging.getLogger("voice_endpoint")
router = APIRouter()

nvidia_service = NvidiaNIMService()

@router.websocket("/ws/voice-call")
async def websocket_voice_call(websocket: WebSocket):
    """
    WebSocket endpoint for real-time duplex 1-1 voice consultation:
      - Interruption detection & VAD
      - Audio chunk buffering
      - Speech-to-Text, LLM/VLM generation, Text-to-Speech
    """
    await websocket.accept()
    logger.info("Voice Call WebSocket connected")
    session = VoiceCallSession(websocket=websocket, nvidia_service=nvidia_service)

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")

            if msg_type == "start":
                await session.handle_start()
            elif msg_type == "audio_chunk":
                session.handle_audio_chunk(message.get("data", ""))
            elif msg_type == "image":
                await session.handle_image(message.get("data", ""))
            elif msg_type == "speech_done":
                await session.handle_speech_done()
            elif msg_type == "speech_text":
                await session.handle_speech_text(message.get("text", ""))
            elif msg_type == "interrupt":
                await session.handle_interrupt()

    except WebSocketDisconnect:
        logger.info("Voice Call client disconnected")
        session.close()
    except Exception as e:
        logger.error(f"Voice Call Error: {e}")
        session.close()
