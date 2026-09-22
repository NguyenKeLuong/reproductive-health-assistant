from backend.app.agents.base import BaseAgent
from backend.app.core.prompts import REPRODUCTIVE_HEALTH_AGENT_PROMPT

class ReproductiveHealthAgent(BaseAgent):
    name: str = "reproductive_health_agent"
    description: str = (
        "Answers questions about reproductive health, menstrual cycles, "
        "pregnancy, fertility, ovulation, PCOS, endometriosis, menopause, "
        "and reproductive anatomy/biology."
    )
    system_prompt: str = REPRODUCTIVE_HEALTH_AGENT_PROMPT
