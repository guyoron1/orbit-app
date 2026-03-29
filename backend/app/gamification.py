"""
Orbit Gamification Engine — Quests, XP, Achievements, Streaks

Design principles:
  - Reward organic behavior, don't force it
  - Encourage real-world meetups over digital interactions
  - Make progression visible but not pushy
  - Quests are suggestions, not mandatory checklists
"""

import random
from datetime import datetime, timedelta, date
from typing import Optional, List

from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import (
    User, Contact, Interaction, Quest, UserAchievement,
    InteractionType, QuestStatus, QuestType, DifficultyTier,
)


# ── XP Rewards ──
XP_INTERACTION = {
    InteractionType.in_person: 40,
    InteractionType.video_call: 25,
    InteractionType.call: 20,
    InteractionType.email: 10,
    InteractionType.text: 8,
    InteractionType.social_media: 5,
}

XP_DURATION_BONUS = 0.5  # per minute, capped at 30 bonus
XP_QUEST_MULTIPLIER = 1.5  # quest completion bonus on top of base XP

# ── Level Thresholds ──
# Level N requires sum(100 * 1.4^(i-1)) for i in 1..N
def xp_for_level(level: int) -> int:
    if level <= 1:
        return 0
    total = 0
    for i in range(1, level):
        total += int(100 * (1.3 ** (i - 1)))
    return total


def level_from_xp(xp: int) -> int:
    level = 1
    while xp_for_level(level + 1) <= xp:
        level += 1
    return level


def level_progress(xp: int) -> dict:
    """Returns current level, XP within level, XP needed for next level."""
    lvl = level_from_xp(xp)
    current_threshold = xp_for_level(lvl)
    next_threshold = xp_for_level(lvl + 1)
    return {
        "level": lvl,
        "current_xp": xp,
        "level_xp": xp - current_threshold,
        "level_xp_needed": next_threshold - current_threshold,
        "progress": (xp - current_threshold) / max(1, next_threshold - current_threshold),
    }


# ── Relationship Levels ──
RELATIONSHIP_LEVELS = [
    (0, "new"),
    (50, "acquaintance"),
    (200, "friend"),
    (500, "close"),
    (1000, "inner_circle"),
]


def relationship_level_from_xp(xp: int) -> str:
    level = "new"
    for threshold, name in RELATIONSHIP_LEVELS:
        if xp >= threshold:
            level = name
    return level


# ── XP Award ──
def award_interaction_xp(user: User, contact: Contact, interaction: Interaction, db: Session) -> dict:
    """Award XP for logging an interaction. Returns XP breakdown."""
    base = XP_INTERACTION.get(interaction.interaction_type, 10)
    duration_bonus = min(30, int(interaction.duration_minutes * XP_DURATION_BONUS))
    total = base + duration_bonus

    # Update user XP
    user.xp = (user.xp or 0) + total
    user.level = level_from_xp(user.xp)

    # Update contact relationship XP
    contact.relationship_xp = (contact.relationship_xp or 0) + total
    contact.relationship_level = relationship_level_from_xp(contact.relationship_xp)

    # Update streak
    today = date.today()
    if user.last_active_date != today:
        if user.last_active_date == today - timedelta(days=1):
            user.streak_days = (user.streak_days or 0) + 1
        else:
            user.streak_days = 1
        user.last_active_date = today

    db.commit()

    # Check achievements
    new_achievements = check_achievements(user, contact, db)

    return {
        "xp_earned": total,
        "base_xp": base,
        "duration_bonus": duration_bonus,
        "new_level": user.level,
        "new_achievements": new_achievements,
    }


