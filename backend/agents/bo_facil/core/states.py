"""BOState definition with Pydantic sub-models for organized state management.

This module defines the state structure for the BO Fácil agent using
Pydantic models for validation, defaults, and clear organization.
"""

from typing import Annotated, Literal, TypeVar

from langgraph.graph import MessagesState
from pydantic import BaseModel, Field

from agents.bo_facil.flows.bo_treatment.location_extractor.models import (
    StructuredLocation,
)

T = TypeVar("T", bound=BaseModel)


def scratchpad_reducer(existing: str, new: str | None) -> str:
    """Reducer for scratchpad - overwrites at strategic flow points."""
    if new is None:
        return existing or ""
    return new


# =============================================================================
# Sub-Models
# =============================================================================


class UserInfo(BaseModel):
    """User identification from GovChat bridge."""

    inbox_id: str | None = None
    account_id: str | None = None
    conversation_id: str | None = None
    phone: str | None = None
    sender_id: str | None = None


class ClassificationInfo(BaseModel):
    """Service classification and urgency analysis."""

    type: (
        Literal["bo_facil", "atendimento_190", "denuncia_anonima", "atendimento_humano", "ambigua"]
        | None
    ) = None
    attempts: int = 0
    requires_fallback: bool = False
    is_urgent: bool = False
    urgency_level: Literal["critica", "alta", "media", "baixa"] | None = None
    urgency_reasoning: str | None = None
    emergency_detected: bool = False
    emergency_confidence: float | None = None


class RedirectInfo(BaseModel):
    """Redirect control for emergency/human handoff or flow restart."""

    to: Literal["emergency", "human", "initial", "closed", "cancel"] | None = None
    reason: str | None = None
    custom_message: str | list[str] | None = None


class IncidentInfo(BaseModel):
    """Core incident data."""

    fact: str | None = None
    datetime: str | None = None
    location: str | None = None
    reference_point: str | None = None
    description: str | None = None
    type_codes: list[str] = Field(default_factory=list)
    type_names: list[str] = Field(default_factory=list)
    # Legacy geocoded data (DEPRECATED, remove in Phase 3)
    # Kept for backward compatibility with checkpoints in-flight during deploy.
    latitude: float | None = None
    longitude: float | None = None
    geocoded_data: dict | None = None
    # New structured location + coordinates from the 3-layer extractor (Phase 2+)
    structured: "StructuredLocation | None" = None
    coordinates: list[float] | None = Field(
        default=None,
        description="[lat, long] — list form for JSON round-trip safety",
    )
    non_pi_state_detected: bool = False
    detected_state: str | None = None
    non_pi_state_acknowledged: bool = False


class CollectionStatus(BaseModel):
    """Incident data collection tracking."""

    # Collection flags
    has_fact: bool = False
    has_datetime: bool = False
    has_date: bool = False
    has_time: bool = False
    has_location: bool = False
    has_objects: bool = False
    has_persons: bool = False

    # Attempt counters
    fact_attempts: int = 0
    datetime_attempts: int = 0
    location_attempts: int = 0

    # UI state
    last_failed_input: str | None = None
    retry_prefix_shown: bool = False
    audio_hint_shown: bool = False
    user_at_site: bool | None = None
    location_geocoded: bool = False  # True when geocoding returned useful data

    # LLM-generated followup questions
    fact_followup_question: str | None = None

    # Non-BO intent / non-criminal detection
    non_bo_intent_detected: bool = False
    non_bo_intent_type: str | None = None  # "acompanhamento" | "duvida" | "outro"
    non_registrable_detected: bool = False

    # Flag: datetime was rejected because it was in the future
    datetime_future_rejected: bool = False

    # Flag: user already used "continue" at max attempts (prevent infinite loop)
    continue_used: bool = False

    # Flag: collection was just restarted (show transition message on next question)
    collection_restarted: bool = False


class IdentityInfo(BaseModel):
    """CPF verification and identity data."""

    cpf_input: str | None = None
    cpf_validated: bool = False
    cpf_attempts: int = 0
    biographical_data: dict | None = None
    birth_year_selected: int | None = None
    birth_city_provided: str | None = None
    verified: bool = False
    proceed_without_cpf: bool = False
    data_confirmed: bool = False


class VictimInfo(BaseModel):
    """Victim data for third-party reporters."""

    is_third_party: bool = False
    analyzed: bool = False
    cpf: str | None = None
    cpf_unknown: bool = False
    name: str | None = None
    name_unknown: bool = False
    collected: bool = False
    reporter_name: str | None = None


class ObjectsInfo(BaseModel):
    """Object/item collection data."""

    items: list[dict] = Field(default_factory=list)
    weapons: list[dict] = Field(default_factory=list)
    has_objects: bool | None = None
    collected: bool = False
    current_idx: int | None = None
    current_type: str | None = None
    all_details_collected: bool = False
    details_collected: bool = False
    needs_followup: bool = False
    followup_question: str | None = None


class PersonsInfo(BaseModel):
    """Person collection data."""

    items: list[dict] = Field(default_factory=list)
    has_persons: bool | None = None
    collected: bool = False


