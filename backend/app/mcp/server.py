"""
backend/app/mcp/server.py
─────────────────────────
FastMCP Server implementation exposing specialized agents and coordinator as MCP tools.
"""

import logging

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    FastMCP = None

from backend.app.agents.general import GeneralHealthAgent
from backend.app.agents.sti import STIAgent
from backend.app.agents.contraception import ContraceptionAgent
from backend.app.agents.reproductive import ReproductiveHealthAgent
from backend.app.agents.safety import SafetyConsentAgent
from backend.app.agents.coordinator import CoordinatorAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_server")

_general = GeneralHealthAgent()
_sti = STIAgent()
_contraception = ContraceptionAgent()
_reproductive = ReproductiveHealthAgent()
_safety = SafetyConsentAgent()
_coordinator = CoordinatorAgent()

if FastMCP is not None:
    mcp = FastMCP(
        name="SexualHealthAssistant",
        instructions=(
            "A virtual assistant with 5 specialized agents for sexual and reproductive health topics. "
            "Use the coordinator tool to auto-route, or call a specific agent directly."
        ),
    )

    @mcp.tool()
    async def coordinator(question: str) -> str:
        """Auto-routes the question to the most relevant specialized agent."""
        result = await _coordinator.run(question)
        agent_used = result.get("agent_used", "coordinator")
        answer = result.get("answer", "")
        return f"[Handled by: {agent_used}]\n\n{answer}"

    @mcp.tool()
    async def general_health_agent(question: str) -> str:
        """Answers general sexual health questions: hygiene, anatomy, puberty, wellness."""
        return await _general.run(question)

    @mcp.tool()
    async def sti_agent(question: str) -> str:
        """Answers questions about sexually transmitted infections (STIs/STDs)."""
        return await _sti.run(question)

    @mcp.tool()
    async def contraception_agent(question: str) -> str:
        """Answers questions about contraception (birth control) and family planning."""
        return await _contraception.run(question)

    @mcp.tool()
    async def reproductive_health_agent(question: str) -> str:
        """Answers questions about reproductive health: menstruation, pregnancy, PCOS, fertility."""
        return await _reproductive.run(question)

    @mcp.tool()
    async def safety_consent_agent(question: str) -> str:
        """Answers questions about consent, healthy relationships, safety, and emotional support."""
        return await _safety.run(question)

else:
    class DummyMCP:
        def __init__(self):
            self.name = "SexualHealthAssistant (Stub)"

        def run(self):
            raise ImportError(
                "The 'mcp' package is not installed. Please install it using 'pip install mcp' to run the FastMCP server."
            )

    mcp = DummyMCP()

if __name__ == "__main__":
    if FastMCP is not None:
        logger.info("Starting Sexual Health Assistant FastMCP Server...")
        mcp.run()
    else:
        print("LỖI: Chưa cài đặt thư viện 'mcp'. Vui lòng chạy 'pip install mcp' để sử dụng FastMCP Server.")
