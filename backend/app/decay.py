"""
Orbit Decay Algorithm — Adaptive Relationship Health Engine

The health of a relationship is modeled as an exponential decay curve
with parameters that are *learned* from actual interaction patterns.

Core formula:
    health(t) = clamp(base_health * decay(t) * reciprocity_factor + pending_boost, 0, 100)

Where:
    decay(t) = exp(-lambda * max(0, days_silent - grace)^gamma)
    reciprocity_factor = 1.0 - w_reciprocity * (1 - reciprocity_ratio)
    pending_boost = sum of active life event boosts

The learning loop:
    After each interaction, we observe the gap since the last one and how the
    user actually behaves. We nudge the weights toward reality using exponential
    moving averages (EMA). No GPU, no training pipeline — just simple online
    updates that converge after ~20 interactions per contact.
"""

import math
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import (
    Contact, Interaction, Weights, LifeEvent,
    InteractionType, INTERACTION_DEPTH, FREQUENCY_DAYS,
)


# ── Learning rate for online weight updates ──
# Starts high (0.3) and decays toward 0.05 as more updates happen.
# This means early interactions have a big effect, later ones fine-tune.
def learning_rate(update_count: int) -> float:
    return max(0.05, 0.3 * math.exp(-0.05 * update_count))


@dataclass
class HealthReport:
    """Full health assessment for a single contact."""
    contact_id: int
    contact_name: str
    health: float              # 0-100
    days_since_contact: float
    grace_remaining: float     # days before decay starts
    decay_rate: float          # current decay speed
    reciprocity_ratio: float   # 0-1, how balanced the communication is
    trend: str                 # "improving", "stable", "declining"
    urgency: float             # 0-1, how urgently a nudge is needed
    suggested_action: str
    decay_paused: bool         # True if a life event is pausing decay


def compute_health(contact: Contact, db: Session, now: Optional[datetime] = None) -> HealthReport:
    """
    Compute the current relationship health for a contact.
    This is the core function — called on every dashboard load and by the nudge engine.
    """
    now = now or datetime.utcnow()
    weights = contact.weights

    # If no weights exist yet, use defaults based on relationship type
    if not weights:
        weights = _default_weights(contact)

    # ── 1. Days since last interaction ──
    last_interaction = (
        db.query(Interaction)
        .filter(Interaction.contact_id == contact.id)
        .order_by(Interaction.timestamp.desc())
        .first()
    )

    if last_interaction:
        days_silent = (now - last_interaction.timestamp).total_seconds() / 86400
    else:
        # Never interacted — use days since contact was added
        days_silent = (now - contact.created_at).total_seconds() / 86400

    # ── 2. Check for active life events that pause decay ──
    active_pause = (
        db.query(LifeEvent)
        .filter(
            LifeEvent.contact_id == contact.id,
            LifeEvent.pause_decay == True,
            LifeEvent.event_date >= now - timedelta(days=30),
        )
        .first()
    )
    decay_paused = active_pause is not None

    # ── 3. Compute decay factor ──
    if decay_paused:
        decay_factor = 1.0
    else:
        effective_silence = max(0.0, days_silent - weights.grace_period)
        decay_factor = math.exp(
            -weights.lambda_decay * (effective_silence ** weights.gamma)
        )

    # ── 4. Compute reciprocity ──
    total_count = (
        db.query(func.count(Interaction.id))
        .filter(Interaction.contact_id == contact.id)
        .scalar() or 0
    )
    user_initiated = (
        db.query(func.count(Interaction.id))
        .filter(
            Interaction.contact_id == contact.id,
            Interaction.initiated_by_user == True,
        )
        .scalar() or 0
    )

    if total_count > 0:
        reciprocity_ratio = 1.0 - abs(0.5 - user_initiated / total_count) * 2
    else:
        reciprocity_ratio = 0.5  # neutral when no data

    reciprocity_factor = 1.0 - weights.w_reciprocity * (1.0 - reciprocity_ratio)

    # ── 5. Last interaction quality boost ──
    if last_interaction:
        depth = INTERACTION_DEPTH.get(last_interaction.interaction_type, 0.3)
        quality_boost = 1.0 + weights.w_depth * depth * 0.2  # up to 20% boost
    else:
        quality_boost = 1.0

    # ── 6. Final health ──
    base = 100.0
    health = base * decay_factor * reciprocity_factor * quality_boost
    health = max(0.0, min(100.0, health))

    # ── 7. Trend analysis (compare to 7 days ago) ──
    health_7d_ago = _health_at_time(contact, weights, db, now - timedelta(days=7))
    if health > health_7d_ago + 3:
        trend = "improving"
    elif health < health_7d_ago - 3:
        trend = "declining"
    else:
        trend = "stable"

    # ── 8. Urgency score (for nudge prioritization) ──
    target_days = FREQUENCY_DAYS.get(contact.target_frequency, 14)
    overdue_ratio = days_silent / target_days
    urgency = min(1.0, max(0.0, (overdue_ratio - 0.5) / 1.5))
    # Boost urgency for declining relationships
    if trend == "declining":
        urgency = min(1.0, urgency + 0.15)

    # ── 9. Suggested action ──
    suggested_action = _suggest_action(contact, last_interaction, days_silent, target_days)

    grace_remaining = max(0.0, weights.grace_period - days_silent)

    return HealthReport(
        contact_id=contact.id,
        contact_name=contact.name,
        health=round(health, 1),
        days_since_contact=round(days_silent, 1),
        grace_remaining=round(grace_remaining, 1),
        decay_rate=weights.lambda_decay,
        reciprocity_ratio=round(reciprocity_ratio, 2),
        trend=trend,
        urgency=round(urgency, 2),
        suggested_action=suggested_action,
        decay_paused=decay_paused,
    )


