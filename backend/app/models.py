"""
Database models for Orbit.

Core tables:
  users          - app users
  contacts       - people in a user's orbit
  interactions   - logged touchpoints (calls, texts, meetups, etc.)
  weights        - learned decay parameters per contact (the ML state)
  nudges         - generated reminders with status tracking
  life_events    - birthdays, job changes, milestones that affect decay
"""

import enum
from datetime import datetime, date

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Date, ForeignKey, Enum, Text, Boolean
)
from sqlalchemy.orm import relationship

from .database import Base


# ── Enums ──

class RelationshipType(str, enum.Enum):
    family = "family"
    friend = "friend"
    work = "work"
    acquaintance = "acquaintance"
    mentor = "mentor"


class ContactFrequency(str, enum.Enum):
    daily = "daily"
    weekly = "weekly"
    biweekly = "biweekly"
    monthly = "monthly"
    quarterly = "quarterly"


class Recurrence(str, enum.Enum):
    weekly = "weekly"
    biweekly = "biweekly"
    monthly = "monthly"


class InteractionType(str, enum.Enum):
    call = "call"
    video_call = "video_call"
    text = "text"
    in_person = "in_person"
    social_media = "social_media"
    email = "email"


class NudgeStatus(str, enum.Enum):
    pending = "pending"
    acted = "acted"
    snoozed = "snoozed"
    dismissed = "dismissed"


class LifeEventType(str, enum.Enum):
    birthday = "birthday"
    job_change = "job_change"
    move = "move"
    baby = "baby"
    wedding = "wedding"
    graduation = "graduation"
    loss = "loss"
    health = "health"
    travel = "travel"
    custom = "custom"


class QuestStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    expired = "expired"
    skipped = "skipped"


class QuestType(str, enum.Enum):
    coffee = "coffee"
    call = "call"
    outdoor = "outdoor"
    dinner = "dinner"
    reconnect = "reconnect"
    social = "social"
    explore = "explore"
    streak = "streak"
    expand = "expand"


