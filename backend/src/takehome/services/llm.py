from __future__ import annotations

from collections.abc import AsyncIterator

from pydantic_ai import Agent

from takehome.config import settings  # noqa: F401 — triggers ANTHROPIC_API_KEY export
from takehome.services.grounding import GROUNDED_SYSTEM_PROMPT, build_grounded_prompt

# A lightweight agent used only for the utility task of naming conversations.
title_agent = Agent("anthropic:claude-haiku-4-5-20251001")

# The main Q&A agent. Its system prompt encodes the grounding contract: answer
# only from provided sources, cite everything, and admit when the documents
# don't cover the question.
grounded_agent = Agent(
    "anthropic:claude-haiku-4-5-20251001",
    system_prompt=GROUNDED_SYSTEM_PROMPT,
)


async def generate_title(user_message: str) -> str:
    """Generate a 3-5 word conversation title from the first user message."""
    result = await title_agent.run(
        f"Generate a concise 3-5 word title for a conversation that starts with: '{user_message}'. "
        "Return only the title, nothing else."
    )
    title = str(result.output).strip().strip('"').strip("'")
    if len(title) > 100:
        title = title[:97] + "..."
    return title


async def chat_with_documents(
    user_message: str,
    sources_block: str,
    conversation_history: list[dict[str, str]],
) -> AsyncIterator[str]:
    """Stream a grounded answer, yielding text chunks.

    `sources_block` is the pre-rendered, numbered SOURCES block produced from the
    passages retrieved across all of the conversation's documents. The model is
    constrained to answer from those sources and to cite them inline with
    `[Sn]` markers.
    """
    prompt = build_grounded_prompt(user_message, sources_block, conversation_history)
    async with grounded_agent.run_stream(prompt) as result:
        async for text in result.stream_text(delta=True):
            yield text
