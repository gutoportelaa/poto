"""
Centralized user memory management.

This module provides the UserMemoryManager class which handles all
user data persistence operations, including loading, saving, restoring,
and deleting user data from the store.

Updated to work with nested Pydantic state structure.
"""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from langgraph.store.base import BaseStore

from ..states import get_nested_value, set_nested_value
from .config import USER_MEMORY_CONFIG as config
from .models import (
    CURRENT_VERSION,
    BOHistoryEntry,
    UserMemoryData,
    UserMetadata,
    UserProfile,
)

logger = logging.getLogger(__name__)


class UserMemoryManager:
    """
    Centralized manager for user memory persistence.

    Provides a clean interface for loading, saving, restoring, and
    deleting user data from the LangGraph store. Handles all the
    complexity of namespace management and data serialization.

    Works with nested Pydantic state structure.

    Usage:
        manager = UserMemoryManager(store, user_id)
        await manager.restore_to_state(state)  # Load saved data into state
        await manager.save_profile_from_state(state)  # Persist state data
    """

    def __init__(self, store: BaseStore, user_id: str):
        """
        Initialize the manager with a store and user ID.

        Args:
            store: LangGraph BaseStore instance (PostgresStore, InMemoryStore, etc.)
            user_id: Unique identifier for the user
        """
        self.store = store
        self.user_id = user_id
        self.namespace = (user_id,)
        self._cache: UserMemoryData | None = None

    # ==================== LOAD ====================

    async def _safe_aget(self, key: str) -> Any | None:
        """Safely get an item from the store, returning None on deserialization errors.

        On failure, delete the corrupt key so the next write starts clean — this
        prevents the same warning from recurring every load for users whose store
        entries were written in an incompatible format by a prior schema.
        """
        try:
            item = await self.store.aget(self.namespace, key)
            if item is None:
                return None
            return item.value
        except Exception as e:
            logger.warning(
                "[UserMemoryManager] Failed to read key '%s' for user %s: %s — "
                "deleting corrupt entry",
                key,
                self.user_id,
                e,
            )
            try:
                await self.store.adelete(self.namespace, key)
            except Exception as delete_error:
                logger.warning(
                    "[UserMemoryManager] Failed to delete corrupt key '%s' for user %s: %s",
                    key,
                    self.user_id,
                    delete_error,
                )
            return None

    async def load(self) -> UserMemoryData:
        """
        Load all user data from the store.

        Returns cached data if available, otherwise fetches from store.
        Handles version migration if stored data uses an older schema.
        Each key is loaded independently — one failure doesn't break the others.

        Returns:
            UserMemoryData containing profile, history, and metadata
        """
        if self._cache:
            return self._cache

        # Load each key independently
        profile_value = await self._safe_aget(config.store_key_profile)
        try:
            profile = UserProfile(**profile_value) if profile_value else UserProfile()
        except Exception as e:
            logger.warning("[UserMemoryManager] Corrupt profile for user %s: %s", self.user_id, e)
            profile = UserProfile()

        history_value = await self._safe_aget(config.store_key_history)
        history: list[BOHistoryEntry] = []
        if history_value:
            try:
                # Guard: store backend may return JSON string instead of parsed list
                if isinstance(history_value, (str, bytes)):
                    import json

                    history_value = json.loads(history_value)
                if isinstance(history_value, list):
                    history = [BOHistoryEntry(**entry) for entry in history_value]
                else:
                    logger.warning(
                        "[UserMemoryManager] Unexpected history type for user %s: %s",
                        self.user_id,
                        type(history_value).__name__,
                    )
            except Exception as e:
                logger.warning(
                    "[UserMemoryManager] Corrupt history for user %s: %s", self.user_id, e
                )

        meta_value = await self._safe_aget(config.store_key_metadata)
        try:
            metadata = UserMetadata(**meta_value) if meta_value else UserMetadata()
        except Exception as e:
            logger.warning("[UserMemoryManager] Corrupt metadata for user %s: %s", self.user_id, e)
            metadata = UserMetadata()

        # Check version and migrate if necessary
        if metadata.version != CURRENT_VERSION:
            await self._migrate(metadata.version)

        self._cache = UserMemoryData(profile=profile, bo_history=history, metadata=metadata)
        logger.info("[UserMemoryManager] Loaded data for user %s", self.user_id)
        return self._cache

    # ==================== SAVE ====================

    async def save_profile(self, profile: UserProfile) -> None:
        """
        Save the user profile to the store.

        Args:
            profile: UserProfile instance to persist
        """
        await self.store.aput(
            self.namespace, config.store_key_profile, profile.model_dump(mode="json")
        )
        await self._update_metadata()
        if self._cache:
            self._cache.profile = profile
        logger.info(f"[UserMemoryManager] Saved profile for user {self.user_id}")

    async def save_profile_from_state(self, state: dict[str, Any]) -> None:
        """
        Extract fields from nested BOState and save to profile.

        Uses the field mapping from config to determine which state
        fields should be persisted to the user profile.

        Args:
            state: BOState dictionary with nested Pydantic models
        """
        data = await self.load()
        profile_dict = data.profile.model_dump()

        # Map nested state fields to profile fields using config
        for (group, field), profile_field in config.profile_field_mapping.items():
            value = get_nested_value(state, group, field)
            if value is not None:
                profile_dict[profile_field] = value

        await self.save_profile(UserProfile(**profile_dict))

    async def add_bo_to_history(
        self, bo_description: str, incident_type: str | None = None
    ) -> None:
        """
        Add a completed BO to the user's history.

        Maintains a maximum number of entries as defined in config,
        removing oldest entries when the limit is exceeded.

        Args:
            bo_description: Description of the BO incident
            incident_type: Optional type classification of the incident
        """
        data = await self.load()

        entry = BOHistoryEntry(
            bo_id=str(uuid4()),
            created_at=datetime.now(UTC),
            incident_type=incident_type,
            bo_description=bo_description,
        )

        # Add at the beginning and limit size
        data.bo_history.insert(0, entry)
        data.bo_history = data.bo_history[: config.max_bo_history]

        await self.store.aput(
            self.namespace,
            config.store_key_history,
            [e.model_dump(mode="json") for e in data.bo_history],
        )

        # Update metadata with BO statistics
        data.metadata.last_bo_at = datetime.now(UTC)
        data.metadata.total_bos += 1
        await self._update_metadata(data.metadata)

        logger.info(f"[UserMemoryManager] Added BO to history for user {self.user_id}")

    # ==================== RESTORE ====================

    async def restore_to_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Restore saved profile data to nested BOState.

        Loads persisted user data and populates the corresponding
        fields in the nested state structure.

        Args:
            state: BOState dictionary to populate with saved data

        Returns:
            Dictionary of fields that were restored (for logging/debugging)
        """
        data = await self.load()
        restored = {}

        # Group updates by state group for efficiency
        for (group, field), profile_field in config.profile_field_mapping.items():
            value = getattr(data.profile, profile_field, None)
            if value is not None:
                set_nested_value(state, group, field, value)
                restored[f"{group}.{field}"] = value

        logger.info(f"[UserMemoryManager] Restored {len(restored)} fields to state")
        return restored

    # ==================== DELETE ====================

    async def delete_all(self) -> None:
        """
        Delete all user data from the store.

        Removes profile, BO history, and metadata completely.
        Use with caution - this action cannot be undone.
        """
        for key in [
            config.store_key_profile,
            config.store_key_history,
            config.store_key_metadata,
        ]:
            try:
                await self.store.adelete(self.namespace, key)
            except Exception:
                pass  # Ignore if key doesn't exist

        self._cache = None
        logger.info(f"[UserMemoryManager] Deleted all data for user {self.user_id}")

    async def delete_profile(self) -> None:
        """
        Delete only the user profile, keeping history intact.

        Useful for LGPD compliance when user requests data deletion
        but historical records need to be maintained.
        """
        await self.store.adelete(self.namespace, config.store_key_profile)
        if self._cache:
            self._cache.profile = UserProfile()
        logger.info(f"[UserMemoryManager] Deleted profile for user {self.user_id}")

    async def clear_bo_history(self) -> None:
        """
        Clear the BO history while keeping profile data.

        Useful for users who want to start fresh without
        losing their verified identity information.
        """
        await self.store.adelete(self.namespace, config.store_key_history)
        if self._cache:
            self._cache.bo_history = []
        logger.info(f"[UserMemoryManager] Cleared BO history for user {self.user_id}")

    # ==================== HELPERS ====================

    async def _update_metadata(self, metadata: UserMetadata | None = None) -> None:
        """
        Update metadata with current timestamp.

        Args:
            metadata: Optional metadata to save, loads from cache if not provided
        """
        if metadata is None:
            data = await self.load()
            metadata = data.metadata

        metadata.updated_at = datetime.now(UTC)
        await self.store.aput(
            self.namespace, config.store_key_metadata, metadata.model_dump(mode="json")
        )

    async def _migrate(self, from_version: str) -> None:
        """
        Migrate data from an older schema version.

        Override this method to add migration logic when the schema
        changes. Each migration should handle converting from one
        version to the next.

        Args:
            from_version: The version string of the stored data
        """
        logger.info(f"[UserMemoryManager] Migrating from {from_version} to {CURRENT_VERSION}")
        # Add migration logic here as needed
        pass

    # ==================== GETTERS ====================

    async def get_profile(self) -> UserProfile:
        """Get the user's profile data."""
        data = await self.load()
        return data.profile

    async def get_bo_history(self) -> list[BOHistoryEntry]:
        """Get the user's BO history."""
        data = await self.load()
        return data.bo_history

    async def has_verified_identity(self) -> bool:
        """Check if the user has previously verified their identity."""
        data = await self.load()
        return data.profile.identity_verified
