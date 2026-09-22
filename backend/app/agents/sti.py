from backend.app.agents.base import BaseAgent
from backend.app.core.prompts import STI_AGENT_PROMPT

class STIAgent(BaseAgent):
    name: str = "sti_agent"
    description: str = (
        "Answers questions about sexually transmitted infections (STIs/STDs): "
        "HIV, chlamydia, gonorrhea, syphilis, herpes, HPV, hepatitis. "
        "Covers symptoms, transmission, prevention, testing, and treatment."
    )
    system_prompt: str = STI_AGENT_PROMPT
