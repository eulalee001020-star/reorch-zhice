"""Base Pydantic model configuration for the ReOrch system.

All Pydantic schemas should inherit from ``ReOrchModel`` to get
consistent serialization, ORM compatibility, and validation behaviour.
"""

from pydantic import BaseModel, ConfigDict


class ReOrchModel(BaseModel):
    """Project-wide base model with shared Pydantic v2 config."""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=True,
        str_strip_whitespace=True,
    )
