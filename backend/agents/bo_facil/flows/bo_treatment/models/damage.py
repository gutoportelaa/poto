"""Pydantic models for damage data collection."""

from typing import Literal

from pydantic import BaseModel, Field


class DamageAnalysis(BaseModel):
    """Model for initial damage detection from incident text."""

    has_damage: bool = Field(
        description="Whether financial damage was detected in the incident text"
    )
    damage_value: float | None = Field(
        default=None,
        description="Extracted damage value in BRL if detected, null otherwise",
    )
    payment_method: str | None = Field(
        default=None,
        description="Payment method used if detected (pix, cartao, transferencia, etc)",
    )


class DamageValueExtraction(BaseModel):
    """Model for extracting damage value from user input."""

    extracted_value: float | None = Field(
        default=None,
        description="Numeric value extracted from user input in BRL",
    )
    is_valid: bool = Field(
        description="Whether a valid numeric value was extracted",
    )
    no_damage: bool = Field(
        default=False,
        description=(
            "True ONLY when the user states there was NO financial loss at all "
            "(e.g. 'não houve prejuízo', 'eu não tive prejuízo financeiro', "
            "'prejuízo nenhum'). This contradicts an earlier damage confirmation. "
            "Do NOT set it when the user merely does not know or won't say the "
            "amount ('não sei o valor', 'não tenho como saber') — that is unknown "
            "value, not absence of damage."
        ),
    )


class DamageConfirmation(BaseModel):
    """Model for user confirmation response."""

    confirmed: bool = Field(
        description="Whether user confirmed the damage",
    )
    wants_to_correct: bool = Field(
        default=False,
        description="Whether user wants to correct the value",
    )


class DamageData(BaseModel):
    """Complete damage data collected."""

    has_damage: bool = Field(
        default=False,
        description="Whether financial damage occurred",
    )
    damage_value: float | None = Field(
        default=None,
        description="Damage value in BRL",
    )
    payment_method: (
        Literal[
            "pix",
            "cartao_credito",
            "cartao_debito",
            "transferencia",
            "deposito",
            "boleto",
            "dinheiro",
        ]
        | None
    ) = Field(
        default=None,
        description="Payment method used",
    )
    has_receipt: bool = Field(
        default=False,
        description="Whether user has a receipt to attach",
    )
    receipt_url: str | None = Field(
        default=None,
        description="URL of attached receipt if provided",
    )
