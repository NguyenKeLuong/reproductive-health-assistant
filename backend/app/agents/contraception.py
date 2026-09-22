from backend.app.agents.base import BaseAgent
from backend.app.core.prompts import CONTRACEPTION_AGENT_PROMPT

class ContraceptionAgent(BaseAgent):
    name: str = "contraception_agent"
    description: str = (
        "Answers questions about contraception (birth control) and family planning: "
        "condoms, oral contraceptives, IUDs, implants, emergency contraception, "
        "and fertility awareness methods."
    )
    system_prompt: str = CONTRACEPTION_AGENT_PROMPT