class DamageInfo(BaseModel):
    """Financial damage/loss data."""

    detected: bool = False
    detected_value: float | None = None
    detected_payment: str | None = None
    has_damage: bool | None = None
    confirmed: bool = False
    value: float | None = None
    value_attempts: int = 0
    # True once the value step is settled (provided, declined, or max attempts),
    # so the router can leave collect_value instead of re-asking forever.
    value_resolved: bool = False
    payment_method: str | None = None
    # True once the payment-method step is settled (informed or declined), so the
    # router can leave collect_payment instead of re-asking forever.
    payment_resolved: bool = False
    wants_receipt: bool = False
    receipt_url: str | None = None
    collected: bool = False


class CybercrimeInfo(BaseModel):
    """Cybercrime-specific data."""

    should_collect: bool = False
    collected: bool = False
    estelionato: dict | None = None
    has_estelionato: bool = False
    estelionato_attempts: int = 0
    virtual_channel: dict | None = None
    has_virtual_channel: bool = False


class CompletionInfo(BaseModel):
    """BO completion and summary state."""

    completed: bool = False
    pdf_generated: bool = False
    protocol_number: str | None = None
    pdf_url: str | None = None
    wants_edit: bool = False
    edit_request: str | None = None  # User's change description (when typed inline at confirmation)
    awaiting_response: bool = False
    retry_count: int = 0


class HandoffInfo(BaseModel):
    """Human handoff flow data."""

    name: str | None = None
    description: str | None = None
    completed: bool = False
    is_related: bool = False
    team_id: int | None = None


class AnonymousInfo(BaseModel):
    """Anonymous report flow data."""

    completed: bool = False


# =============================================================================
# Main State
# =============================================================================


class BOState(MessagesState, total=False):
    """Main state for BO Fácil agent.

    Groups:
        user: User identification (GovChat)
        classification: Service classification and urgency
        redirect: Emergency/human redirect control
        incident: Core BO data (fact, datetime, location)
        collection: Data collection tracking
        identity: CPF verification
        victim: Third-party reporter victim data
        objects: Object/item collection
        persons: Person collection
        damage: Financial damage collection
        cybercrime: Cybercrime-specific data
        completion: BO completion status
        handoff: Human handoff flow
        anonymous: Anonymous report flow

    Usage:
        # Read
        fact = state["incident"].fact
        is_verified = state["identity"].verified

        # Update (in node return)
        incident = state.get("incident", IncidentInfo())
        return {"incident": incident.model_copy(update={"fact": "Roubaram meu celular"})}
    """

    user: UserInfo
    classification: ClassificationInfo
    redirect: RedirectInfo
    incident: IncidentInfo
    collection: CollectionStatus
    identity: IdentityInfo
    victim: VictimInfo
    objects: ObjectsInfo
    persons: PersonsInfo
    damage: DamageInfo
    cybercrime: CybercrimeInfo
    completion: CompletionInfo
    handoff: HandoffInfo
    anonymous: AnonymousInfo

    last_extraction_index: int | None

    scratchpad: Annotated[str, scratchpad_reducer] = Field(
        default="",
        description="Context extracted at strategic flow points",
    )


# =============================================================================
# Helper Functions
# =============================================================================


def get_state_field(state: "BOState", field: str, model_class: type[T]) -> T:
    """Get a field from state, handling both dict and Pydantic model instances.

    Args:
        state: Current BOState
        field: Field name to retrieve (e.g., "identity", "user", "incident")
        model_class: Pydantic model class for the field

    Returns:
        Instance of model_class, either from state or newly created with defaults

    Examples:
        >>> identity = get_state_field(state, "identity", IdentityInfo)
        >>> user = get_state_field(state, "user", UserInfo)
        >>> incident = get_state_field(state, "incident", IncidentInfo)
    """
    value = state.get(field, model_class())
    if isinstance(value, dict):
        return model_class(**value)
    return value


def get_nested_value(state: dict, group: str, field: str):
    """Get a value from nested state structure.

    Args:
        state: BOState dict
        group: Group name (e.g., 'identity', 'incident')
        field: Field name within the group

    Returns:
        The field value or None

    Examples:
        >>> cpf = get_nested_value(state, "identity", "cpf_input")
        >>> fact = get_nested_value(state, "incident", "fact")
    """
    group_data = state.get(group)
    if group_data is None:
        return None

    # Handle both Pydantic model and dict
    if isinstance(group_data, BaseModel):
        return getattr(group_data, field, None)
    elif isinstance(group_data, dict):
        return group_data.get(field)

    return None


def set_nested_value(state: dict, group: str, field: str, value) -> None:
    """Set a value in nested state structure.

    Args:
        state: BOState dict to modify
        group: Group name (e.g., 'identity', 'incident')
        field: Field name within the group
        value: Value to set

    Examples:
        >>> set_nested_value(state, "identity", "cpf_input", "12345678901")
        >>> set_nested_value(state, "incident", "fact", "Furto de celular")
    """
    if group not in state:
        state[group] = {}

    group_data = state[group]

    if isinstance(group_data, BaseModel):
        # For Pydantic models, update via dict then reconstruct
        model_dict = group_data.model_dump()
        model_dict[field] = value
        state[group] = type(group_data)(**model_dict)
    elif isinstance(group_data, dict):
        group_data[field] = value
