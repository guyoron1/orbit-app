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
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, ForeignKey, Enum, Text, Boolean
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
    created_at = Column(DateTime, default=datetime.utcnow)

    contacts = relationship("Contact", back_populates="user", cascade="all, delete-orphan")
    nudges = relationship("Nudge", back_populates="user", cascade="all, delete-orphan")


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    relationship_type = Column(Enum(RelationshipType), nullable=False)
    target_frequency = Column(Enum(ContactFrequency), default=ContactFrequency.biweekly)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="contacts")
    interactions = relationship("Interaction", back_populates="contact", cascade="all, delete-orphan")
    weights = relationship("Weights", back_populates="contact", uselist=False, cascade="all, delete-orphan")
    life_events = relationship("LifeEvent", back_populates="contact", cascade="all, delete-orphan")
    nudges = relationship("Nudge", back_populates="contact", cascade="all, delete-orphan")


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