class DifficultyTier(str, enum.Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class ActivityType(str, enum.Enum):
    run = "run"
    gym = "gym"
    hike = "hike"
    concert = "concert"
    dinner = "dinner"
    drinks = "drinks"
    gaming = "gaming"
    movie = "movie"
    sports = "sports"
    study = "study"
    custom = "custom"


class PartyStatus(str, enum.Enum):
    waiting = "waiting"       # lobby open, waiting for members
    active = "active"         # activity in progress
    completed = "completed"   # done, XP awarded
    cancelled = "cancelled"


class ChallengeStatus(str, enum.Enum):
    pending = "pending"       # sent, awaiting response
    accepted = "accepted"     # accepted, in progress
    completed = "completed"   # challenger marked done
    declined = "declined"
    expired = "expired"


class HunterRank(str, enum.Enum):
    e_rank = "E-Rank"
    d_rank = "D-Rank"
    c_rank = "C-Rank"
    b_rank = "B-Rank"
    a_rank = "A-Rank"
    s_rank = "S-Rank"
    ss_rank = "SS-Rank"
    monarch = "Monarch"


# ── Interaction depth scores ──
# Used by the decay algorithm to weight interaction quality.
# Higher = more meaningful contact.
INTERACTION_DEPTH = {
    InteractionType.in_person: 1.0,
    InteractionType.video_call: 0.85,
    InteractionType.call: 0.75,
    InteractionType.email: 0.5,
    InteractionType.text: 0.4,
    InteractionType.social_media: 0.2,
}

# ── Target frequency in days ──
FREQUENCY_DAYS = {
    ContactFrequency.daily: 1,
    ContactFrequency.weekly: 7,
    ContactFrequency.biweekly: 14,
    ContactFrequency.monthly: 30,
    ContactFrequency.quarterly: 90,
}


# ── Models ──

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False, default="")
    name = Column(String(255), nullable=False)
    timezone = Column(String(50), default="UTC")
    plan = Column(String(20), default="free")
    email_verified = Column(Boolean, default=False)
    auth_provider = Column(String(20), default="email")  # "email", "apple", "google"
    auth_provider_id = Column(String(255), nullable=True, unique=True)  # provider's user ID
    created_at = Column(DateTime, default=datetime.utcnow)

    city = Column(String(100), default="")
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Gamification
    xp = Column(Integer, default=0)
    level = Column(Integer, default=1)
    streak_days = Column(Integer, default=0)
    last_active_date = Column(Date, nullable=True)

    # Solo Leveling
    hunter_rank = Column(Enum(HunterRank), default=HunterRank.e_rank)
    stat_points = Column(Integer, default=0)
    stat_charisma = Column(Integer, default=1)
    stat_empathy = Column(Integer, default=1)
    stat_consistency = Column(Integer, default=1)
    stat_initiative = Column(Integer, default=1)
    stat_wisdom = Column(Integer, default=1)
    shadow_army_count = Column(Integer, default=0)
    daily_quest_streak = Column(Integer, default=0)
    hp = Column(Integer, default=100)
    title = Column(String(100), default="Rookie Hunter")
    streak_freezes = Column(Integer, default=0)

    # Skill tree
    social_class = Column(String(20), default="")  # "", "connector", "nurturer", "catalyst", "sage"
    skill_points = Column(Integer, default=0)  # SP earned per level, spent on skills

    contacts = relationship("Contact", back_populates="user", cascade="all, delete-orphan")
    nudges = relationship("Nudge", back_populates="user", cascade="all, delete-orphan")
    quests = relationship("Quest", back_populates="user", cascade="all, delete-orphan")
    achievements = relationship("UserAchievement", back_populates="user", cascade="all, delete-orphan")
    parties = relationship("Party", back_populates="creator", cascade="all, delete-orphan")
    challenges_sent = relationship("Challenge", back_populates="challenger", foreign_keys="Challenge.challenger_id", cascade="all, delete-orphan")


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    relationship_type = Column(Enum(RelationshipType), nullable=False)
    target_frequency = Column(Enum(ContactFrequency), default=ContactFrequency.biweekly)
    notes = Column(Text, default="")
    city = Column(String(100), default="")
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Gamification
    relationship_xp = Column(Integer, default=0)
    relationship_level = Column(String(20), default="new")

    # Solo Leveling - Shadow Army
    shadow_grade = Column(String(20), default="")  # empty = not a shadow, then: normal, elite, knight, general, marshal
    shadow_extracted_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="contacts")
    interactions = relationship("Interaction", back_populates="contact", cascade="all, delete-orphan")
    weights = relationship("Weights", back_populates="contact", uselist=False, cascade="all, delete-orphan")
    life_events = relationship("LifeEvent", back_populates="contact", cascade="all, delete-orphan")
    nudges = relationship("Nudge", back_populates="contact", cascade="all, delete-orphan")
    quests = relationship("Quest", back_populates="contact", cascade="all, delete-orphan")


class Interaction(Base):
    __tablename__ = "interactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False, index=True)
    interaction_type = Column(Enum(InteractionType), nullable=False)
    duration_minutes = Column(Integer, default=0)
    initiated_by_user = Column(Boolean, default=True)
    notes = Column(Text, default="")
    quality_score = Column(Float, default=0.5)  # 0-1, computed after logging
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    contact = relationship("Contact", back_populates="interactions")


class Weights(Base):
    """
    Learned decay parameters per contact.
    These are the ML state — updated after every interaction via online learning.

    lambda_decay: controls how fast health drops (higher = faster decay)
    grace_period: days of silence before decay kicks in
    gamma: curve shape (>1 = slow start then fast drop, <1 = fast start then plateau)
    w_reciprocity: how much two-way communication matters (0-1)
    w_depth: how much interaction quality matters (0-1)
    interaction_boost: health bump per interaction (learned from history)
    """
    __tablename__ = "weights"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False, unique=True, index=True)

    # Decay curve parameters
    lambda_decay = Column(Float, default=0.05)
    grace_period = Column(Float, default=3.0)    # days
    gamma = Column(Float, default=1.2)

    # Behavioral weights
    w_reciprocity = Column(Float, default=0.5)
    w_depth = Column(Float, default=0.5)
    interaction_boost = Column(Float, default=15.0)  # health points gained per interaction

    # Tracking
    update_count = Column(Integer, default=0)      # how many learning updates applied
    updated_at = Column(DateTime, default=datetime.utcnow)

    contact = relationship("Contact", back_populates="weights")


