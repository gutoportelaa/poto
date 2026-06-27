"""Utility functions for building conversation history."""

from langchain_core.messages import AIMessage, HumanMessage

from .message_tags import summarize_bot_message


def _extract_text_from_whatsapp_json(content: str) -> str | None:
    """Extract readable text from WhatsApp JSON message format.

    Handles the WhatsAppResponse structure: {"messages": [{"type": "text", "body": "..."}, ...]}
    """
    try:
        import json

        data = json.loads(content)

        # Handle WhatsAppResponse format: {"messages": [...]}
        if "messages" in data:
            text_parts = []
            for msg in data["messages"]:
                body = msg.get("body")
                if body:
                    text_parts.append(body)
            return " | ".join(text_parts) if text_parts else None

        # Fallback: try legacy format {"text": {"body": "..."}}
        text = data.get("text", {}).get("body", "")
        if text:
            return text

        return None
    except Exception:
        return None


def build_conversation_history(
    state: dict,
    max_messages: int = 30,
    compress_bot_messages: bool = True,
) -> str:
    """
    Build conversation history from both AI and user messages for context in analysis prompts.

    This enables "carrying context" - allowing collectors to access information
    from earlier messages (e.g., first message and menu responses) that would
    otherwise be lost when analyzing only the current user response.

    Args:
        state: Current state containing messages list
        max_messages: Maximum number of recent messages to include (default: 30, ~15 exchanges)
        compress_bot_messages: If True, replaces bot messages with semantic tags to save tokens.
            User messages are always kept in full. (default: True)

    Returns:
        String with formatted conversation history (Bot: ... \n Usuário: ...), or "Nenhuma mensagem anterior"
    """
    messages = state.get("messages", [])
    if not messages:
        return "Nenhuma mensagem anterior"

    history_parts = []
    for msg in messages[-max_messages:]:
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if content.strip():
                history_parts.append(f"Usuário: {content.strip()}")
        elif isinstance(msg, AIMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if not content.strip():
                continue

            # Plain text message (not JSON)
            if not content.startswith("{"):
                bot_text = content.strip()
            else:
                # Parse WhatsApp JSON to extract bot message text
                extracted = _extract_text_from_whatsapp_json(content)
                if not extracted:
                    continue
                bot_text = extracted

            # Compress bot message if enabled
            if compress_bot_messages:
                # Try to get node name from message metadata for better fallback
                node_name = msg.additional_kwargs.get("node_name")
                bot_text = summarize_bot_message(bot_text, node_name=node_name)

            history_parts.append(f"Bot: {bot_text}")

    return "\n".join(history_parts) if history_parts else "Nenhuma mensagem anterior"
