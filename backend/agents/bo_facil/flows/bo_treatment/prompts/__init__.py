"""LLM prompts for bo_treatment flows.

Organized by domain:
- common: Core prompts (classification, summary, unified extraction)
- object: Object collection and analysis prompts
- person: Person/suspect collection prompts
- victim: Victim collection prompts
- damage: Damage collection prompts
- edit: Edit operation prompts
"""

from .common import (
    datetime_extraction_prompt,
    description_generation_prompt,
    fact_extraction_prompt,
    incident_classification_prompt,
    location_extraction_prompt,
    user_choice_analysis_prompt,
)
from .damage import (
    confirmation_analysis_prompt,
    damage_analysis_prompt,
    damage_value_extraction_prompt,
)
from .edit import (
    edit_analysis_prompt,
    edit_description_prompt,
)
from .object import (
    followup_diff_prompt,
    object_used_analysis_prompt,
    unified_extraction_prompt,
)
from .person import (
    persons_analysis_prompt,
)
from .victim import (
    third_party_reporter_analysis_prompt,
)

__all__ = [
    # Common prompts
    "description_generation_prompt",
    "incident_classification_prompt",
    "fact_extraction_prompt",
    "datetime_extraction_prompt",
    "location_extraction_prompt",
    "user_choice_analysis_prompt",
    # Object prompts
    "followup_diff_prompt",
    "object_used_analysis_prompt",
    "unified_extraction_prompt",
    # Person prompts
    "persons_analysis_prompt",
    # Damage prompts
    "confirmation_analysis_prompt",
    "damage_analysis_prompt",
    "damage_value_extraction_prompt",
    # Victim prompts
    "third_party_reporter_analysis_prompt",
    # Edit prompts
    "edit_analysis_prompt",
    "edit_description_prompt",
]
