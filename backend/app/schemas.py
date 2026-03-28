from datetime import datetime
from pydantic import BaseModel, EmailStr

from .models import RelationshipType, ContactFrequency, InteractionType, LifeEventType


# ── User ──

class UserCreate(BaseModel):
    email: str
    name: str
    timezone: str = "UTC"


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    timezone: str
    plan: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Contact ──

class ContactCreate(BaseModel):
    name: str
    relationship_type: RelationshipType
    target_frequency: ContactFrequency = ContactFrequency.biweekly
    notes: str = ""


class ContactOut(BaseModel):
    id: int
    user_id: int
    name: str
    relationship_type: RelationshipType
    target_frequency: ContactFrequency
    notes: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Interaction ──

class InteractionCreate(BaseModel):
    contact_id: int
    interaction_type: InteractionType
    duration_minutes: int = 0
    initiated_by_user: bool = True
    notes: str = ""


class InteractionOut(BaseModel):
    id: int
    contact_id: int
    interaction_type: InteractionType
    duration_minutes: int
    initiated_by_user: bool
    quality_score: float
    notes: str
    timestamp: datetime

    model_config = {"from_attributes": True}


# ── Health Report ──

class HealthReportOut(BaseModel):
    contact_id: int
    contact_name: str
    health: float
    days_since_contact: float
    grace_remaining: float
    decay_rate: float
    reciprocity_ratio: float
    trend: str
    urgency: float
    suggested_action: str
    decay_paused: bool

    model_config = {"from_attributes": True}


# ── Weights (read-only, for transparency) ──

class WeightsOut(BaseModel):
    lambda_decay: float
    grace_period: float
    gamma: float
    w_reciprocity: float
    w_depth: float
    interaction_boost: float
    update_count: int

    model_config = {"from_attributes": True}


# ── Life Event ──

class LifeEventCreate(BaseModel):
    contact_id: int
    event_type: LifeEventType
    description: str = ""
    event_date: datetime
    pause_decay: bool = False


class LifeEventOut(BaseModel):
    id: int
    contact_id: int
    event_type: LifeEventType
    description: str
    event_date: datetime
    pause_decay: bool

    model_config = {"from_attributes": True}


# ── Nudge ──

class NudgeOut(BaseModel):
    id: int
    contact_id: int
    contact_name: str = ""
    message: str
    suggestion: str
    priority: float
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Dashboard aggregate ──

class DashboardOut(BaseModel):
    total_contacts: int
    inner_circle_count: int
    avg_health: float
    interactions_this_week: int
    health_reports: list[HealthReportOut]
    top_nudges: list[NudgeOut]
