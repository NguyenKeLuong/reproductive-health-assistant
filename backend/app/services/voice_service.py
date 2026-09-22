import asyncio
import base64
import logging
from typing import Optional, List, Dict
from fastapi import WebSocket

from backend.app.services.nvidia_service import NvidiaNIMService

logger = logging.getLogger("voice_service")

class VoiceCallSession:
    """
    Manages a real-time duplex voice call session over WebSocket.
    Features:
      - Raw audio chunks buffering and concatenation
      - Speech-to-Text (STT) with Whisper / fallback
      - LLM/VLM reasoning with image context support
      - Text-to-Speech (TTS) synthesis
      - User interruption detection & ongoing task cancellation
    """

    def __init__(self, websocket: WebSocket, nvidia_service: NvidiaNIMService):
        self.websocket = websocket
        self.nvidia_service = nvidia_service
        self.audio_chunks: List[bytes] = []
        self.call_history: List[Dict[str, str]] = []
        self.active_image_bytes: Optional[bytes] = None
        self.active_task: Optional[asyncio.Task] = None

    async def handle_start(self) -> None:
        logger.info("Voice Call Session Started")
        self.audio_chunks.clear()
        self.call_history.clear()
        self.active_image_bytes = None
        await self.websocket.send_json({"type": "system", "message": "Call connected successfully"})

    def handle_audio_chunk(self, base64_data: str) -> None:
        if base64_data:
            chunk_bytes = base64.b64decode(base64_data)
            self.audio_chunks.append(chunk_bytes)

    async def handle_image(self, base64_data: str) -> None:
        if base64_data:
            if "," in base64_data:
                base64_data = base64_data.split(",")[1]
            self.active_image_bytes = base64.b64decode(base64_data)
            logger.info("Received image for VLM analysis during voice call")
            await self.websocket.send_json({"type": "system", "message": "Image received for analysis"})

    async def handle_speech_done(self) -> None:
        if not self.audio_chunks:
            return

        full_audio = b"".join(self.audio_chunks)
        self.audio_chunks.clear()

        await self.websocket.send_json({"type": "ai_status", "status": "transcribing"})
        user_text = await self.nvidia_service.speech_to_text(full_audio)
        logger.info(f"Voice Call transcription result: {user_text}")

        if not user_text.strip():
            await self.websocket.send_json({"type": "ai_status", "status": "idle"})
            return

        await self.websocket.send_json({"type": "user_transcription", "text": user_text})
        self._dispatch_response_generation(user_text)

    async def handle_speech_text(self, user_text: str) -> None:
        if not user_text.strip():
            await self.websocket.send_json({"type": "ai_status", "status": "idle"})
            return

        await self.websocket.send_json({"type": "user_transcription", "text": user_text})
        self._dispatch_response_generation(user_text)

    async def handle_interrupt(self) -> None:
        logger.info("Received INTERRUPT signal from client")
        if self.active_task and not self.active_task.done():
            self.active_task.cancel()
            logger.info("Cancelled ongoing AI speech generation task")
        self.audio_chunks.clear()
        await self.websocket.send_json({"type": "ai_status", "status": "idle"})

    def _dispatch_response_generation(self, user_text: str) -> None:
        consumed_image = self.active_image_bytes
        self.active_image_bytes = None
        self.active_task = asyncio.create_task(
            self._generate_and_speak_response(user_text, consumed_image)
        )

    async def _generate_and_speak_response(self, user_text: str, image_bytes: Optional[bytes]) -> None:
        try:
            await self.websocket.send_json({"type": "ai_status", "status": "thinking"})
            
            ai_text = await self.nvidia_service.chat_completion(
                message=user_text,
                history=self.call_history,
                image_bytes=image_bytes
            )
            
            await self.websocket.send_json({"type": "ai_transcription", "text": ai_text})
            await self.websocket.send_json({"type": "ai_status", "status": "speaking"})
            
            audio_bytes = await self.nvidia_service.text_to_speech(ai_text)
            if audio_bytes:
                audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
                await self.websocket.send_json({
                    "type": "audio_response",
                    "audio": f"data:audio/wav;base64,{audio_b64}"
                })
            else:
                logger.warning("TTS returned empty audio. Falling back to client-side synthesis.")

            self.call_history.append({"role": "user", "content": user_text})
            self.call_history.append({"role": "assistant", "content": ai_text})
            if len(self.call_history) > 20:
                self.call_history = self.call_history[-20:]

            await self.websocket.send_json({"type": "ai_status", "status": "idle"})

        except asyncio.CancelledError:
            logger.info("Response generation task cancelled due to user interruption")
            try:
                await self.websocket.send_json({"type": "ai_status", "status": "idle"})
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Error in speech response pipeline: {e}")
            try:
                await self.websocket.send_json({"type": "error", "message": str(e)})
                await self.websocket.send_json({"type": "ai_status", "status": "idle"})
            except Exception:
                pass

    def close(self) -> None:
        if self.active_task and not self.active_task.done():
            self.active_task.cancel()