# ── Quest Generation ──
QUEST_TEMPLATES = [
    # (type, difficulty, xp, title_template, description_template, requires_contact)
    (QuestType.coffee, DifficultyTier.easy, 30,
     "Coffee catch-up with {name}",
     "Meet {name} for coffee or a drink. In-person connections are the strongest.",
     True),
    (QuestType.call, DifficultyTier.easy, 20,
     "Call {name}",
     "Give {name} a ring. A 10-minute call can make someone's day.",
     True),
    (QuestType.outdoor, DifficultyTier.medium, 50,
     "Outdoor adventure with {name}",
     "Go for a run, hike, or walk with {name}. Fresh air + friendship = magic.",
     True),
    (QuestType.dinner, DifficultyTier.medium, 45,
     "Dinner with {name}",
     "Cook together or grab a meal with {name}. Break bread, build bonds.",
     True),
    (QuestType.reconnect, DifficultyTier.medium, 40,
     "Reconnect with {name}",
     "It's been a while since you talked to {name}. Reach out and catch up!",
     True),
    (QuestType.social, DifficultyTier.easy, 15,
     "Send {name} something funny",
     "Share a meme, article, or inside joke with {name}. Small touches matter.",
     True),
    (QuestType.explore, DifficultyTier.hard, 60,
     "Plan something new with {name}",
     "Try something neither of you have done before — concert, class, escape room.",
     True),
    (QuestType.streak, DifficultyTier.medium, 35,
     "7-day social streak",
     "Interact with at least one person every day for 7 days straight.",
     False),
    (QuestType.expand, DifficultyTier.easy, 25,
     "Add someone new to your orbit",
     "Think of someone you'd like to stay closer to and add them.",
     False),
]


def generate_quests(user: User, db: Session) -> List[Quest]:
    """Generate personalized quests based on user's relationship state."""
    contacts = db.query(Contact).filter(Contact.user_id == user.id).all()
    if not contacts:
        return []

    # Don't generate if user already has 3+ active quests
    active_count = db.query(func.count(Quest.id)).filter(
        Quest.user_id == user.id,
        Quest.status == QuestStatus.active,
    ).scalar() or 0
    if active_count >= 3:
        return []

    now = datetime.utcnow()
    new_quests = []
    slots = 3 - active_count

    # Prioritize contacts who need attention
    contact_scores = []
    for c in contacts:
        last = (
            db.query(Interaction)
            .filter(Interaction.contact_id == c.id)
            .order_by(Interaction.timestamp.desc())
            .first()
        )
        days_silent = (now - last.timestamp).total_seconds() / 86400 if last else 999
        contact_scores.append((c, days_silent))

    contact_scores.sort(key=lambda x: x[1], reverse=True)

    # Pick templates
    available_templates = list(QUEST_TEMPLATES)
    random.shuffle(available_templates)

    for template in available_templates:
        if slots <= 0:
            break

        qtype, diff, xp, title_tmpl, desc_tmpl, needs_contact = template

        if needs_contact and not contact_scores:
            continue

        # Check for duplicate active quests of same type
        existing = db.query(Quest).filter(
            Quest.user_id == user.id,
            Quest.quest_type == qtype,
            Quest.status == QuestStatus.active,
        ).first()
        if existing:
            continue

        if needs_contact:
            contact, days_silent = contact_scores[0]
            # For reconnect quests, pick contacts with most silence
            if qtype == QuestType.reconnect and days_silent < 7:
                continue
            title = title_tmpl.format(name=contact.name)
            desc = desc_tmpl.format(name=contact.name)
            contact_id = contact.id
            # Rotate to next contact for variety
            contact_scores.append(contact_scores.pop(0))
        else:
            title = title_tmpl
            desc = desc_tmpl
            contact_id = None

        # Set expiry based on difficulty
        expire_days = {DifficultyTier.easy: 3, DifficultyTier.medium: 7, DifficultyTier.hard: 14}
        expires_at = now + timedelta(days=expire_days.get(diff, 7))

        quest = Quest(
            user_id=user.id,
            contact_id=contact_id,
            title=title,
            description=desc,
            quest_type=qtype,
            difficulty=diff,
            xp_reward=xp,
            expires_at=expires_at,
        )
        db.add(quest)
        new_quests.append(quest)
        slots -= 1

    if new_quests:
        db.commit()
        for q in new_quests:
            db.refresh(q)

    return new_quests


def complete_quest(quest: Quest, user: User, db: Session) -> dict:
    """Mark a quest as completed and award XP."""
    quest.status = QuestStatus.completed
    quest.completed_at = datetime.utcnow()

    xp = quest.xp_reward
    user.xp = (user.xp or 0) + xp
    user.level = level_from_xp(user.xp)

    db.commit()

    new_achievements = check_achievements(user, None, db)

    return {
        "xp_earned": xp,
        "new_level": user.level,
        "new_achievements": new_achievements,
    }