def update_weights_after_interaction(
    contact: Contact,
    interaction: Interaction,
    db: Session,
) -> Weights:
    """
    Online learning update — called every time an interaction is logged.
    Adjusts the contact's decay weights based on observed behavior.

    The key insight: we compare what actually happened to what the model predicted,
    and nudge the weights to better match reality.
    """
    weights = contact.weights
    if not weights:
        weights = Weights(contact_id=contact.id)
        db.add(weights)

    lr = learning_rate(weights.update_count)

    # ── Get the previous interaction to measure the actual gap ──
    prev_interaction = (
        db.query(Interaction)
        .filter(
            Interaction.contact_id == contact.id,
            Interaction.id != interaction.id,
        )
        .order_by(Interaction.timestamp.desc())
        .first()
    )

    if prev_interaction:
        actual_gap = (interaction.timestamp - prev_interaction.timestamp).total_seconds() / 86400
    else:
        actual_gap = (interaction.timestamp - contact.created_at).total_seconds() / 86400

    target_days = FREQUENCY_DAYS.get(contact.target_frequency, 14)

    # ── Update grace period ──
    # If the user consistently contacts before the current grace period,
    # the grace period should shrink toward their actual rhythm.
    # If they contact after, it should grow (they're comfortable with longer gaps).
    weights.grace_period += lr * (actual_gap * 0.7 - weights.grace_period)
    weights.grace_period = max(0.5, min(target_days * 0.8, weights.grace_period))

    # ── Update lambda (decay rate) ──
    # If the user reaches out faster than target, decay should be gentler (lower lambda).
    # If they're slower, decay should be steeper to create stronger nudges.
    gap_ratio = actual_gap / target_days
    if gap_ratio < 1.0:
        # User is proactive — slow down the decay
        target_lambda = weights.lambda_decay * 0.9
    else:
        # User is late — speed up the decay slightly
        target_lambda = weights.lambda_decay * 1.1
    weights.lambda_decay += lr * (target_lambda - weights.lambda_decay)
    weights.lambda_decay = max(0.01, min(0.3, weights.lambda_decay))

    # ── Update gamma (curve shape) ──
    # Users who are consistently late get a steeper curve (gamma > 1.2)
    # to make the health drop more dramatic and nudges more urgent.
    # Consistent users get a gentler curve.
    if gap_ratio > 1.3:
        target_gamma = min(2.0, weights.gamma + 0.1)
    elif gap_ratio < 0.7:
        target_gamma = max(0.8, weights.gamma - 0.1)
    else:
        target_gamma = weights.gamma
    weights.gamma += lr * (target_gamma - weights.gamma)

    # ── Update reciprocity weight ──
    # If the contact also initiates, reciprocity matters more.
    total = (
        db.query(func.count(Interaction.id))
        .filter(Interaction.contact_id == contact.id)
        .scalar() or 1
    )
    them_initiated = (
        db.query(func.count(Interaction.id))
        .filter(
            Interaction.contact_id == contact.id,
            Interaction.initiated_by_user == False,
        )
        .scalar() or 0
    )
    their_ratio = them_initiated / total
    # If they initiate often, reciprocity weight should be higher
    # (meaning one-sided relationships will decay faster)
    weights.w_reciprocity += lr * (their_ratio - weights.w_reciprocity)
    weights.w_reciprocity = max(0.0, min(1.0, weights.w_reciprocity))

    # ── Update depth weight ──
    # Track whether high-depth interactions correspond to longer healthy gaps.
    depth = INTERACTION_DEPTH.get(interaction.interaction_type, 0.3)
    if actual_gap <= target_days and depth >= 0.6:
        # Deep interaction + on schedule = depth matters
        weights.w_depth += lr * (0.8 - weights.w_depth)
    elif actual_gap > target_days and depth < 0.4:
        # Shallow interaction + overdue = depth doesn't save you
        weights.w_depth += lr * (0.3 - weights.w_depth)
    weights.w_depth = max(0.1, min(1.0, weights.w_depth))

    # ── Update interaction boost ──
    # How much health should an interaction recover? Learn from what keeps
    # health above 70 for this specific relationship.
    if actual_gap <= target_days:
        # Healthy cadence — keep the boost moderate
        weights.interaction_boost += lr * (12.0 - weights.interaction_boost)
    else:
        # Overdue — need bigger boosts to recover
        weights.interaction_boost += lr * (20.0 - weights.interaction_boost)
    weights.interaction_boost = max(5.0, min(30.0, weights.interaction_boost))

    weights.update_count += 1
    weights.updated_at = datetime.utcnow()

    db.commit()
    return weights