class Nudge(Base):
    __tablename__ = "nudges"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False, index=True)
    message = Column(Text, nullable=False)
    suggestion = Column(String(255), default="")
    priority = Column(Float, default=0.5)   # 0-1, computed by nudge engine
    status = Column(Enum(NudgeStatus), default=NudgeStatus.pending)
    created_at = Column(DateTime, default=datetime.utcnow)
    acted_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="nudges")
    contact = relationship("Contact", back_populates="nudges")


class LifeEvent(Base):
    __tablename__ = "life_events"

    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False, index=True)
    event_type = Column(Enum(LifeEventType), nullable=False)
    description = Column(Text, default="")
    event_date = Column(DateTime, nullable=False)
    pause_decay = Column(Boolean, default=False)  # if True, decay freezes during this event
    created_at = Column(DateTime, default=datetime.utcnow)

    contact = relationship("Contact", back_populates="life_events")


class Quest(Base):
    __tablename__ = "quests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    quest_type = Column(Enum(QuestType), nullable=False)
    difficulty = Column(Enum(DifficultyTier), default=DifficultyTier.easy)
    xp_reward = Column(Integer, default=20)
    status = Column(Enum(QuestStatus), default=QuestStatus.active)
    expires_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="quests")
    contact = relationship("Contact", back_populates="quests")


class UserAchievement(Base):
    __tablename__ = "user_achievements"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    achievement_key = Column(String(50), nullable=False)
    earned_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="achievements")