# ── Achievements ──
ACHIEVEMENT_DEFS = [
    ("first_contact", "First Contact", "Add your first person to Orbit", "rocket", 20),
    ("social_5", "Social Butterfly", "Have 5 people in your orbit", "butterfly", 30),
    ("social_10", "Connector", "Have 10 people in your orbit", "link", 50),
    ("first_interaction", "Ice Breaker", "Log your first interaction", "wave", 15),
    ("interactions_10", "Conversationalist", "Log 10 interactions", "chat", 40),
    ("interactions_50", "Social Pro", "Log 50 interactions", "trophy", 100),
    ("streak_3", "Getting Started", "Maintain a 3-day streak", "flame", 25),
    ("streak_7", "Streak Master", "Maintain a 7-day streak", "fire", 50),
    ("streak_30", "Unstoppable", "Maintain a 30-day streak", "comet", 150),
    ("quest_1", "Quester", "Complete your first quest", "compass", 20),
    ("quest_5", "Adventurer", "Complete 5 quests", "map", 50),
    ("quest_10", "Quest Legend", "Complete 10 quests", "crown", 100),
    ("level_5", "Rising Star", "Reach level 5", "star", 30),
    ("level_10", "Orbit Master", "Reach level 10", "orbit", 75),
    ("in_person_5", "Real World", "Have 5 in-person meetups", "handshake", 60),
    ("inner_circle", "Inner Circle", "Get a relationship to Inner Circle level", "heart", 80),
]


def check_achievements(user: User, contact: Optional[Contact], db: Session) -> list:
    """Check and award any newly earned achievements. Returns list of new ones."""
    earned = {ua.achievement_key for ua in
              db.query(UserAchievement).filter(UserAchievement.user_id == user.id).all()}

    new_achievements = []

    # Helper to check and award
    def try_award(key: str, condition: bool):
        if key not in earned and condition:
            ua = UserAchievement(user_id=user.id, achievement_key=key)
            db.add(ua)
            # Find XP bonus
            for akey, name, desc, icon, xp in ACHIEVEMENT_DEFS:
                if akey == key:
                    user.xp = (user.xp or 0) + xp
                    new_achievements.append({"key": key, "name": name, "xp_bonus": xp})
                    break

    # Contact count achievements
    contact_count = db.query(func.count(Contact.id)).filter(Contact.user_id == user.id).scalar() or 0
    try_award("first_contact", contact_count >= 1)
    try_award("social_5", contact_count >= 5)
    try_award("social_10", contact_count >= 10)

    # Interaction count achievements
    interaction_count = db.query(func.count(Interaction.id)).filter(Interaction.user_id == user.id).scalar() or 0
    try_award("first_interaction", interaction_count >= 1)
    try_award("interactions_10", interaction_count >= 10)
    try_award("interactions_50", interaction_count >= 50)

    # Streak achievements
    streak = user.streak_days or 0
    try_award("streak_3", streak >= 3)
    try_award("streak_7", streak >= 7)
    try_award("streak_30", streak >= 30)

    # Quest achievements
    quest_count = db.query(func.count(Quest.id)).filter(
        Quest.user_id == user.id, Quest.status == QuestStatus.completed
    ).scalar() or 0
    try_award("quest_1", quest_count >= 1)
    try_award("quest_5", quest_count >= 5)
    try_award("quest_10", quest_count >= 10)

    # Level achievements
    try_award("level_5", (user.level or 1) >= 5)
    try_award("level_10", (user.level or 1) >= 10)

    # In-person meetups
    in_person_count = db.query(func.count(Interaction.id)).filter(
        Interaction.user_id == user.id,
        Interaction.interaction_type == InteractionType.in_person,
    ).scalar() or 0
    try_award("in_person_5", in_person_count >= 5)

    # Inner circle relationship
    if contact and (contact.relationship_xp or 0) >= 1000:
        try_award("inner_circle", True)

    if new_achievements:
        user.level = level_from_xp(user.xp)
        db.commit()

    return new_achievements
