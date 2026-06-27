"""Context builder for BO description generation.

This module provides the context string used by the LLM to generate
the formal PDF description ("Consta dos presentes autos que...").
"""

import re


def build_description_context(
    fact: str | None,
    datetime_info: str | None,
    location: str | None,
    bo_objects: list[dict] | None = None,
    bo_weapons: list[dict] | None = None,
    bo_persons: list[dict] | None = None,
    has_damage: bool | None = None,
    damage_value: float | None = None,
    damage_payment_method: str | None = None,
) -> str:
    """Build context string for LLM description generation.

    This creates a structured context that the LLM uses to generate
    the formal PDF description ("Consta dos presentes autos que...").

    Args:
        fact: The incident description
        datetime_info: Date and time information
        location: Location information (includes address and reference points)
        bo_objects: List of stolen/lost objects
        bo_weapons: List of weapons used
        bo_persons: List of involved persons (name, type, description)
        has_damage: Whether financial damage occurred
        damage_value: Damage value in BRL
        damage_payment_method: Payment method used

    Returns:
        Structured context string for LLM prompt
    """
    context_parts = []

    if fact:
        context_parts.append(f"FATO: {fact}")

    if datetime_info:
        context_parts.append(f"DATA/HORA: {datetime_info}")

    if location:
        context_parts.append(f"LOCAL: {location}")

    if bo_weapons:
        weapon_details = []
        for w in bo_weapons:
            if isinstance(w, dict):
                tipo = w.get("type", "arma")
                desc = w.get("description", "")
                detail = tipo
                if desc:
                    detail += f" ({desc})"
                weapon_details.append(detail)
        if weapon_details:
            context_parts.append(
                f"OBJETO(S) UTILIZADO(S) PELO AGRESSOR: {', '.join(weapon_details)}"
            )

    if bo_objects:
        obj_details = []
        for obj in bo_objects:
            if isinstance(obj, dict):
                name = obj.get("name", "objeto")
                obj_type = obj.get("type", "")

                # Build detail string with all available information
                detail_parts = [name]
                if obj_type and obj_type != "outro":
                    detail_parts[0] = f"{name} ({obj_type})"

                # Add descriptive attributes
                attrs = []
                if obj.get("brand"):
                    attrs.append(f"marca {obj['brand']}")
                if obj.get("model"):
                    attrs.append(f"modelo {obj['model']}")
                if obj.get("color"):
                    attrs.append(f"cor {obj['color']}")
                if obj.get("imei"):
                    attrs.append(f"IMEI {obj['imei']}")
                if obj.get("plate"):
                    attrs.append(f"placa {obj['plate']}")
                if obj.get("document_number"):
                    attrs.append(f"documento {obj['document_number']}")
                # Strip already-captured values from description, keep novel info
                if obj.get("description"):
                    remaining = obj["description"]
                    for key in ("color", "brand", "model", "name"):
                        val = obj.get(key)
                        if val:
                            remaining = re.sub(re.escape(val), "", remaining, flags=re.IGNORECASE)
                    remaining = re.sub(r"[,;]\s*[,;]", ",", remaining)
                    remaining = re.sub(r"\s{2,}", " ", remaining).strip(" ,;-")
                    if remaining and len(remaining) > 2:
                        attrs.append(remaining)

                if attrs:
                    detail_parts.append(", ".join(attrs))

                obj_details.append(
                    " - ".join(detail_parts) if len(detail_parts) > 1 else detail_parts[0]
                )
        if obj_details:
            context_parts.append(f"OBJETOS SUBTRAÍDOS/ENVOLVIDOS: {'; '.join(obj_details)}")

    if bo_persons:
        person_summaries = []
        for p in bo_persons:
            if isinstance(p, dict):
                p_type = p.get("type", "envolvido")
                p_name = p.get("name", "desconhecido")
                p_desc = p.get("description", "")
                summary = f"{p_type}: {p_name}"
                if p_desc:
                    summary += f" - {p_desc}"
                person_summaries.append(summary)
        if person_summaries:
            context_parts.append(f"PESSOAS ENVOLVIDAS: {'; '.join(person_summaries)}")

    if has_damage:
        damage_parts = []
        if damage_value is not None:
            formatted_value = (
                f"R$ {damage_value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            )
            damage_parts.append(f"valor de {formatted_value}")
        if damage_payment_method:
            damage_parts.append(f"forma de pagamento: {damage_payment_method}")
        if damage_parts:
            context_parts.append(f"PREJUÍZO FINANCEIRO: {', '.join(damage_parts)}")

    return "\n".join(context_parts)
