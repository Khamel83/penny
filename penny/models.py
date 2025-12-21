"""Pydantic models for Penny."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid


class IngestRequest(BaseModel):
    """Request to ingest transcribed text."""
    text: str = Field(..., description="Transcribed text content")
    source_file: Optional[str] = Field(None, description="Original audio filename")
    timestamp: Optional[datetime] = Field(None, description="When the recording was made")


class Item(BaseModel):
    """A transcribed and classified item."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    text: str
    classification: str = "unknown"  # work | personal | shopping | unknown
    confidence: float = 0.0
    source_file: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    routed_to: Optional[str] = None  # atlas | trojanhorse | shopping | None


class ReclassifyRequest(BaseModel):
    """Request to reclassify an item."""
    classification: str = Field(..., pattern="^(work|personal|shopping|unknown)$")


class ItemResponse(BaseModel):
    """Response containing an item."""
    item: Item
    message: str = "success"


class ItemsResponse(BaseModel):
    """Response containing multiple items."""
    items: list[Item]
    total: int
    page: int = 1
    per_page: int = 50
