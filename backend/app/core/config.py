import os
from pathlib import Path
from dotenv import load_dotenv

# Ensure environment variables are loaded from root .env
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

if ENV_FILE.exists():
    load_dotenv(dotenv_path=ENV_FILE)
else:
    load_dotenv()

class Settings:
    PROJECT_NAME: str = "Reproductive Health Assistant API"
    PROJECT_DESCRIPTION: str = "API for routing sexual health questions to specialized agents with VLM & Voice Call."
    VERSION: str = "1.0.0"
    
    # Core LLM API (OpenAI-compatible / FPT Cloud)
    API_URL: str = os.getenv("API_URL", "").strip()
    API_KEY: str = os.getenv("API_KEY", "").strip()
    MODEL_NAME: str = os.getenv("MODEL_NAME", "").strip()
    
    # NVIDIA NIM APIs
    NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "").strip()
    NVIDIA_API_KEY_2: str = os.getenv("NVIDIA_API_KEY_2", "").strip()
    NVIDIA_API_KEY_3: str = os.getenv("NVIDIA_API_KEY_3", "").strip()
    NVIDIA_SPEECH_API_URL: str = os.getenv("NVIDIA_SPEECH_API_URL", "https://integrate.api.nvidia.com/v1").strip()
    
    # Server & Paths
    PORT: int = int(os.getenv("PORT", "8010"))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    
    # Frontend build location
    FRONTEND_DIST_DIR: Path = PROJECT_ROOT / "health-chat-companion" / "dist"

    def validate(self) -> None:
        """Validate required configuration at startup."""
        missing = []
        if not self.API_URL:
            missing.append("API_URL")
        if not self.MODEL_NAME:
            missing.append("MODEL_NAME")
        if missing:
            raise ValueError(f"Missing required environment variables in .env: {', '.join(missing)}")

settings = Settings()

# Direct variable exports for backward compatibility
API_URL = settings.API_URL
API_KEY = settings.API_KEY
MODEL_NAME = settings.MODEL_NAME
NVIDIA_API_KEY = settings.NVIDIA_API_KEY
NVIDIA_API_KEY_2 = settings.NVIDIA_API_KEY_2
NVIDIA_API_KEY_3 = settings.NVIDIA_API_KEY_3
NVIDIA_SPEECH_API_URL = settings.NVIDIA_SPEECH_API_URL
PORT = settings.PORT
HOST = settings.HOST