# ── Private helpers ──

def _health_at_time(contact: Contact, weights: Weights, db: Session, at: datetime) -> float:
    """Compute what health was at a past timestamp (for trend analysis)."""
    last_before = (
        db.query(Interaction)
        .filter(
            Interaction.contact_id == contact.id,
            Interaction.timestamp <= at,
        )
        .order_by(Interaction.timestamp.desc())
        .first()
    )

    if last_before:
        days = (at - last_before.timestamp).total_seconds() / 86400
    else:
        days = (at - contact.created_at).total_seconds() / 86400

    effective = max(0.0, days - weights.grace_period)
    decay = math.exp(-weights.lambda_decay * (effective ** weights.gamma))
    return max(0.0, min(100.0, 100.0 * decay))


def _default_weights(contact: Contact) -> Weights:
    """Sensible defaults before any learning has happened."""
    target = FREQUENCY_DAYS.get(contact.target_frequency, 14)

    # Family gets slower decay, acquaintances get faster
    type_multipliers = {
        "family": 0.7,
        "friend": 1.0,
        "work": 1.1,
        "mentor": 0.9,
        "acquaintance": 1.3,
    }
    mult = type_multipliers.get(contact.relationship_type.value, 1.0)

    return Weights(
        contact_id=contact.id,
        lambda_decay=0.05 * mult,
        grace_period=target * 0.4,
        gamma=1.2,
        w_reciprocity=0.3,
        w_depth=0.5,
        interaction_boost=15.0,
        update_count=0,
    )


def _suggest_action(
    contact: Contact,
    last_interaction: Optional[Interaction],
    days_silent: float,
    target_days: int,
) -> str:
    """Generate a contextual action suggestion."""
    if last_interaction is None:
        return f"Reach out to {contact.name} for the first time!"

    overdue = days_silent / target_days

    # Vary the suggestion based on last interaction type to encourage variety
    last_type = last_interaction.interaction_type
    if last_type in (InteractionType.text, InteractionType.social_media):
        upgrade = "Try calling or meeting in person for a deeper connection."
    elif last_type in (InteractionType.call, InteractionType.video_call):
        upgrade = "Maybe plan an in-person catch-up?"
    else:
        upgrade = "A quick text to stay on their radar works great."

    if overdue > 2.0:
        return f"It's been a while! Send a simple 'thinking of you' message. {upgrade}"
    elif overdue > 1.0:
        return f"You're a bit overdue. {upgrade}"
    else:
        return f"Relationship is healthy. {upgrade}"
