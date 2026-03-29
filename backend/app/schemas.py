from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from .models import (
    RelationshipType, ContactFrequency, InteractionType, LifeEventType,
    QuestType, QuestStatus, DifficultyTier,
    ActivityType, PartyStatus, ChallengeStatus, Recurrence,
)


# ── Auth ──

class SignupRequest(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=100)
    timezone: str = "UTC"


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


# ── User ──

class UserCreate(BaseModel):
    email: str = Field(..., max_length=255)
    name: str = Field(..., max_length=100)
    timezone: str = "UTC"


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    timezone: str
    plan: str
    created_at: datetime
    xp: int = 0
    level: int = 1
    streak_days: int = 0

    model_config = {"from_attributes": True}


# ── Contact ──

class ContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    relationship_type: RelationshipType
    target_frequency: ContactFrequency = ContactFrequency.biweekly
    notes: str = Field("", max_length=2000)
    city: str = Field("", max_length=100)


class ContactUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    relationship_type: Optional[RelationshipType] = None
    target_frequency: Optional[ContactFrequency] = None
    notes: Optional[str] = Field(None, max_length=2000)
    city: Optional[str] = Field(None, max_length=100)


class ContactOut(BaseModel):
    id: int
    user_id: int
    name: str
    relationship_type: RelationshipType
    target_frequency: ContactFrequency
    notes: str
    city: str = ""
    created_at: datetime
    relationship_xp: int = 0
    relationship_level: str = "new"

    model_config = {"from_attributes": True}


# ── Interaction ──

class InteractionCreate(BaseModel):
    contact_id: int
    interaction_type: InteractionType
    duration_minutes: int = Field(0, ge=0, le=1440)
    initiated_by_user: bool = True
    notes: str = Field("", max_length=2000)


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
    description: str = Field("", max_length=1000)
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


# ── AI ──

class ConversationStartersOut(BaseModel):
    contact_id: int
    contact_name: str
    starters: list[str]


class AISummaryOut(BaseModel):
    summary: str


# ── Quests ──

class QuestOut(BaseModel):
    id: int
    user_id: int
    contact_id: Optional[int] = None
    title: str
    description: str
    quest_type: QuestType
    difficulty: DifficultyTier
    xp_reward: int
    status: QuestStatus
    expires_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Achievements ──

class AchievementDef(BaseModel):
    key: str
    name: str
    description: str
    icon: str
    xp_bonus: int
    earned: bool = False
    earned_at: Optional[datetime] = None


class XPAwardOut(BaseModel):
    xp_earned: int
    base_xp: int
    duration_bonus: int
    new_level: int
    new_achievements: list[dict]


class LevelProgressOut(BaseModel):
    level: int
    current_xp: int
    level_xp: int
    level_xp_needed: int
    progress: float


# ── Gamification Dashboard ──

class GamificationDashboardOut(BaseModel):
    level_progress: LevelProgressOut
    streak_days: int
    active_quests: list[QuestOut]
    recent_achievements: list[AchievementDef]
    all_achievements: list[AchievementDef]
    active_parties: list["PartyOut"] = []
    active_challenges: list["ChallengeOut"] = []


# ── Party / Hangout ──

class PartyMemberOut(BaseModel):
    id: int
    contact_id: int
    contact_name: str = ""
    status: str
    joined_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PartyCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    activity_type: ActivityType
    description: str = Field("", max_length=1000)
    location: str = Field("", max_length=200)
    scheduled_at: Optional[datetime] = None
    contact_ids: list[int] = []
    is_recurring: bool = False
    recurrence: Optional[Recurrence] = None


class PartyOut(BaseModel):
    id: int
    creator_id: int
    title: str
    activity_type: ActivityType
    description: str
    location: str
    scheduled_at: Optional[datetime] = None
    max_members: int
    xp_reward: int
    status: PartyStatus
    is_recurring: bool = False
    recurrence: Optional[Recurrence] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    members: list[PartyMemberOut] = []

    model_config = {"from_attributes": True}


# ── Challenge ──

class ChallengeCreate(BaseModel):
    contact_id: int
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=1000)
    activity_type: ActivityType


class ChallengeOut(BaseModel):
    id: int
    challenger_id: int
    contact_id: int
    contact_name: str = ""
    title: str
    description: str
    activity_type: ActivityType
    xp_reward: int
    status: ChallengeStatus
    expires_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Social Feed ──

class FeedItemOut(BaseModel):
    event_type: str  # interaction, party_completed, challenge_completed, achievement, level_up
    title: str
    description: str
    icon: str
    xp: int = 0
    contact_name: str = ""
    timestamp: datetime


# ── Leaderboard ──

class LeaderboardEntryOut(BaseModel):
    contact_id: int
    contact_name: str
    relationship_type: str
    value: float
    rank: int


class LeaderboardOut(BaseModel):
    most_interactions: list[LeaderboardEntryOut]
    highest_relationship_xp: list[LeaderboardEntryOut]
    longest_streak: list[LeaderboardEntryOut]


# ── Location ──

class NearbyContactOut(BaseModel):
    contact_id: int
    contact_name: str
    city: str
    relationship_type: str
    days_since_contact: float
    suggestion: str


class LocationUpdate(BaseModel):
    city: str = Field("", max_length=100)
    latitude: Optional[float] = None
    longitude: Optional[float] = None


# ── Strava ──

class StravaStatusOut(BaseModel):
    connected: bool
    athlete_id: Optional[int] = None
    connected_at: Optional[datetime] = None


# ── Dashboard aggregate ──

class DashboardOut(BaseModel):
    total_contacts: int
    inner_circle_count: int
    avg_health: float
    interactions_this_week: int
    health_reports: list[HealthReportOut]
    top_nudges: list[NudgeOut]
    ai_summary: str = ""
    gamification: Optional[GamificationDashboardOut] = None
