"""GovChat API client based on Chatwoot API specification."""

import logging
from typing import Any

import httpx

from core.observability import traced_external_call
from core.settings import settings

from .exceptions import (
    GovChatApiError,
    GovChatConfigError,
    GovChatConnectionError,
    GovChatTimeoutError,
)
from .models import (
    AssignConversationRequest,
    AttributeDisplayType,
    AttributeModel,
    ConversationStatus,
    CreateAttributeDefinitionRequest,
    CreateConversationRequest,
    Priority,
    TogglePriorityRequest,
    ToggleStatusRequest,
    UpdateContactRequest,
    UpdateConversationCustomAttributesRequest,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10.0


class GovChatClient:
    """Async client for GovChat (Chatwoot-based) API.

    When GOVCHAT_ENABLED is False, all API calls return mock responses
    without making real HTTP requests. This is useful for testing.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_token: str | None = None,
        account_id: str | None = None,
        enabled: bool | None = None,
    ):
        """
        Initialize GovChat client.

        Args:
            base_url: API base URL. Defaults to settings.GOVCHAT_API_URL
            api_token: API access token. Defaults to settings.GOVCHAT_API_TOKEN
            account_id: Account ID. Defaults to settings.GOVCHAT_ACCOUNT_ID
            enabled: Whether to make real API calls. Defaults to settings.GOVCHAT_ENABLED
        """
        self.base_url = base_url or settings.GOVCHAT_API_URL
        self.account_id = account_id or settings.GOVCHAT_ACCOUNT_ID
        self.enabled = enabled if enabled is not None else settings.GOVCHAT_ENABLED

        # Get API token
        if api_token:
            self.api_token = api_token
        elif settings.GOVCHAT_API_TOKEN:
            self.api_token = settings.GOVCHAT_API_TOKEN.get_secret_value()
        else:
            self.api_token = None

        self._client: httpx.AsyncClient | None = None

        if not self.enabled:
            logger.info("[GovChat] Running in MOCK mode (GOVCHAT_ENABLED=false)")

    def _validate_config(self) -> None:
        """Validate that required configuration is present."""
        if not self.api_token:
            raise GovChatConfigError("GOVCHAT_API_TOKEN is not configured")
        if not self.account_id:
            raise GovChatConfigError("GOVCHAT_ACCOUNT_ID is not configured")

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        self._validate_config()

        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=f"{self.base_url}/accounts/{self.account_id}",
                headers={
                    "api_access_token": self.api_token,
                    "Content-Type": "application/json",
                },
                timeout=REQUEST_TIMEOUT,
            )
        return self._client

    @traced_external_call(name="govchat_request", dep="govchat")
    async def _request(
        self,
        method: str,
        endpoint: str,
        json: dict | None = None,
        params: dict | None = None,
        *,
        _max_retries: int = 2,
    ) -> dict[str, Any]:
        """
        Make an HTTP request to the GovChat API with automatic retry.

        Retries on transient failures (DNS resolution, connection reset,
        timeout) with exponential backoff. API-level errors (4xx/5xx) are
        NOT retried — those indicate a problem with the request itself.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (e.g., "/conversations/123/custom_attributes")
            json: Request body as dict
            params: Query parameters

        Returns:
            Response data as dict

        Raises:
            GovChatApiError: If API returns an error response
            GovChatConnectionError: If connection fails after all retries
            GovChatTimeoutError: If request times out after all retries
        """
        import asyncio

        last_error: Exception | None = None

        for attempt in range(_max_retries + 1):
            try:
                if attempt == 0:
                    logger.info(f"[GovChat] {method} {endpoint}")
                else:
                    logger.info(f"[GovChat] {method} {endpoint} (retry {attempt}/{_max_retries})")

                response = await self.client.request(
                    method=method,
                    url=endpoint,
                    json=json,
                    params=params,
                )

                if response.status_code >= 400:
                    error_msg = response.text[:500] if response.text else "Unknown error"
                    logger.error(f"[GovChat] API error {response.status_code}: {error_msg}")
                    raise GovChatApiError(response.status_code, error_msg)

                # Return empty dict for 204 No Content or empty body
                if response.status_code == 204 or not response.text or not response.text.strip():
                    if response.status_code != 204 and not response.text:
                        logger.warning(
                            f"[GovChat] Empty response body (status {response.status_code})"
                        )
                    return {}

                try:
                    return response.json()
                except ValueError:
                    logger.warning(
                        f"[GovChat] Invalid JSON response (status {response.status_code}): "
                        f"{response.text[:200]}"
                    )
                    return {}

            except httpx.TimeoutException as e:
                last_error = GovChatTimeoutError(f"Request timed out: {e}")
                logger.warning(f"[GovChat] Timeout on attempt {attempt + 1}: {e}")

            except httpx.ConnectError as e:
                last_error = GovChatConnectionError(f"Connection failed: {e}")
                logger.warning(f"[GovChat] Connection error on attempt {attempt + 1}: {e}")

            except GovChatApiError:
                raise  # 4xx/5xx — don't retry

            except Exception as e:
                last_error = GovChatConnectionError(f"Unexpected error: {e}")
                logger.warning(f"[GovChat] Unexpected error on attempt {attempt + 1}: {e}")

            # Exponential backoff before next retry (0.5s, 1s)
            if attempt < _max_retries:
                await asyncio.sleep(0.5 * (2**attempt))

        # All retries exhausted
        logger.error(f"[GovChat] All {_max_retries + 1} attempts failed for {method} {endpoint}")
        raise last_error

    # =========================================================================
    # Mock Responses
    # =========================================================================

    def _mock_response(self, operation: str, **kwargs: Any) -> dict:
        """Generate a mock response for testing."""
        logger.info(f"[GovChat MOCK] {operation}: {kwargs}")
        return {"success": True, "mock": True, **kwargs}

    # =========================================================================
    # Contact Operations
    # =========================================================================

    async def update_contact_attribute(
        self,
        contact_id: int,
        attribute_key: str,
        value: str | int | bool,
    ) -> dict:
        """
        Update a custom attribute on a contact.

        PUT /api/v1/accounts/{account_id}/contacts/{id}

        Args:
            contact_id: Contact ID
            attribute_key: Attribute key (e.g., "cpf", "protocolo")
            value: Attribute value

        Returns:
            Updated contact data
        """
        if not self.enabled:
            return self._mock_response(
                "update_contact_attribute",
                contact_id=contact_id,
                attribute_key=attribute_key,
                value=value,
            )

        logger.info(f"[GovChat] Updating contact {contact_id} attribute: {attribute_key}={value}")

        request = UpdateContactRequest(custom_attributes={attribute_key: value})

        return await self._request(
            method="PUT",
            endpoint=f"/contacts/{contact_id}",
            json=request.model_dump(exclude_none=True),
        )

    # =========================================================================
    # Conversation Operations
    # =========================================================================

    async def create_conversation(
        self,
        inbox_id: int,
        contact_id: int,
        status: ConversationStatus = ConversationStatus.OPEN,
        source_id: str | None = None,
    ) -> dict:
        """
        Create a new conversation.

        POST /api/v1/accounts/{account_id}/conversations

        Args:
            inbox_id: Inbox (channel) ID
            contact_id: Contact ID
            status: Initial status (defaults to OPEN)
            source_id: Optional unique source identifier

        Returns:
            Created conversation data (includes 'id' field)
        """
        if not self.enabled:
            return self._mock_response(
                "create_conversation",
                inbox_id=inbox_id,
                contact_id=contact_id,
                id=99999,
            )

        logger.info(f"[GovChat] Creating conversation: inbox={inbox_id}, contact={contact_id}")

        request = CreateConversationRequest(
            inbox_id=inbox_id,
            contact_id=contact_id,
            status=status,
            source_id=source_id,
        )

        return await self._request(
            method="POST",
            endpoint="/conversations",
            json=request.model_dump(exclude_none=True),
        )

    async def update_conversation_attribute(
        self,
        conversation_id: int,
        attribute_key: str,
        value: str | int | bool,
    ) -> dict:
        """
        Update a custom attribute on a conversation.

        POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/custom_attributes

        Args:
            conversation_id: Conversation ID
            attribute_key: Attribute key (e.g., "protocolo", "tipo_ocorrencia")
            value: Attribute value

        Returns:
            Updated custom attributes
        """
        if not self.enabled:
            return self._mock_response(
                "update_conversation_attribute",
                conversation_id=conversation_id,
                attribute_key=attribute_key,
                value=value,
            )

        logger.info(
            f"[GovChat] Updating conversation {conversation_id} attribute: {attribute_key}={value}"
        )

        request = UpdateConversationCustomAttributesRequest(
            custom_attributes={attribute_key: value}
        )

        return await self._request(
            method="POST",
            endpoint=f"/conversations/{conversation_id}/custom_attributes",
            json=request.model_dump(),
        )

    async def set_priority(
        self,
        conversation_id: int,
        priority: Priority,
    ) -> dict:
        """
        Set conversation priority.

        POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/toggle_priority

        Args:
            conversation_id: Conversation ID
            priority: Priority level (URGENT, HIGH, MEDIUM, LOW, NONE)

        Returns:
            Success status
        """
        if not self.enabled:
            return self._mock_response(
                "set_priority",
                conversation_id=conversation_id,
                priority=priority.value,
            )

        logger.info(f"[GovChat] Setting conversation {conversation_id} priority: {priority.value}")

        request = TogglePriorityRequest(priority=priority)

        return await self._request(
            method="POST",
            endpoint=f"/conversations/{conversation_id}/toggle_priority",
            json=request.model_dump(),
        )

    async def assign_team(
        self,
        conversation_id: int,
        team_id: int,
    ) -> dict:
        """
        Assign conversation to a team.

        POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/assignments

        Args:
            conversation_id: Conversation ID
            team_id: Team ID to assign

        Returns:
            Assignment result (user object)
        """
        if not self.enabled:
            return self._mock_response(
                "assign_team",
                conversation_id=conversation_id,
                team_id=team_id,
            )

        logger.info(f"[GovChat] Assigning conversation {conversation_id} to team {team_id}")

        request = AssignConversationRequest(team_id=team_id)

        return await self._request(
            method="POST",
            endpoint=f"/conversations/{conversation_id}/assignments",
            json=request.model_dump(exclude_none=True),
        )

    async def resolve_conversation(
        self,
        conversation_id: int,
        status: ConversationStatus = ConversationStatus.RESOLVED,
        snoozed_until: int | None = None,
    ) -> dict:
        """
        Resolve or change conversation status.

        POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/toggle_status

        Args:
            conversation_id: Conversation ID
            status: New status (OPEN, RESOLVED, PENDING, SNOOZED)
            snoozed_until: Unix timestamp for reopen time when status is SNOOZED

        Returns:
            Toggle status response with current_status and success
        """
        if not self.enabled:
            return self._mock_response(
                "resolve_conversation",
                conversation_id=conversation_id,
                status=status.value,
            )

        logger.info(f"[GovChat] Setting conversation {conversation_id} status: {status.value}")

        request = ToggleStatusRequest(status=status, snoozed_until=snoozed_until)

        return await self._request(
            method="POST",
            endpoint=f"/conversations/{conversation_id}/toggle_status",
            json=request.model_dump(exclude_none=True),
        )

    # =========================================================================
    # Custom Attribute Definitions
    # =========================================================================

    async def create_attribute(
        self,
        attribute_key: str,
        attribute_type: AttributeDisplayType,
        display_name: str,
        model: AttributeModel = AttributeModel.CONVERSATION,
        description: str | None = None,
        attribute_values: list[str] | None = None,
        regex_pattern: str | None = None,
        regex_cue: str | None = None,
    ) -> dict:
        """
        Create a new custom attribute definition in the account.

        POST /api/v1/accounts/{account_id}/custom_attribute_definitions

        Args:
            attribute_key: Unique key for the attribute (e.g., "protocolo")
            attribute_type: Data type (TEXT, NUMBER, CURRENCY, PERCENT, LINK, DATE, LIST, CHECKBOX)
            display_name: Display name shown in UI
            model: Model type (CONVERSATION or CONTACT)
            description: Optional description
            attribute_values: Predefined values for LIST type
            regex_pattern: Validation pattern for TEXT type
            regex_cue: User message when validation fails

        Returns:
            Created attribute definition
        """
        if not self.enabled:
            return self._mock_response(
                "create_attribute",
                attribute_key=attribute_key,
                attribute_type=attribute_type.value,
                display_name=display_name,
                model=model.value,
            )

        logger.info(
            f"[GovChat] Creating attribute definition: {attribute_key} (type={attribute_type.value})"
        )

        request = CreateAttributeDefinitionRequest(
            attribute_key=attribute_key,
            attribute_display_type=attribute_type.value,
            attribute_display_name=display_name,
            attribute_model=model.value,
            attribute_description=description,
            attribute_values=attribute_values,
            regex_pattern=regex_pattern,
            regex_cue=regex_cue,
        )

        return await self._request(
            method="POST",
            endpoint="/custom_attribute_definitions",
            json=request.model_dump(exclude_none=True),
        )

    async def list_attributes(
        self,
        model: AttributeModel | None = None,
    ) -> list[dict]:
        """
        List custom attribute definitions.

        GET /api/v1/accounts/{account_id}/custom_attribute_definitions

        Args:
            model: Filter by model type (CONVERSATION or CONTACT)

        Returns:
            List of attribute definitions
        """
        if not self.enabled:
            return [
                self._mock_response(
                    "list_attributes",
                    model=model.value if model else None,
                )
            ]

        logger.info(f"[GovChat] Listing attribute definitions (model={model})")

        params = {}
        if model is not None:
            params["attribute_model"] = model.value

        return await self._request(
            method="GET",
            endpoint="/custom_attribute_definitions",
            params=params if params else None,
        )

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            logger.info("[GovChat] Client closed")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# =============================================================================
# Singleton Instance
# =============================================================================

_govchat_client: GovChatClient | None = None


def get_govchat_client() -> GovChatClient:
    """Get or create singleton GovChat client."""
    global _govchat_client
    if _govchat_client is None:
        _govchat_client = GovChatClient()
    return _govchat_client


# Convenience alias
govchat_client = get_govchat_client
