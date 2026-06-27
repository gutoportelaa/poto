"""
User memory persistence module.

This module provides centralized management of user data that persists
across conversations, including profile information, BO history, and
metadata for versioning.

Usage:
    from agents.bo_facil.core.user_memory import UserMemoryManager

    manager = UserMemoryManager(store, user_id)
    await manager.restore_to_state(state)
    await manager.save_profile_from_state(state)
"""

from .config import USER_MEMORY_CONFIG, UserMemoryConfig
from .manager import UserMemoryManager
from .models import BOHistoryEntry, UserMemoryData, UserMetadata, UserProfile

__all__ = [
    "UserMemoryManager",
    "UserMemoryData",
    "UserProfile",
    "BOHistoryEntry",
    "UserMetadata",
    "USER_MEMORY_CONFIG",
    "UserMemoryConfig",
]
