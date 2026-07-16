from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=3, max_length=80)


class ProjectCreate(BaseModel):
    organization_id: str
    name: str = Field(min_length=2, max_length=180)
    slug: str = Field(min_length=3, max_length=100)
    description: str | None = Field(default=None, max_length=4000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, max_length=4000)
    status: str | None = Field(default=None, pattern=r"^(draft|review|published|paused|archived)$")
    access_mode: str | None = Field(default=None, pattern=r"^(private|password|unlisted|public|link)$")
    client_can_edit: bool | None = None


class LotPatch(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    block: str | None = Field(default=None, max_length=120)
    area_m2: float | None = None
    status: str | None = Field(default=None, pattern=r"^(available|sold|reserved|blocked|unknown)$")
    color: str | None = Field(default=None, max_length=24)
    geometry: dict[str, Any] | None = None
    properties: dict[str, Any] | None = None


class LotBatchPatch(BaseModel):
    lot_ids: list[str] = Field(min_length=1, max_length=500)
    changes: LotPatch


class ShareLinkCreate(BaseModel):
    access_mode: str = Field(default="token", pattern=r"^(token|password|public|private)$")
    password: str | None = Field(default=None, max_length=128)
    allow_edit: bool = False
    expires_at: datetime | None = None


class ShareLinkUpdate(BaseModel):
    active: bool | None = None
    password: str | None = Field(default=None, max_length=128)
    allow_edit: bool | None = None
    expires_at: datetime | None = None


class EditProposalCreate(BaseModel):
    title: str = Field(min_length=2, max_length=180)
    summary: str | None = Field(default=None, max_length=4000)
    changes: dict[str, Any]
    share_link_id: str | None = None


class ProposalDecision(BaseModel):
    notes: str | None = Field(default=None, max_length=4000)


class PublishVersionPayload(BaseModel):
    require_clean_validation: bool = True


class ProjectPublishPayload(BaseModel):
    access_mode: str = Field(default="private", pattern=r"^(private|password|unlisted|public)$")
    password: str | None = Field(default=None, max_length=128)
    allow_edit: bool = False
    require_clean_validation: bool = False
