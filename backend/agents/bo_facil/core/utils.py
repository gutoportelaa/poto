import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

from langchain_core.language_models.base import LanguageModelInput
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.runnables import Runnable, RunnableConfig, RunnableLambda, RunnableSerializable

from core import settings

from .llm_fallback import RunnableWithFallback
from .states import BOState, RedirectInfo

logger = logging.getLogger(__name__)

_BRT = ZoneInfo("America/Sao_Paulo")

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

    from .user_memory import UserMemoryManager


def now_brazil() -> datetime:
    """Return current datetime in Brazil/São Paulo timezone (naive).

    Returns a naive datetime (no tzinfo) in BRT, suitable for string
    formatting and comparison with other naive datetimes in the codebase.
    """
    return datetime.now(_BRT).replace(tzinfo=None)


def get_config_info(config: RunnableConfig) -> tuple[str | None, tuple | None, str]:
    """Extract configuration information from RunnableConfig.

    Returns:
        tuple: (user_id, namespace, model_name)
            - user_id: User identifier from config
            - namespace: Tuple namespace for store operations, or None
            - model_name: Model name from config or default
    """
    configurable = config.get("configurable", {})
    user_id = configurable.get("user_id")
    namespace = (user_id,) if user_id else None
    model_name = configurable.get("model", settings.DEFAULT_MODEL)
    return user_id, namespace, model_name


def get_user_memory_manager(
    config: RunnableConfig, store: "BaseStore | None"
) -> "UserMemoryManager | None":
    """
    Create a UserMemoryManager instance if user_id is available.

    Factory function that creates a UserMemoryManager for the current user,
    handling the case where user_id or store might not be available.

    Args:
        config: RunnableConfig containing user_id in configurable
        store: LangGraph BaseStore instance (may be None)

    Returns:
        UserMemoryManager instance or None if user_id/store unavailable
    """
    user_id, _, _ = get_config_info(config)
    if not user_id or not store:
        return None

    # Import here to avoid circular dependency
    from .user_memory import UserMemoryManager

    return UserMemoryManager(store, user_id)


def _prepare_messages(
    state: BOState,
    system_prompt: BaseMessage,  # noqa: ARG001
) -> list[BaseMessage]:
    """Prepare messages for the model.

    Returns [SystemMessage, HumanMessage(fixed)] to satisfy vLLM/GLM json_schema
    requirement of having at least one HumanMessage.

    This agent is NOT a traditional chatbot — LLM calls are for extraction,
    classification, and decision-making. All context is embedded in the system
    prompt via explicit variables (conversation_history, scratchpad, current_message,
    user_input, etc.). The state messages are a WhatsApp conversation log, not LLM
    context, so injecting the last user message would leak unrelated content
    (e.g. "Não" from a button click) into the LLM call.

    Args:
        state: BOState (required by wrap_model interface, not used directly)
        system_prompt: The formatted system prompt for this LLM call
    """
    return [system_prompt, HumanMessage(content="Execute a tarefa.")]


def wrap_model(
    model: BaseChatModel | Runnable[LanguageModelInput, Any],
    system_prompt: BaseMessage,
    *,
    node_name: str | None = None,
    tier: str | None = None,
) -> RunnableSerializable[BOState, Any]:
    """Wrapper for the model with state preprocessing and timeout/fallback.

    Pass ``node_name`` (and optionally ``tier``) to propagate telemetry
    metadata to LangSmith via the config argument at invoke time. This is
    robust to the inner runnable shape (works with RunnableSequence from
    ``with_structured_output``, RunnableBinding, etc.).
    """
    preprocessor = RunnableLambda(
        lambda state: _prepare_messages(cast(BOState, state), system_prompt),
        name="StateModifier",
    )
    return preprocessor | RunnableWithFallback(inner=model, node_name=node_name, tier=tier)


def _prepare_context_with_scratchpad(state: BOState, system_prompt: BaseMessage):
    """Helper function to prepare messages with scratchpad context.

    Uses scratchpad as HumanMessage when available, otherwise uses a fixed
    trigger to satisfy vLLM/json_schema requirement.
    """
    scratchpad_content = state.get("scratchpad", "")

    if scratchpad_content:
        context_message = HumanMessage(content=f"INFORMAÇÕES JÁ COLETADAS:\n{scratchpad_content}")
        return [system_prompt, context_message]

    return [system_prompt, HumanMessage(content="Execute a tarefa.")]


def wrap_model_scratchpad(
    model: BaseChatModel | Runnable[LanguageModelInput, Any],
    system_prompt: BaseMessage,
    *,
    node_name: str | None = None,
    tier: str | None = None,
) -> RunnableSerializable[BOState, Any]:
    """Wrapper for the model with scratchpad context preprocessing and timeout/fallback.

    See ``wrap_model`` for the ``node_name`` / ``tier`` telemetry contract.
    """
    preprocessor = RunnableLambda(
        lambda state: _prepare_context_with_scratchpad(cast(BOState, state), system_prompt),
        name="StateModifier",
    )
    return preprocessor | RunnableWithFallback(inner=model, node_name=node_name, tier=tier)


def get_last_user_message(state: BOState) -> str:
    """Extract the last user message from state."""
    if state.get("messages"):
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                return str(msg.content)
    return ""


def is_redirect(result: Any) -> bool:
    """Check if result is a redirect response."""
    return isinstance(result, dict) and result.get("_redirect") is True


def get_redirect_state(result: dict) -> dict:
    """Extract redirect state from result dict."""
    return {"redirect": RedirectInfo(**result["redirect"])}