class Party(Base):
    """
    MapleStory-style party for group activities.
    Creator forms a party, invites contacts, activity happens, everyone gets XP.
    """
    __tablename__ = "parties"

    id = Column(Integer, primary_key=True, index=True)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    activity_type = Column(Enum(ActivityType), nullable=False)
    description = Column(Text, default="")
    location = Column(String(255), default="")
    scheduled_at = Column(DateTime, nullable=True)
    max_members = Column(Integer, default=10)
    xp_reward = Column(Integer, default=50)
    status = Column(Enum(PartyStatus), default=PartyStatus.waiting)
    is_recurring = Column(Boolean, default=False)
    recurrence = Column(Enum(Recurrence), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    creator = relationship("User", back_populates="parties")
    members = relationship("PartyMember", back_populates="party", cascade="all, delete-orphan")


class PartyMember(Base):
    """Contacts invited to a party. Tracks RSVP status."""
    __tablename__ = "party_members"

    id = Column(Integer, primary_key=True, index=True)
    party_id = Column(Integer, ForeignKey("parties.id"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    status = Column(String(20), default="invited")  # invited, joined, declined
    joined_at = Column(DateTime, nullable=True)

    party = relationship("Party", back_populates="members")
    contact = relationship("Contact")


class Challenge(Base):
    """
    Challenge a friend to do something together.
    "I challenge you to a 5K run this week!"
    """
    __tablename__ = "challenges"

    id = Column(Integer, primary_key=True, index=True)
    challenger_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    activity_type = Column(Enum(ActivityType), nullable=False)
    xp_reward = Column(Integer, default=40)
    status = Column(Enum(ChallengeStatus), default=ChallengeStatus.pending)
    expires_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    challenger = relationship("User", back_populates="challenges_sent", foreign_keys=[challenger_id])
    challenged_contact = relationship("Contact", foreign_keys=[contact_id])


class PushToken(Base):
    """Device push notification tokens (FCM) per user."""
    __tablename__ = "push_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token = Column(String(500), nullable=False, unique=True)
    platform = Column(String(20), nullable=False)  # "ios", "android", "web"
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class StravaConnection(Base):
    """OAuth connection to Strava for auto-verifying activities."""
    __tablename__ = "strava_connections"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    strava_athlete_id = Column(Integer, nullable=False)
    access_token = Column(String(255), nullable=False)
    refresh_token = Column(String(255), nullable=False)
    expires_at = Column(Integer, nullable=False)
    connected_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")


class Gate(Base):
    """
    Solo Leveling-inspired gate/dungeon.
    Users open gates (social challenges) and must clear objectives to earn XP.
    """
    __tablename__ = "gates"

    id = Column(Integer, primary_key=True, index=True)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    gate_rank = Column(Enum(HunterRank), default=HunterRank.e_rank)
    xp_reward = Column(Integer, default=100)
    time_limit_hours = Column(Integer, default=24)
    status = Column(String(20), default="open")  # open, active, cleared, failed
    objective_type = Column(String(50), default="interactions")  # interactions, party, streak
    objective_target = Column(Integer, default=3)
    objective_current = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=True)
    cleared_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    creator = relationship("User")


class BossRaid(Base):
    """
    Boss Raid — boss fight with HP-based damage system.
    Damage dealt via real interactions, scaled by stats.
    """
    __tablename__ = "boss_raids"

    id = Column(Integer, primary_key=True, index=True)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    boss_name = Column(String(100), default="Shadow Beast")
    boss_hp = Column(Integer, default=100)
    boss_max_hp = Column(Integer, default=100)
    xp_reward = Column(Integer, default=200)
    status = Column(String(20), default="active")  # active, cleared, failed
    time_limit_days = Column(Integer, default=7)
    expires_at = Column(DateTime, nullable=True)
    cleared_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Phase 5: deeper boss mechanics
    boss_type = Column(String(30), default="shadow_beast")  # shadow_beast, drifter, hydra, monarch
    phase = Column(Integer, default=1)
    total_phases = Column(Integer, default=1)
    mechanic_data = Column(Text, default="{}")  # JSON for tracking boss-specific state (e.g. hydra heads)
    stat_points_reward = Column(Integer, default=3)

    creator = relationship("User")


# ── Quest Chains (Phase 3) ──

class QuestChainStatus(str, enum.Enum):
    active = "active"
    completed = "completed"
    failed = "failed"


class QuestChain(Base):
    """
    Multi-step quest storylines with prerequisites and chain bonuses.
    Each chain has a key (e.g. 'reconnection_saga') and tracks progress.
    """
    __tablename__ = "quest_chains"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    chain_key = Column(String(50), nullable=False)  # e.g. 'reconnection_saga'
    current_step = Column(Integer, default=1)
    total_steps = Column(Integer, nullable=False)
    status = Column(Enum(QuestChainStatus), default=QuestChainStatus.active)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    # Store chain-specific state (e.g. target contact_id for reconnection)
    chain_data = Column(Text, default="{}")

    user = relationship("User")


# ── Skill Tree (Phase 6) ──

class UserSkill(Base):
    """
    Skills unlocked by spending SP within a social class.
    Each skill has a key and a level (1-3).
    """
    __tablename__ = "user_skills"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    skill_key = Column(String(50), nullable=False)
    level = Column(Integer, default=1)
    unlocked_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")


# ── Circles / Guilds (Phase 7) ──

class Circle(Base):
    """
    Persistent contact groups. Group contacts into circles
    for circle-specific quests, XP tracking, and perks.
    """
    __tablename__ = "circles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, default="")
    icon = Column(String(20), default="users")  # icon key
    xp_pool = Column(Integer, default=0)  # cumulative XP from circle interactions
    level = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")
    members = relationship("CircleMember", back_populates="circle", cascade="all, delete-orphan")


class CircleMember(Base):
    """Contacts assigned to a circle."""
    __tablename__ = "circle_members"

    id = Column(Integer, primary_key=True, index=True)
    circle_id = Column(Integer, ForeignKey("circles.id"), nullable=False, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.id"), nullable=False)
    joined_at = Column(DateTime, default=datetime.utcnow)

    circle = relationship("Circle", back_populates="members")
    contact = relationship("Contact")


class CircleQuest(Base):
    """
    Circle-wide quest: interact with all members within a timeframe.
    """
    __tablename__ = "circle_quests"

    id = Column(Integer, primary_key=True, index=True)
    circle_id = Column(Integer, ForeignKey("circles.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, default="")
    quest_type = Column(String(30), default="interact_all")  # interact_all, group_activity, streak_all
    target = Column(Integer, default=1)  # e.g. interact with each member 1 time
    progress_data = Column(Text, default="{}")  # JSON tracking per-member progress
    xp_reward = Column(Integer, default=100)
    status = Column(String(20), default="active")  # active, completed, failed
    expires_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    circle = relationship("Circle")
    user = relationship("User")
