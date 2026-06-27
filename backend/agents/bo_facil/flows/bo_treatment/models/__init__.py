"""Pydantic models for bo_treatment flows.

Organized by domain:
- common: Core models (classification, summary, unified extraction)
- object: Object and weapon models
- person: Person/suspect models
- victim: Victim models
- damage: Damage/loss models
- edit: Edit operation models
"""

from .common import (
    BODescription,
    DatetimeExtraction,
    FactExtraction,
    IncidentClassification,
    LocationExtraction,
    UnifiedIncidentExtraction,
    UserChoiceAnalysis,
)
from .damage import (
    DamageAnalysis,
    DamageConfirmation,
    DamageData,
    DamageValueExtraction,
)
from .edit import (
    EditDiff,
    EditedObject,
    EditedPerson,
    EditedWeapon,
    ObjectUpdate,
    PersonUpdate,
    WeaponUpdate,
)
from .object import (
    BOObject,
    BOWeapon,
    FollowUpObjectDiff,
    ObjectFieldUpdate,
    ObjectType,
    UnifiedObjectExtraction,
    WeaponAnalysis,
)
from .person import (
    BasicPersonInfo,
    InvolvedPerson,
    PersonAnalysis,
)
from .victim import (
    ThirdPartyReporterAnalysis,
)

__all__ = [
    # Common models
    "BODescription",
    "IncidentClassification",
    "FactExtraction",
    "DatetimeExtraction",
    "LocationExtraction",
    "UnifiedIncidentExtraction",
    "UserChoiceAnalysis",
    # Object models
    "BOObject",
    "BOWeapon",
    "FollowUpObjectDiff",
    "ObjectFieldUpdate",
    "ObjectType",
    "UnifiedObjectExtraction",
    "WeaponAnalysis",
    # Person models
    "BasicPersonInfo",
    "InvolvedPerson",
    "PersonAnalysis",
    # Damage models
    "DamageAnalysis",
    "DamageConfirmation",
    "DamageData",
    "DamageValueExtraction",
    # Victim models
    "ThirdPartyReporterAnalysis",
    # Edit models
    "EditDiff",
    "EditedObject",
    "EditedPerson",
    "EditedWeapon",
    "ObjectUpdate",
    "PersonUpdate",
    "WeaponUpdate",
]
