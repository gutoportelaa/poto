"""
Pydantic models for user memory persistence.

This module defines the data structures used to persist user data
across conversations, including profile information, BO history,
and metadata for versioning.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(UTC)


# Current schema version - increment when making breaking changes
CURRENT_VERSION = "1.0.0"


class UserProfile(BaseModel):
    """
    Personal data persisted across conversations.

    These fields are collected during identity verification and
    can be restored in subsequent conversations to avoid asking
    the user for the same information repeatedly.
    """

    cpf: str | None = None
    cpf_validated: bool = False
    full_name: str | None = None
    birth_city: str | None = None
    biographical_data: dict | None = None
    identity_verified: bool = False


class BOHistoryEntry(BaseModel):
    """
    Single entry in the user's BO history.

    Only stores essential information (bo_description) to keep
    storage requirements minimal while maintaining useful context.
    """

    bo_id: str
    created_at: datetime
    incident_type: str | None = None
    bo_description: str  # Only the description, not the full BO


class UserMetadata(BaseModel):
    """
    Metadata for tracking user data versioning and statistics.

    Used for schema migrations and analytics about user activity.
    """

    version: str = CURRENT_VERSION
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    last_bo_at: datetime | None = None
    total_bos: int = 0


class UserMemoryData(BaseModel):
    """
    Main container for all user data.

    Aggregates profile, BO history, and metadata into a single
    object for convenient loading and manipulation.
    """

    profile: UserProfile = Field(default_factory=UserProfile)
    bo_history: list[BOHistoryEntry] = Field(default_factory=list)
    metadata: UserMetadata = Field(default_factory=UserMetadata)
