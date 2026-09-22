from backend.app.agents.base import BaseAgent
from backend.app.core.prompts import SAFETY_CONSENT_AGENT_PROMPT

class SafetyConsentAgent(BaseAgent):
    name: str = "safety_consent_agent"
    description: str = (
        "Answers questions about consent, healthy relationships, sexual violence, "
        "coercion, boundaries, emotional health, and emergency support."
    )
    system_prompt: str = SAFETY_CONSENT_AGENT_PROMPT
