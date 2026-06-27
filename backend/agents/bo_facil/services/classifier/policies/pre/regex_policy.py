"""Regex-based policy for fast-path classification.

Detects emergency keywords, human handoff requests, button responses,
and simple data inputs without using LLM.
"""

import logging
import re

from ...models import ClassificationClass
from ..base import PolicyAction, PolicyBase, PolicyContext, PolicyResult

logger = logging.getLogger(__name__)


class RegexPolicy(PolicyBase):
    """Policy that uses regex patterns for fast classification.

    Priority: 10 (executes early in the chain)

    This policy handles:
    1. Emergency keywords: Immediately routes to emergency
    2. Human handoff keywords: Immediately routes to human
    3. Button responses: Skips classification (known UI interactions)
    4. Simple data inputs: Skips classification (CPF, IMEI, plate, etc.)

    Emergency detection uses a 3-layer gating system to avoid false positives
    from narrative mentions (e.g. "a mulher gritou por socorro"):
    - Layer 1: Length gate - real SOS messages are short
    - Layer 2: Narrative exclusion - 3rd person past tense context
    - Layer 3: Flow context gate - stricter threshold inside BO treatment
    """

    name = "regex"
    priority = 10

    # Max message length for regex-based emergency detection.
    # Real SOS messages are short and urgent; longer messages are narratives.
    EMERGENCY_MAX_LENGTH = 200

    # Stricter threshold when user is already inside BO treatment,
    # where crime narratives naturally contain emergency-related words.
    EMERGENCY_MAX_LENGTH_IN_BO = 120

    # Emergency patterns - words indicating immediate danger
    # Tolerant of repeated letters (panic typing: "socorrooo", "ajudaaa")
    # and common typos ("socoro", "ajud")
    EMERGENCY_PATTERNS = [
        re.compile(r"\b(socor+o+)\b"),  # socorro, socorrooo, socoro
        re.compile(r"\b(me\s+ajud[ae]a*)\b"),  # me ajuda, me ajudaaa, me ajude
        re.compile(r"\b(ajud[ae]a*\s+por\s+favor)\b"),  # ajuda por favor, ajudaaa por favor
        re.compile(r"\b(estao me|estão me)\b"),
        re.compile(r"\b(to sendo|tô sendo)\b"),
        re.compile(r"\b(pelo amor de deus)\b"),
        re.compile(r"\b(emergencia+|emergência+)\b"),  # emergencia, emergenciaaaa
        re.compile(r"\b(me\s+salv[ae]a*)\b"),  # me salva, me salve, me salvaaa
        re.compile(r"\b(sos)\b"),  # SOS
    ]

    # Patterns indicating 3rd-person / past-tense narrative usage of emergency words.
    # When ALL emergency keyword matches fall within these contexts,
    # the message is a narrative, not a real-time SOS.
    NARRATIVE_EMERGENCY_PATTERNS = [
        re.compile(r"grit(?:ou|ando|aram|ava)\s+(?:por\s+)?socor+o+"),
        re.compile(r"ped(?:iu|indo|iram|ia)\s+(?:por\s+)?socor+o+"),
        re.compile(r"grit(?:ou|ando|aram|ava)\s+(?:por\s+)?ajud[ae]"),
        re.compile(r"ped(?:iu|indo|iram|ia)\s+(?:por\s+)?ajud[ae]"),
        re.compile(r"cham(?:ou|ando|aram|ava)\s+(?:por\s+)?socor+o+"),
    ]

    # Human handoff patterns - explicit request for human agent
    HUMAN_HANDOFF_PATTERNS = [
        re.compile(r"\b(quero|preciso)\s+(falar\s+com\s+)?(um\s+)?(atendente|humano|pessoa)\b"),
        re.compile(r"\b(quero|preciso)\s+atendimento\s+humano\b"),
        re.compile(r"\b(n[aã]o\s+quero)\s+falar\s+com\s+(rob[oô]|bot|maquina|máquina)\b"),
        re.compile(r"\b(transferir|transfere)\s+(para\s+)?(um\s+)?(humano|atendente)\b"),
        re.compile(r"\bfalar\s+com\s+algu[eé]m\b"),
        re.compile(r"\batendente\s+humano\b"),
    ]

    # Cancel/exit patterns - user wants to leave the flow
    # Length-gated like emergency: short messages only (narratives may contain these words)
    CANCEL_MAX_LENGTH = 120

    CANCEL_PATTERNS = [
        re.compile(r"^(cancelar|sair|encerrar|desisto)$"),
        re.compile(r"\b(quero|preciso|vou)\s+(sair|encerrar|parar|cancelar|desistir)\b"),
        re.compile(r"\bn[aã]o\s+quero\s+mais\b"),
        re.compile(r"\bdeixa\s+pra\s+l[aá]\b"),
        re.compile(r"\b(encerrar|cancelar|sair)\s+(d?o\s+)?(atendimento|bo|b\.o)\b"),
        re.compile(r"\bpode\s+parar\b"),
        re.compile(r"\besquece\b"),
    ]

    # Button response patterns - known UI button responses (skip classification)
    BUTTON_RESPONSE_PATTERNS = [
        # Confirmation buttons
        re.compile(r"^(sim|s|yes|y)$"),
        re.compile(r"^(n[aã]o|nao|no|n)$"),
        # Action buttons
        re.compile(r"^(prosseguir|continuar|avancar|avançar|próximo|proximo)$"),
        re.compile(r"^(alterar|editar|corrigir|mudar)$"),
        re.compile(r"^(voltar)$"),
        re.compile(r"^(confirmar|confirmo)$"),
        # Service menu buttons
        re.compile(r"^(bo\s*f[aá]cil|fazer\s*bo(?:\s*f[aá]cil)?|registrar\s*bo)$"),
        re.compile(r"^(den[uú]ncia\s*an[oô]nima|denuncia\s*anonima)$"),
        re.compile(r"^(atendimento\s*(?:190|urgente)|ligar\s*190|190)$"),
        # Button IDs (from WhatsApp buttons)
        re.compile(r"^(bo_facil|denuncia_anonima|atendimento_190)$"),
        re.compile(r"^(help_yes|help_no)$"),
        re.compile(r"^(confirm_yes|confirm_no)$"),
        re.compile(r"^(edit_.*|change_.*)$"),
    ]

    # Simple data patterns - structured data inputs
    SIMPLE_DATA_PATTERNS = [
        re.compile(r"^[A-Z0-9]{7}$"),  # Placa (7 chars alphanumeric)
        re.compile(r"^\d{14,15}$"),  # IMEI (14-15 digits)
        re.compile(r"^\d{11}$"),  # CPF without formatting
        re.compile(r"^\d{3}\.\d{3}\.\d{3}-\d{2}$"),  # CPF with formatting
        re.compile(r"^\d{2,3}\s?\d{4,5}-?\d{4}$"),  # Phone number
        re.compile(r"^\d{2,4}-\d{2}-\d{2}$"),  # Date format
    ]

    def _is_in_bo_treatment(self, context: PolicyContext) -> bool:
        """Check if user is already inside BO treatment flow."""
        if not context.state:
            return False
        classification = context.state.get("classification", {})
        cls_type = (
            classification.get("type")
            if isinstance(classification, dict)
            else getattr(classification, "type", None)
        )
        return cls_type == "bo_facil"

    def _has_narrative_context(self, text: str) -> bool:
        """Check if emergency keywords appear only in narrative context.

        Returns True when ALL occurrences of emergency words are used in
        3rd-person / past-tense constructions (e.g. "gritou por socorro").
        """
        return any(p.search(text) for p in self.NARRATIVE_EMERGENCY_PATTERNS)

    async def execute(self, context: PolicyContext) -> PolicyResult:
        """Check for patterns that can be resolved without LLM.

        Args:
            context: Policy context with user input

        Returns:
            RESOLVE for known patterns, CONTINUE otherwise
        """
        text = context.user_input

        if not text or len(text.strip()) < 1:
            return PolicyResult(action=PolicyAction.CONTINUE)

        text_stripped = text.strip()
        text_lower = text_stripped.lower()

        # 1. Check emergency patterns (highest priority) with 3-layer gating
        emergency_matches = [p for p in self.EMERGENCY_PATTERNS if p.search(text_lower)]

        if emergency_matches:
            in_bo = self._is_in_bo_treatment(context)
            max_len = self.EMERGENCY_MAX_LENGTH_IN_BO if in_bo else self.EMERGENCY_MAX_LENGTH
            msg_len = len(text_stripped)

            # Layer 1: Long messages are narratives, not real-time SOS
            if msg_len > max_len:
                logger.info(
                    f"[RegexPolicy] Emergency keyword in long message "
                    f"({msg_len} chars > {max_len}), deferring to LLM"
                )
            # Layer 2: Keyword used in 3rd-person narrative context
            elif self._has_narrative_context(text_lower):
                logger.info(
                    "[RegexPolicy] Emergency keyword in narrative context, deferring to LLM"
                )
            else:
                # Short + direct + no narrative context = genuine emergency
                return PolicyResult(
                    action=PolicyAction.RESOLVE,
                    classification=ClassificationClass.EMERGENCY,
                    confidence=0.95,
                    reason=f"Emergency keyword detected: {emergency_matches[0]}",
                )

        # 2. Check human handoff patterns
        for pattern in self.HUMAN_HANDOFF_PATTERNS:
            if pattern.search(text_lower):
                return PolicyResult(
                    action=PolicyAction.RESOLVE,
                    classification=ClassificationClass.HUMAN,
                    confidence=0.95,
                    reason=f"Human handoff request detected: {pattern}",
                )

        # 3. Check cancel/exit patterns (length-gated)
        if len(text_stripped) <= self.CANCEL_MAX_LENGTH:
            for pattern in self.CANCEL_PATTERNS:
                if pattern.search(text_lower):
                    return PolicyResult(
                        action=PolicyAction.RESOLVE,
                        classification=ClassificationClass.CANCEL,
                        confidence=0.95,
                        reason=f"Cancel/exit request detected: {pattern}",
                    )

        # 4. Check button response patterns (skip classification)
        for pattern in self.BUTTON_RESPONSE_PATTERNS:
            if pattern.match(text_lower):
                return PolicyResult(
                    action=PolicyAction.RESOLVE,
                    classification=ClassificationClass.NEUTRAL,
                    confidence=1.0,
                    reason="Button response - skip classification",
                )

        # 5. Check simple data patterns (skip classification)
        for pattern in self.SIMPLE_DATA_PATTERNS:
            if pattern.match(text_stripped.upper()):
                return PolicyResult(
                    action=PolicyAction.RESOLVE,
                    classification=ClassificationClass.NEUTRAL,
                    confidence=1.0,
                    reason="Simple data input - skip classification",
                )

        # 6. Short numeric-only inputs (skip classification)
        text_clean = (
            text_stripped.replace(" ", "").replace("-", "").replace(".", "").replace("/", "")
        )
        if len(text_stripped) <= 10 and text_clean.isdigit():
            return PolicyResult(
                action=PolicyAction.RESOLVE,
                classification=ClassificationClass.NEUTRAL,
                confidence=1.0,
                reason="Short numeric input - skip classification",
            )

        return PolicyResult(action=PolicyAction.CONTINUE)
