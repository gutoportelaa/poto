"""Models for BO edit operations (diff-only approach)."""

from pydantic import BaseModel, Field


class EditedObject(BaseModel):
    """Object model for new objects added via edit."""

    name: str = Field(description="Object name")
    type: str = Field(default="outro", description="celular, documento, carro, moto, outro")
    brand: str | None = Field(default=None, description="Brand if applicable")
    model: str | None = Field(default=None, description="Model if applicable")
    color: str | None = Field(default=None, description="Color if applicable")
    imei: str | None = Field(default=None, description="IMEI for cellphones")
    document_number: str | None = Field(default=None, description="Document number")
    plate: str | None = Field(default=None, description="Vehicle plate")
    description: str | None = Field(default=None, description="Additional description")


class EditedWeapon(BaseModel):
    """Weapon model for new weapons added via edit."""

    type: str = Field(description="Weapon type: arma de fogo, faca, etc")
    description: str | None = Field(default=None, description="Additional description")


class EditedPerson(BaseModel):
    """Person model for new persons added via edit."""

    name: str = Field(description="Person identifier: Suspeito, Testemunha, etc")
    type: str = Field(default="outro_envolvido", description="suspeito, testemunha, outro")
    physical_description: str | None = Field(default=None, description="Physical description")
    phone: str | None = Field(default=None, description="Phone number")
    cpf: str | None = Field(default=None, description="CPF")
    address: str | None = Field(default=None, description="Address")
    description: str | None = Field(default=None, description="Additional description")


class ObjectUpdate(BaseModel):
    """Update specific fields of an existing object. None = no change."""

    target_name: str = Field(description="EXACT name from current data to identify the object")
    name: str | None = None
    type: str | None = None
    brand: str | None = None
    model: str | None = None
    color: str | None = None
    imei: str | None = None
    document_number: str | None = None
    plate: str | None = None
    description: str | None = None


class WeaponUpdate(BaseModel):
    """Update specific fields of an existing weapon. None = no change."""

    target_type: str = Field(description="EXACT type from current data to identify the weapon")
    type: str | None = None
    description: str | None = None


class PersonUpdate(BaseModel):
    """Update specific fields of an existing person. None = no change."""

    target_name: str = Field(description="EXACT name from current data to identify the person")
    name: str | None = None
    type: str | None = None
    physical_description: str | None = None
    phone: str | None = None
    cpf: str | None = None
    address: str | None = None
    description: str | None = None


class EditDiff(BaseModel):
    """Diff-only edit result. Only changed fields are populated."""

    changes_summary: str = Field(description="Brief description of what was changed (max 50 words)")

    # Scalar changes (None = unchanged)
    updated_fact: str | None = None
    updated_datetime: str | None = None
    updated_location: str | None = None

    # Object operations
    objects_to_add: list[EditedObject] = Field(default_factory=list)
    objects_to_remove: list[str] = Field(
        default_factory=list, description="Exact names of objects to remove"
    )
    objects_to_update: list[ObjectUpdate] = Field(default_factory=list)

    # Weapon operations
    weapons_to_add: list[EditedWeapon] = Field(default_factory=list)
    weapons_to_remove: list[str] = Field(
        default_factory=list, description="Exact types of weapons to remove"
    )
    weapons_to_update: list[WeaponUpdate] = Field(default_factory=list)

    # Person operations
    persons_to_add: list[EditedPerson] = Field(default_factory=list)
    persons_to_remove: list[str] = Field(
        default_factory=list, description="Exact names of persons to remove"
    )
    persons_to_update: list[PersonUpdate] = Field(default_factory=list)
