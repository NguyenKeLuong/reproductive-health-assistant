from backend.app.agents.base import BaseAgent
from backend.app.core.prompts import GENERAL_HEALTH_PROMPT

class GeneralHealthAgent(BaseAgent):
    name: str = "general_health_agent"
    description: str = (
        "Answers broad questions on sexual health, anatomy, hygiene, puberty, "
        "wellness, and general sexual development."
    )
    system_prompt: str = GENERAL_HEALTH_PROMPT
