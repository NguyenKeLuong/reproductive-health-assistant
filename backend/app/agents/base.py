"""
base.py
───────
Base class for specialized clinical agents communicating with an OpenAI-compatible LLM.
"""

from typing import List, Dict, Optional, AsyncGenerator
from openai import AsyncOpenAI
from backend.app.core.config import API_URL, API_KEY, MODEL_NAME

class BaseAgent:
    """
    Base agent: wraps an OpenAI-compatible chat API call.
    Each subclass defines its own `name`, `description`, and `system_prompt`.
    """

    name: str = "base_agent"
    description: str = "A generic agent."
    system_prompt: str = "You are a helpful assistant."

    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=API_URL,
            api_key=API_KEY if API_KEY else "no-key",
        )
        self.model = MODEL_NAME

    async def run(self, question: str, chat_history: Optional[List[Dict[str, str]]] = None) -> str:
        """Send a question to the LLM and return the complete text answer."""
        messages = [{"role": "system", "content": self.system_prompt}]
        if chat_history:
            messages.extend(chat_history)
        messages.append({"role": "user", "content": question})

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=2048,
        )
        return response.choices[0].message.content.strip()

    async def run_stream(self, question: str, chat_history: Optional[List[Dict[str, str]]] = None) -> AsyncGenerator[str, None]:
        """Send a question to the LLM and yield streaming tokens in real-time."""
        messages = [{"role": "system", "content": self.system_prompt}]
        if chat_history:
            messages.extend(chat_history)
        messages.append({"role": "user", "content": question})

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.7,
            max_tokens=2048,
            stream=True,
        )
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def as_tool_schema(self) -> dict:
        """Return an OpenAI function-calling tool schema for this agent."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The user question to answer.",
                        }
                    },
                    "required": ["question"],
                },
            },
        }

    def __repr__(self):
        return f"<Agent name={self.name!r}>"
