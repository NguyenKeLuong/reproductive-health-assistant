"""
coordinator.py
──────────────
Coordinator Agent orchestrates routing sexual health queries to 5 specialized agents.
"""

import json
import logging
from typing import Optional, List, Dict
from openai import AsyncOpenAI

from backend.app.core.config import API_URL, API_KEY, MODEL_NAME
from backend.app.agents.general import GeneralHealthAgent
from backend.app.agents.sti import STIAgent
from backend.app.agents.contraception import ContraceptionAgent
from backend.app.agents.reproductive import ReproductiveHealthAgent
from backend.app.agents.safety import SafetyConsentAgent

logger = logging.getLogger("coordinator_agent")

AGENT_REGISTRY: Dict[str, object] = {
    "general_health_agent": GeneralHealthAgent(),
    "sti_agent": STIAgent(),
    "contraception_agent": ContraceptionAgent(),
    "reproductive_health_agent": ReproductiveHealthAgent(),
    "safety_consent_agent": SafetyConsentAgent(),
}

class CoordinatorAgent:
    """
    Orchestrator that:
      • Holds references to all specialized agents in AGENT_REGISTRY.
      • Uses LLM tool calling to decide which agent best handles a user question.
      • Runs the chosen agent or streams tokens via WebSocket.
    """

    SYSTEM_PROMPT = """You are the coordinator of a sexual health virtual assistant.
You manage a team of 5 specialized agents. When the user asks a question,
you must call exactly ONE of the available tools that best matches the topic.

Agent overview:
- general_health_agent      → broad sexual health, hygiene, anatomy, wellness
- sti_agent                 → STIs/STDs (HIV, chlamydia, gonorrhea, herpes, HPV …)
- contraception_agent       → birth control, emergency contraception, family planning
- reproductive_health_agent → pregnancy, fertility, menstruation, PCOS, menopause …
- safety_consent_agent      → consent, healthy relationships, sexual violence, mental health

Rules:
1. Always call a tool – never answer directly without routing.
2. Pass the user's original question verbatim to the tool's `question` argument.
3. Choose the single most relevant agent.
4. If the question spans multiple topics, pick the PRIMARY topic.
"""

    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=API_URL,
            api_key=API_KEY if API_KEY else "no-key",
        )
        self.model = MODEL_NAME
        self.agents = AGENT_REGISTRY
        self.tools = [agent.as_tool_schema() for agent in self.agents.values()]

    async def run(self, question: str, chat_history: Optional[List[Dict[str, str]]] = None) -> dict:
        """Route the user question to the best agent and return answer."""
        messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        if chat_history:
            messages.extend(chat_history)
        messages.append({"role": "user", "content": question})

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=256,
            )
        except Exception as exc:
            logger.error(f"Coordinator LLM call failed: {exc}")
            return await self._fallback(question)

        choice = response.choices[0]
        if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
            logger.warning("LLM did not call a tool; using fallback agent.")
            return await self._fallback(question)

        tool_call = choice.message.tool_calls[0]
        agent_name = tool_call.function.name

        try:
            args = json.loads(tool_call.function.arguments)
            routed_question = args.get("question", question)
        except (json.JSONDecodeError, AttributeError):
            routed_question = question

        agent = self.agents.get(agent_name)
        if agent is None:
            logger.warning(f"Unknown agent '{agent_name}'; using fallback.")
            return await self._fallback(question)

        logger.info(f"Coordinator routing to: {agent_name}")
        answer = await agent.run(routed_question)

        return {
            "agent_used": agent_name,
            "question": question,
            "answer": answer,
        }

    async def get_route(self, question: str, chat_history: Optional[List[Dict[str, str]]] = None) -> str:
        """Decide which agent should handle the question for streaming."""
        messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        if chat_history:
            messages.extend(chat_history)
        messages.append({"role": "user", "content": question})

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.tools,
                tool_choice="auto",
                temperature=0.2,
                max_tokens=256,
            )
            choice = response.choices[0]
            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                return choice.message.tool_calls[0].function.name
            return "general_health_agent"
        except Exception as e:
            logger.error(f"Routing error: {e}")
            return "general_health_agent"

    async def _fallback(self, question: str) -> dict:
        fallback_agent = self.agents["general_health_agent"]
        answer = await fallback_agent.run(question)
        return {
            "agent_used": "general_health_agent (fallback)",
            "question": question,
            "answer": answer,
        }

    def list_agents(self) -> List[dict]:
        return [
            {"name": name, "description": agent.description}
            for name, agent in self.agents.items()
        ]
