"""Centralized GovChat operations used across flows.

Eliminates duplicated helper functions by providing validated,
safe wrappers around GovChatClient methods.
"""

import logging

from .client import GovChatClient
from .models import ConversationStatus, Priority

logger = logging.getLogger(__name__)


def _parse_conversation_id(conversation_id: str | None) -> int | None:
    """Convert conversation_id string to int, returning None if invalid."""
    if not conversation_id:
        return None
    try:
        return int(conversation_id)
    except (ValueError, TypeError):
        logger.error(
            f"[GovChat] Invalid conversation_id (not numeric): {conversation_id!r}"
        )
        return None


async def govchat_resolve(
    account_id: str | None,
    conversation_id: str | None,
    status: ConversationStatus = ConversationStatus.RESOLVED,
) -> dict:
    """Resolve (or change status of) a GovChat conversation."""
    conv_id = _parse_conversation_id(conversation_id)
    if not account_id or not conv_id:
        logger.warning("[GovChat] Missing/invalid IDs, skipping resolve")
        return {"success": False, "error": "Missing account_id or conversation_id"}

    async with GovChatClient(account_id=account_id) as client:
        try:
            result = await client.resolve_conversation(
                conversation_id=conv_id, status=status
            )
            logger.info(f"[GovChat] Resolved conversation {conversation_id}")
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"[GovChat] Failed to resolve conversation: {e}")
            return {"success": False, "error": str(e)}


async def govchat_assign_team(
    account_id: str | None,
    conversation_id: str | None,
    team_id: int,
) -> dict:
    """Assign a conversation to a team."""
    conv_id = _parse_conversation_id(conversation_id)
    if not account_id or not conv_id:
        logger.warning(
            f"[GovChat] Missing/invalid IDs, skipping team assignment: team_id={team_id}"
        )
        return {"success": False, "error": "Missing account_id or conversation_id"}

    async with GovChatClient(account_id=account_id) as client:
        try:
            result = await client.assign_team(conversation_id=conv_id, team_id=team_id)
            logger.info(
                f"[GovChat] Assigned conversation {conversation_id} to team {team_id}"
            )
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"[GovChat] Failed to assign team: {e}")
            return {"success": False, "error": str(e)}


async def govchat_set_attribute(
    account_id: str | None,
    conversation_id: str | None,
    attribute_key: str,
    value: str | int | bool,
) -> dict:
    """Set a custom attribute on a conversation."""
    conv_id = _parse_conversation_id(conversation_id)
    if not account_id or not conv_id:
        logger.warning(
            f"[GovChat] Missing/invalid IDs, skipping attribute update: "
            f"{attribute_key}={value}"
        )
        return {"success": False, "error": "Missing account_id or conversation_id"}

    async with GovChatClient(account_id=account_id) as client:
        try:
            result = await client.update_conversation_attribute(
                conversation_id=conv_id, attribute_key=attribute_key, value=value
            )
            logger.info(
                f"[GovChat] Set conversation {conversation_id} attribute: "
                f"{attribute_key}={value}"
            )
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"[GovChat] Failed to set attribute: {e}")
            return {"success": False, "error": str(e)}


async def govchat_set_priority(
    account_id: str | None,
    conversation_id: str | None,
    priority: Priority,
) -> dict:
    """Set conversation priority."""
    conv_id = _parse_conversation_id(conversation_id)
    if not account_id or not conv_id:
        logger.warning(
            f"[GovChat] Missing/invalid IDs, skipping priority update: "
            f"priority={priority}"
        )
        return {"success": False, "error": "Missing account_id or conversation_id"}

    async with GovChatClient(account_id=account_id) as client:
        try:
            result = await client.set_priority(
                conversation_id=conv_id, priority=priority
            )
            logger.info(
                f"[GovChat] Set conversation {conversation_id} priority to {priority}"
            )
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"[GovChat] Failed to set priority: {e}")
            return {"success": False, "error": str(e)}
