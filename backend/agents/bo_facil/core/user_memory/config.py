"""
Configuration for user memory persistence.

This module centralizes all field mappings and settings for the new
nested Pydantic state structure.
"""

from dataclasses import dataclass, field


@dataclass
class UserMemoryConfig:
    """
    Configuration for user memory field mappings and limits.

    Maps nested BOState fields to flat UserProfile fields.
    Format: (group, field) -> profile_field
    """

    # Maps (group, field) tuples to UserProfile field names
    profile_field_mapping: dict[tuple[str, str], str] = field(
        default_factory=lambda: {
            # Identity group -> profile
            ("identity", "cpf_input"): "cpf",
            ("identity", "cpf_validated"): "cpf_validated",
            ("identity", "birth_city_provided"): "birth_city",
            ("identity", "biographical_data"): "biographical_data",
            ("identity", "verified"): "identity_verified",
            # Victim group -> profile (for reporter_name which maps to full_name)
            ("victim", "reporter_name"): "full_name",
        }
    )

    # BOState fields used for BO history entries (group, field)
    history_fields: list[tuple[str, str]] = field(
        default_factory=lambda: [
            ("incident", "description"),
            ("incident", "type_names"),
        ]
    )

    # Maximum number of BO entries to keep in history
    max_bo_history: int = 10

    # Store keys for each data type
    store_key_profile: str = "profile"
    store_key_history: str = "bo_history"
    store_key_metadata: str = "metadata"


# Global configuration instance
USER_MEMORY_CONFIG = UserMemoryConfig()
