from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from takehome.db.models import Message
from takehome.db.session import get_session
from takehome.services.conversation import get_conversation, update_conversation
from takehome.services.document import get_documents_for_conversation
from takehome.services.grounding import (
    build_sources_block,
    compute_confidence,
    resolve_citations,
    strip_fabricated_markers,
)
from takehome.services.llm import chat_with_documents, generate_title
from takehome.services.retrieval import retrieve

logger = structlog.get_logger()

router = APIRouter(tags=["messages"])

# How many passages to retrieve across all of a conversation's documents.
RETRIEVAL_K = 6


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    sources_cited: int
    confidence: str | None = None
    citations: list[dict[str, Any]] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageCreate(BaseModel):
    content: str


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@router.get(
    "/api/conversations/{conversation_id}/messages",
    response_model=list[MessageOut],
)
async def list_messages(
    conversation_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[MessageOut]:
    """List all messages in a conversation, ordered by creation time."""
    # Verify the conversation exists
    conversation = await get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    result = await session.execute(stmt)
    messages = list(result.scalars().all())

    return [
        MessageOut(
            id=m.id,
            conversation_id=m.conversation_id,
            role=m.role,
            content=m.content,
            sources_cited=m.sources_cited,
            confidence=m.confidence,
            citations=m.citations,
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post("/api/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: MessageCreate,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Send a user message and stream back a grounded AI response via SSE."""
    # Verify the conversation exists
    conversation = await get_conversation(session, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Save the user message
    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=body.content,
    )
    session.add(user_message)
    await session.commit()
    await session.refresh(user_message)

    logger.info("User message saved", conversation_id=conversation_id, message_id=user_message.id)

    # Load every document in the conversation so a single question can be
    # answered across all of them.
    documents = await get_documents_for_conversation(session, conversation_id)
    doc_inputs = [(d.id, d.filename, d.extracted_text) for d in documents]
    has_documents = len(documents) > 0

    # Load conversation history (exclude the message we just saved).
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .where(Message.id != user_message.id)
        .order_by(Message.created_at.asc())
    )
    result = await session.execute(stmt)
    history_messages = list(result.scalars().all())

    conversation_history: list[dict[str, str]] = [
        {"role": m.role, "content": m.content} for m in history_messages
    ]

    # Retrieve the most relevant passages across all documents, then render them
    # as the numbered SOURCES block the model must cite from.
    scored = retrieve(doc_inputs, body.content, k=RETRIEVAL_K)
    sources_block, source_map = build_sources_block(scored)

    # Determine if this is the first user message (for title generation)
    user_msg_count = sum(1 for m in history_messages if m.role == "user")
    is_first_message = user_msg_count == 0

    async def event_stream() -> AsyncIterator[str]:
        """Generate SSE events with the streamed, grounded LLM response."""
        full_response = ""

        try:
            async for chunk in chat_with_documents(
                user_message=body.content,
                sources_block=sources_block,
                conversation_history=conversation_history,
            ):
                full_response += chunk
                event_data = json.dumps({"type": "content", "content": chunk})
                yield f"data: {event_data}\n\n"

        except Exception:
            logger.exception(
                "Error during LLM streaming",
                conversation_id=conversation_id,
            )
            error_msg = "I'm sorry, an error occurred while generating a response. Please try again."
            full_response = error_msg
            event_data = json.dumps({"type": "content", "content": error_msg})
            yield f"data: {event_data}\n\n"

        # Verify the citations the model emitted against the sources we provided:
        # keep the ones that resolve to a real passage, drop the fabricated ones,
        # and derive a confidence level from what survived.
        valid, fabricated = resolve_citations(full_response, source_map)
        clean_response = strip_fabricated_markers(full_response, fabricated)
        confidence = compute_confidence(valid, fabricated, scored, has_documents)
        citations_payload: list[dict[str, Any]] = [
            {
                "marker": c.marker,
                "document_id": c.document_id,
                "filename": c.filename,
                "page": c.page,
                "heading": c.heading,
                "snippet": c.snippet,
            }
            for c in valid
        ]

        if fabricated:
            logger.warning(
                "Dropped fabricated citation markers",
                conversation_id=conversation_id,
                markers=fabricated,
            )

        # Save the assistant message to the database.
        # We need a fresh session since the outer one may have been closed.
        from takehome.db.session import async_session as session_factory

        async with session_factory() as save_session:
            assistant_message = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=clean_response,
                sources_cited=len(valid),
                confidence=confidence,
                citations=citations_payload or None,
            )
            save_session.add(assistant_message)
            await save_session.commit()
            await save_session.refresh(assistant_message)

            # Auto-generate title from first user message
            if is_first_message:
                try:
                    title = await generate_title(body.content)
                    await update_conversation(save_session, conversation_id, title)
                    logger.info(
                        "Auto-generated conversation title",
                        conversation_id=conversation_id,
                        title=title,
                    )
                except Exception:
                    logger.exception(
                        "Failed to generate title",
                        conversation_id=conversation_id,
                    )

            # Send the final message event with the complete assistant message,
            # including trust signals (confidence + resolved citations).
            message_data = json.dumps(
                {
                    "type": "message",
                    "message": {
                        "id": assistant_message.id,
                        "conversation_id": assistant_message.conversation_id,
                        "role": assistant_message.role,
                        "content": assistant_message.content,
                        "sources_cited": assistant_message.sources_cited,
                        "confidence": assistant_message.confidence,
                        "citations": assistant_message.citations,
                        "created_at": assistant_message.created_at.isoformat(),
                    },
                }
            )
            yield f"data: {message_data}\n\n"

            # Send the done signal
            done_data = json.dumps(
                {
                    "type": "done",
                    "sources_cited": len(valid),
                    "confidence": confidence,
                    "message_id": assistant_message.id,
                }
            )
            yield f"data: {done_data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
