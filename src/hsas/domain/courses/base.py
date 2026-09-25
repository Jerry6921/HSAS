from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Base schema that rejects undeclared fields."""

    model_config = ConfigDict(extra="forbid")
