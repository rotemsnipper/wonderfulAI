"""Shared result envelope for every tool, and the error shape."""
from typing import Any

from pydantic import BaseModel, Field


class Definition(BaseModel):
    name: str
    label: str
    unit: str
    definition: str
    source: str
    period: str
    proxy_note: str | None = None


class ToolWarning(BaseModel):
    airport: str | None
    type: str
    severity: str
    message: str


class DataQuality(BaseModel):
    tier: str
    confidence: str
    reason: str


class Meta(BaseModel):
    airports: list[str] = Field(default_factory=list)
    uses_proxy: bool = False
    periods: dict[str, str] = Field(default_factory=dict)
    score_version: str | None = None
    resolved_by_default: bool = False


class Envelope(BaseModel):
    tool: str
    inputs: dict[str, Any]
    result: dict[str, Any]
    definitions: list[Definition] = Field(default_factory=list)
    warnings: list[ToolWarning] = Field(default_factory=list)
    data_quality: dict[str, DataQuality] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    meta: Meta = Field(default_factory=Meta)

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")


def error_result(error: str, valid_options: list | None = None) -> dict:
    return {"error": error, "valid_options": list(valid_options or [])}
