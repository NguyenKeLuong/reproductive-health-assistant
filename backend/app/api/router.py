from fastapi import APIRouter
from backend.app.api.endpoints.chat import router as chat_router
from backend.app.api.endpoints.voice import router as voice_router

api_router = APIRouter()
api_router.include_router(chat_router)
api_router.include_router(voice_router)
