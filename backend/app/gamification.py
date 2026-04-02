"""
Orbit Gamification Engine — Quests, XP, Achievements, Streaks, Skills, Chains, Circles

Design principles:
  - Reward organic behavior, don't force it
  - Encourage real-world meetups over digital interactions
  - Make progression visible but not pushy
  - Quests are suggestions, not mandatory checklists
  - Stats have real mechanical effects
  - Every system feeds into every other system
"""

import json
import random
from datetime import datetime, timedelta, date
from typing import Optional, List

from sqlalchemy.orm import Session
from sqlalchemy import func

from .models import (
    User, Contact, Interaction, Quest, UserAchievement, UserSkill,
    QuestChain, QuestChainStatus, Circle, CircleMember, CircleQuest,
    Party, PartyMember, Challenge, Gate, BossRaid,
    InteractionType, QuestStatus, QuestType, DifficultyTier,
    PartyStatus, ChallengeStatus,
)


# ══════════════════════════════════════════════
# PHASE 1: STAT EFFECTS
# ══════════════════════════════════════════════

def get_stat_bonuses(user: User, db: Session) -> dict:
    """Calculate all mechanical bonuses from stats and skills."""
    charisma = user.stat_charisma or 1
    empathy = user.stat_empathy or 1
    consistency = user.stat_consistency or 1
    initiative = user.stat_initiative or 1
    wisdom = user.stat_wisdom or 1

    bonuses = {
        "party_xp_mult": 1.0 + (charisma - 1) * 0.02,      # +2% per point above 1
        "relationship_xp_mult": 1.0 + (empathy - 1) * 0.02, # +2% per point above 1
        "free_streak_freezes": (consistency - 1) // 10,       # +1 free freeze per 10 pts
        "quest_xp_mult": 1.0 + (initiative - 1) * 0.05,     # +5% per point above 1
        "global_xp_mult": 1.0 + (wisdom - 1) * 0.01,        # +1% per point above 1
    }

    # Apply skill bonuses
    skills = {s.skill_key: s.level for s in
              db.query(UserSkill).filter(UserSkill.user_id == user.id).all()}

    # Connector skills
    if "wide_net" in skills:
        bonuses["max_active_quests"] = 3 + skills["wide_net"]  # +1 per level
    else:
        bonuses["max_active_quests"] = 3

    if "social_butterfly" in skills:
        bonuses["new_contact_xp_mult"] = 1.0 + skills["social_butterfly"] * 0.5  # +50% per level

    # Nurturer skills
    if "deep_roots" in skills:
        bonuses["relationship_xp_mult"] += skills["deep_roots"] * 0.15  # +15% per level
    if "healing_touch" in skills:
        bonuses["hp_per_interaction"] = skills["healing_touch"] * 5  # +5 HP per level
    else:
        bonuses["hp_per_interaction"] = 0

    # Catalyst skills
    if "party_leader" in skills:
        bonuses["party_size_bonus"] = skills["party_leader"] * 2  # +2 max per level
    else:
        bonuses["party_size_bonus"] = 0
    if "rally_cry" in skills:
        bonuses["party_xp_mult"] += skills["rally_cry"] * 0.25  # +25% per level

    # Sage skills
    if "iron_will" in skills:
        bonuses["free_streak_freezes"] += skills["iron_will"] * 2  # +2 per level
    if "meditation" in skills:
        bonuses["daily_checkin_xp_mult"] = 1.0 + skills["meditation"] * 0.25
    else:
        bonuses["daily_checkin_xp_mult"] = 1.0

    return bonuses


# ══════════════════════════════════════════════
# XP & LEVELING
# ══════════════════════════════════════════════

XP_INTERACTION = {
    InteractionType.in_person: 40,
    InteractionType.video_call: 25,
    InteractionType.call: 20,
    InteractionType.email: 10,
    InteractionType.text: 8,
    InteractionType.social_media: 5,
}

XP_DURATION_BONUS = 0.5  # per minute, capped at 30 bonus
XP_QUEST_MULTIPLIER = 1.5


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


# ══════════════════════════════════════════════
# RELATIONSHIP LEVELS
# ══════════════════════════════════════════════

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


# ══════════════════════════════════════════════
# PHASE 2: HP RECOVERY
# ══════════════════════════════════════════════

HP_RECOVERY = {
    "interaction_in_person": 10,
    "interaction_video_call": 5,
    "interaction_call": 3,
    "interaction_other": 2,
    "quest_complete": 5,
    "party_complete": 15,
    "boss_clear": 20,
    "daily_checkin_streak": 3,  # only if streak >= 3
}
HP_MAX = 100
HP_EXHAUSTED_THRESHOLD = 0  # at 0 HP = exhausted debuff
HP_POTION_COST = 50  # XP cost for HP potion
HP_POTION_HEAL = 25


def recover_hp(user: User, source: str, skill_bonus: int = 0):
    """Add HP from an action. Caps at HP_MAX."""
    amount = HP_RECOVERY.get(source, 0) + skill_bonus
    if amount > 0:
        user.hp = min(HP_MAX, (user.hp or 0) + amount)


def is_exhausted(user: User) -> bool:
    """Check if user is in exhausted state (0 HP)."""
    return (user.hp or 0) <= HP_EXHAUSTED_THRESHOLD


def get_xp_penalty(user: User) -> float:
    """Returns XP multiplier penalty. 0.5x if exhausted, 1.0x otherwise."""
    return 0.5 if is_exhausted(user) else 1.0


# ══════════════════════════════════════════════
# XP AWARD (with stat effects + HP recovery)
# ══════════════════════════════════════════════

def award_interaction_xp(user: User, contact: Contact, interaction: Interaction, db: Session) -> dict:
    """Award XP for logging an interaction. Returns XP breakdown."""
    bonuses = get_stat_bonuses(user, db)

    base = XP_INTERACTION.get(interaction.interaction_type, 10)
    duration_bonus = min(30, int(interaction.duration_minutes * XP_DURATION_BONUS))
    raw_total = base + duration_bonus

    # Apply stat multipliers + buff multipliers
    buff_xp_mult = get_active_buff_multiplier(user, "xp_mult")
    xp_mult = bonuses["global_xp_mult"] * get_xp_penalty(user) * buff_xp_mult
    buff_rel_mult = get_active_buff_multiplier(user, "relationship_xp_mult")
    relationship_mult = bonuses["relationship_xp_mult"] * buff_rel_mult

    total = int(raw_total * xp_mult)

    # Update user XP
    old_level = user.level or 1
    user.xp = (user.xp or 0) + total
    user.level = level_from_xp(user.xp)

    # Grant stat points + skill points on level-up
    if user.level > old_level:
        levels_gained = user.level - old_level
        user.stat_points = (user.stat_points or 0) + (3 * levels_gained)
        user.skill_points = (user.skill_points or 0) + (1 * levels_gained)
        # Apply class-specific level-up bonuses (MapleStory-style)
        apply_levelup_bonuses(user, levels_gained)

    # Trigger buffs based on interaction conditions
    if (interaction.duration_minutes or 0) >= 30:
        check_and_apply_buffs(user, "long_interaction", db)
    if (user.streak_days or 0) >= 7:
        check_and_apply_buffs(user, "streak_7", db)

    # Update contact relationship XP (with empathy bonus)
    rel_xp = int(raw_total * relationship_mult)
    contact.relationship_xp = (contact.relationship_xp or 0) + rel_xp
    contact.relationship_level = relationship_level_from_xp(contact.relationship_xp)

    # HP recovery from interaction
    if interaction.interaction_type == InteractionType.in_person:
        hp_source = "interaction_in_person"
    elif interaction.interaction_type == InteractionType.video_call:
        hp_source = "interaction_video_call"
    elif interaction.interaction_type == InteractionType.call:
        hp_source = "interaction_call"
    else:
        hp_source = "interaction_other"
    recover_hp(user, hp_source, bonuses.get("hp_per_interaction", 0))

    # Update streak
    today = date.today()
    if user.last_active_date != today:
        if user.last_active_date == today - timedelta(days=1):
            user.streak_days = (user.streak_days or 0) + 1
        else:
            user.streak_days = 1
        user.last_active_date = today

    # Progress quest chains
    progress_quest_chains(user, interaction, db)

    # Progress circle XP
    progress_circle_xp(user, contact, raw_total, db)

    # Progress boss raids (interaction = damage)
    progress_boss_raids(user, interaction, bonuses, db)

    db.commit()

    # Check achievements
    new_achievements = check_achievements(user, contact, db)

    return {
        "xp_earned": total,
        "base_xp": base,
        "duration_bonus": duration_bonus,
        "stat_bonus": total - (base + duration_bonus),
        "hp_recovered": HP_RECOVERY.get(hp_source, 0) + bonuses.get("hp_per_interaction", 0),
        "new_level": user.level,
        "new_achievements": new_achievements,
    }


# ══════════════════════════════════════════════
# QUEST GENERATION
# ══════════════════════════════════════════════

QUEST_TEMPLATES = [
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

    bonuses = get_stat_bonuses(user, db)
    max_quests = bonuses.get("max_active_quests", 3)

    active_count = db.query(func.count(Quest.id)).filter(
        Quest.user_id == user.id,
        Quest.status == QuestStatus.active,
    ).scalar() or 0
    if active_count >= max_quests:
        return []

    now = datetime.utcnow()
    new_quests = []
    slots = max_quests - active_count

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

    available_templates = list(QUEST_TEMPLATES)
    random.shuffle(available_templates)

    for template in available_templates:
        if slots <= 0:
            break

        qtype, diff, xp, title_tmpl, desc_tmpl, needs_contact = template

        if needs_contact and not contact_scores:
            continue

        existing = db.query(Quest).filter(
            Quest.user_id == user.id,
            Quest.quest_type == qtype,
            Quest.status == QuestStatus.active,
        ).first()
        if existing:
            continue

        if needs_contact:
            contact, days_silent = contact_scores[0]
            if qtype == QuestType.reconnect and days_silent < 7:
                continue
            title = title_tmpl.format(name=contact.name)
            desc = desc_tmpl.format(name=contact.name)
            contact_id = contact.id
            contact_scores.append(contact_scores.pop(0))
        else:
            title = title_tmpl
            desc = desc_tmpl
            contact_id = None

        # Apply initiative stat bonus to quest XP
        bonuses = get_stat_bonuses(user, db)
        quest_xp = int(xp * bonuses.get("quest_xp_mult", 1.0))

        expire_days = {DifficultyTier.easy: 3, DifficultyTier.medium: 7, DifficultyTier.hard: 14}
        expires_at = now + timedelta(days=expire_days.get(diff, 7))

        quest = Quest(
            user_id=user.id,
            contact_id=contact_id,
            title=title,
            description=desc,
            quest_type=qtype,
            difficulty=diff,
            xp_reward=quest_xp,
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

    bonuses = get_stat_bonuses(user, db)
    xp = int(quest.xp_reward * bonuses["global_xp_mult"] * get_xp_penalty(user))
    old_level = user.level or 1
    user.xp = (user.xp or 0) + xp
    user.level = level_from_xp(user.xp)

    if user.level > old_level:
        levels_gained = user.level - old_level
        user.stat_points = (user.stat_points or 0) + (3 * levels_gained)
        user.skill_points = (user.skill_points or 0) + (1 * levels_gained)

    # HP recovery from quest
    recover_hp(user, "quest_complete")

    db.commit()

    new_achievements = check_achievements(user, None, db)

    return {
        "xp_earned": xp,
        "new_level": user.level,
        "new_achievements": new_achievements,
    }


# ══════════════════════════════════════════════
# PHASE 3: QUEST CHAINS
# ══════════════════════════════════════════════

QUEST_CHAIN_DEFS = {
    "reconnection_saga": {
        "name": "The Reconnection Saga",
        "description": "Rebuild a fading connection from scratch",
        "total_steps": 5,
        "steps": [
            {"title": "The First Call", "desc": "Call someone you haven't spoken to in 30+ days", "xp": 30,
             "condition": "call_silent_30"},
            {"title": "The Follow-Up", "desc": "Meet them in person within 7 days of the call", "xp": 50,
             "condition": "in_person_within_7"},
            {"title": "Building Momentum", "desc": "Log 3 more interactions with them in 14 days", "xp": 40,
             "condition": "3_interactions_14_days"},
            {"title": "Going Deep", "desc": "Have a 30+ minute interaction with them", "xp": 45,
             "condition": "long_interaction_30min"},
            {"title": "Inner Circle", "desc": "Get them to 'close' relationship level", "xp": 60,
             "condition": "relationship_close"},
        ],
        "chain_bonus_xp": 200,
        "chain_bonus_title": "The Reviver",
    },
    "party_animal": {
        "name": "Party Animal",
        "description": "Become the ultimate social event organizer",
        "total_steps": 4,
        "steps": [
            {"title": "First Party", "desc": "Create and complete your first party", "xp": 20,
             "condition": "complete_1_party"},
            {"title": "Party Regular", "desc": "Complete 3 parties with 2+ members each", "xp": 50,
             "condition": "3_parties_with_members"},
            {"title": "Social Mixer", "desc": "Complete parties in 3 different activity types", "xp": 80,
             "condition": "3_different_party_types"},
            {"title": "Legendary Host", "desc": "Complete 10 total parties", "xp": 60,
             "condition": "10_total_parties"},
        ],
        "chain_bonus_xp": 150,
        "chain_bonus_title": "Legendary Host",
    },
    "the_marathon": {
        "name": "The Marathon",
        "description": "Push your consistency to the limit",
        "total_steps": 3,
        "steps": [
            {"title": "Week Warrior", "desc": "Maintain a 7-day streak", "xp": 35,
             "condition": "streak_7"},
            {"title": "Fortnight Force", "desc": "Maintain a 14-day streak", "xp": 70,
             "condition": "streak_14"},
            {"title": "Monthly Master", "desc": "Maintain a 30-day streak", "xp": 150,
             "condition": "streak_30"},
        ],
        "chain_bonus_xp": 100,
        "chain_bonus_title": "Unstoppable Force",
    },
    "shadow_hunter": {
        "name": "Shadow Hunter",
        "description": "Build your shadow army from the strongest bonds",
        "total_steps": 4,
        "steps": [
            {"title": "First Extraction", "desc": "Extract your first shadow", "xp": 25,
             "condition": "1_shadow"},
            {"title": "Shadow Squad", "desc": "Have 5 shadows in your army", "xp": 50,
             "condition": "5_shadows"},
            {"title": "Elite Shadows", "desc": "Have 3 shadows at elite grade or higher", "xp": 75,
             "condition": "3_elite_shadows"},
            {"title": "Shadow Legion", "desc": "Have 15 shadows in your army", "xp": 100,
             "condition": "15_shadows"},
        ],
        "chain_bonus_xp": 200,
        "chain_bonus_title": "Shadow Commander",
    },
    "gate_crawler": {
        "name": "Gate Crawler",
        "description": "Conquer gates of increasing difficulty",
        "total_steps": 4,
        "steps": [
            {"title": "Gate Opener", "desc": "Clear your first gate", "xp": 30,
             "condition": "1_gate_cleared"},
            {"title": "D-Rank Gates", "desc": "Clear a D-Rank or higher gate", "xp": 50,
             "condition": "d_rank_gate"},
            {"title": "B-Rank Breaker", "desc": "Clear a B-Rank or higher gate", "xp": 100,
             "condition": "b_rank_gate"},
            {"title": "S-Rank Conqueror", "desc": "Clear an S-Rank or higher gate", "xp": 200,
             "condition": "s_rank_gate"},
        ],
        "chain_bonus_xp": 300,
        "chain_bonus_title": "Gate Master",
    },
}


def get_user_chains(user: User, db: Session) -> list:
    """Get all chain progress for a user, including available ones."""
    active_chains = db.query(QuestChain).filter(
        QuestChain.user_id == user.id
    ).all()

    chain_map = {c.chain_key: c for c in active_chains}
    result = []

    for key, defn in QUEST_CHAIN_DEFS.items():
        chain = chain_map.get(key)
        steps_info = []
        for i, step in enumerate(defn["steps"], 1):
            steps_info.append({
                "step": i,
                "title": step["title"],
                "description": step["desc"],
                "xp_reward": step["xp"],
                "completed": chain is not None and i < (chain.current_step or 1),
                "current": chain is not None and i == (chain.current_step or 1) and chain.status == QuestChainStatus.active,
            })

        result.append({
            "chain_key": key,
            "name": defn["name"],
            "description": defn["description"],
            "total_steps": defn["total_steps"],
            "current_step": chain.current_step if chain else 0,
            "status": chain.status.value if chain else "available",
            "chain_bonus_xp": defn["chain_bonus_xp"],
            "chain_bonus_title": defn.get("chain_bonus_title", ""),
            "steps": steps_info,
        })

    return result


def start_quest_chain(user: User, chain_key: str, db: Session) -> dict:
    """Start a quest chain for a user."""
    if chain_key not in QUEST_CHAIN_DEFS:
        return {"error": "Unknown quest chain"}

    existing = db.query(QuestChain).filter(
        QuestChain.user_id == user.id,
        QuestChain.chain_key == chain_key,
    ).first()
    if existing:
        return {"error": "Chain already started"}

    defn = QUEST_CHAIN_DEFS[chain_key]
    chain = QuestChain(
        user_id=user.id,
        chain_key=chain_key,
        current_step=1,
        total_steps=defn["total_steps"],
    )
    db.add(chain)
    db.commit()
    db.refresh(chain)

    return {
        "chain_key": chain_key,
        "name": defn["name"],
        "current_step": 1,
        "total_steps": defn["total_steps"],
        "status": "active",
    }


def check_chain_step(user: User, chain: QuestChain, db: Session) -> bool:
    """Check if the current step of a chain is completed. Returns True if advanced."""
    defn = QUEST_CHAIN_DEFS.get(chain.chain_key)
    if not defn:
        return False

    step_idx = (chain.current_step or 1) - 1
    if step_idx >= len(defn["steps"]):
        return False

    step = defn["steps"][step_idx]
    condition = step["condition"]
    chain_data = json.loads(chain.chain_data or "{}")

    met = _evaluate_chain_condition(user, condition, chain_data, db)
    if not met:
        return False

    # Award step XP
    xp = step["xp"]
    user.xp = (user.xp or 0) + xp
    user.level = level_from_xp(user.xp)

    chain.current_step = (chain.current_step or 1) + 1

    # Check if chain is completed
    if chain.current_step > chain.total_steps:
        chain.status = QuestChainStatus.completed
        chain.completed_at = datetime.utcnow()
        # Award chain bonus
        bonus_xp = defn.get("chain_bonus_xp", 0)
        user.xp = (user.xp or 0) + bonus_xp
        user.level = level_from_xp(user.xp)
        # Award title
        bonus_title = defn.get("chain_bonus_title")
        if bonus_title:
            user.title = bonus_title

    db.commit()
    return True


def _evaluate_chain_condition(user: User, condition: str, chain_data: dict, db: Session) -> bool:
    """Evaluate a quest chain step condition."""
    if condition == "call_silent_30":
        # Has the user called someone who was silent for 30+ days?
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        return db.query(Interaction).filter(
            Interaction.user_id == user.id,
            Interaction.interaction_type.in_([InteractionType.call, InteractionType.video_call]),
            Interaction.timestamp >= datetime.utcnow() - timedelta(days=7),
        ).first() is not None

    elif condition == "in_person_within_7":
        seven_days = datetime.utcnow() - timedelta(days=7)
        return db.query(Interaction).filter(
            Interaction.user_id == user.id,
            Interaction.interaction_type == InteractionType.in_person,
            Interaction.timestamp >= seven_days,
        ).first() is not None

    elif condition == "3_interactions_14_days":
        two_weeks = datetime.utcnow() - timedelta(days=14)
        count = db.query(func.count(Interaction.id)).filter(
            Interaction.user_id == user.id,
            Interaction.timestamp >= two_weeks,
        ).scalar() or 0
        return count >= 3

    elif condition == "long_interaction_30min":
        return db.query(Interaction).filter(
            Interaction.user_id == user.id,
            Interaction.duration_minutes >= 30,
        ).first() is not None

    elif condition == "relationship_close":
        return db.query(Contact).filter(
            Contact.user_id == user.id,
            Contact.relationship_xp >= 500,
        ).first() is not None

    elif condition == "complete_1_party":
        return db.query(Party).filter(
            Party.creator_id == user.id,
            Party.status == PartyStatus.completed,
        ).first() is not None

    elif condition == "3_parties_with_members":
        parties = db.query(Party).filter(
            Party.creator_id == user.id,
            Party.status == PartyStatus.completed,
        ).all()
        count = 0
        for p in parties:
            joined = db.query(func.count(PartyMember.id)).filter(
                PartyMember.party_id == p.id,
                PartyMember.status == "joined",
            ).scalar() or 0
            if joined >= 2:
                count += 1
        return count >= 3

    elif condition == "3_different_party_types":
        types = db.query(Party.activity_type).filter(
            Party.creator_id == user.id,
            Party.status == PartyStatus.completed,
        ).distinct().all()
        return len(types) >= 3

    elif condition == "10_total_parties":
        count = db.query(func.count(Party.id)).filter(
            Party.creator_id == user.id,
            Party.status == PartyStatus.completed,
        ).scalar() or 0
        return count >= 10

    elif condition == "streak_7":
        return (user.streak_days or 0) >= 7
    elif condition == "streak_14":
        return (user.streak_days or 0) >= 14
    elif condition == "streak_30":
        return (user.streak_days or 0) >= 30

    elif condition == "1_shadow":
        return (user.shadow_army_count or 0) >= 1
    elif condition == "5_shadows":
        return (user.shadow_army_count or 0) >= 5
    elif condition == "3_elite_shadows":
        elite_count = db.query(func.count(Contact.id)).filter(
            Contact.user_id == user.id,
            Contact.shadow_grade.in_(["elite", "knight", "general", "marshal"]),
        ).scalar() or 0
        return elite_count >= 3
    elif condition == "15_shadows":
        return (user.shadow_army_count or 0) >= 15

    elif condition == "1_gate_cleared":
        return db.query(Gate).filter(
            Gate.creator_id == user.id, Gate.status == "cleared"
        ).first() is not None
    elif condition == "d_rank_gate":
        return db.query(Gate).filter(
            Gate.creator_id == user.id, Gate.status == "cleared",
            Gate.gate_rank.in_(["D-Rank", "C-Rank", "B-Rank", "A-Rank", "S-Rank", "SS-Rank", "Monarch"]),
        ).first() is not None
    elif condition == "b_rank_gate":
        return db.query(Gate).filter(
            Gate.creator_id == user.id, Gate.status == "cleared",
            Gate.gate_rank.in_(["B-Rank", "A-Rank", "S-Rank", "SS-Rank", "Monarch"]),
        ).first() is not None
    elif condition == "s_rank_gate":
        return db.query(Gate).filter(
            Gate.creator_id == user.id, Gate.status == "cleared",
            Gate.gate_rank.in_(["S-Rank", "SS-Rank", "Monarch"]),
        ).first() is not None

    return False


def progress_quest_chains(user: User, interaction: Interaction, db: Session):
    """Check all active quest chains for progress after an interaction."""
    active_chains = db.query(QuestChain).filter(
        QuestChain.user_id == user.id,
        QuestChain.status == QuestChainStatus.active,
    ).all()
    for chain in active_chains:
        check_chain_step(user, chain, db)


# ══════════════════════════════════════════════
# PHASE 4: ACHIEVEMENTS (expanded from 16 to 36)
# ══════════════════════════════════════════════

ACHIEVEMENT_DEFS = [
    # Original 16
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
    # Phase 4: New achievements (20 more)
    ("party_3", "Party Starter", "Complete 3 parties", "confetti", 40),
    ("party_10", "Event Planner", "Complete 10 parties", "calendar", 100),
    ("challenge_5", "Challenger", "Complete 5 challenges", "swords", 50),
    ("challenge_10", "Champion", "Complete 10 challenges", "medal", 120),
    ("gate_3", "Gate Keeper", "Clear 3 gates", "door", 60),
    ("gate_10", "Dungeon Master", "Clear 10 gates", "castle", 150),
    ("boss_1", "Boss Slayer", "Clear your first boss raid", "skull", 50),
    ("boss_5", "Raid Leader", "Clear 5 boss raids", "dragon", 120),
    ("shadow_5", "Shadow Squad", "Extract 5 shadows", "ghost", 40),
    ("shadow_20", "Shadow Legion", "Extract 20 shadows", "army", 200),
    ("chain_1", "Chain Starter", "Complete your first quest chain", "chain", 75),
    ("chain_3", "Storyline Hero", "Complete 3 quest chains", "book", 200),
    ("diverse_5", "Renaissance Soul", "Use all 6 interaction types in one week", "rainbow", 60),
    ("level_20", "Veteran", "Reach level 20", "shield", 100),
    ("level_30", "Elite", "Reach level 30", "diamond", 150),
    ("monarch", "The Monarch", "Reach Monarch rank", "crown_royal", 500),
    ("hp_survive", "Survivor", "Recover from below 20 HP to full", "phoenix", 30),
    ("perfect_week", "Perfect Week", "Interact every day for 7 days straight", "calendar_check", 75),
    ("circle_1", "Circle Founder", "Create your first circle", "circle", 25),
    ("skill_1", "Skilled", "Unlock your first skill", "sparkle", 30),
]


def check_achievements(user: User, contact: Optional[Contact], db: Session) -> list:
    """Check and award any newly earned achievements. Returns list of new ones."""
    earned = {ua.achievement_key for ua in
              db.query(UserAchievement).filter(UserAchievement.user_id == user.id).all()}

    new_achievements = []

    def try_award(key: str, condition: bool):
        if key not in earned and condition:
            ua = UserAchievement(user_id=user.id, achievement_key=key)
            db.add(ua)
            for akey, name, desc, icon, xp in ACHIEVEMENT_DEFS:
                if akey == key:
                    user.xp = (user.xp or 0) + xp
                    new_achievements.append({"key": key, "name": name, "xp_bonus": xp})
                    break

    # Contact count
    contact_count = db.query(func.count(Contact.id)).filter(Contact.user_id == user.id).scalar() or 0
    try_award("first_contact", contact_count >= 1)
    try_award("social_5", contact_count >= 5)
    try_award("social_10", contact_count >= 10)

    # Interaction count
    interaction_count = db.query(func.count(Interaction.id)).filter(Interaction.user_id == user.id).scalar() or 0
    try_award("first_interaction", interaction_count >= 1)
    try_award("interactions_10", interaction_count >= 10)
    try_award("interactions_50", interaction_count >= 50)

    # Streak
    streak = user.streak_days or 0
    try_award("streak_3", streak >= 3)
    try_award("streak_7", streak >= 7)
    try_award("streak_30", streak >= 30)

    # Quest count
    quest_count = db.query(func.count(Quest.id)).filter(
        Quest.user_id == user.id, Quest.status == QuestStatus.completed
    ).scalar() or 0
    try_award("quest_1", quest_count >= 1)
    try_award("quest_5", quest_count >= 5)
    try_award("quest_10", quest_count >= 10)

    # Level
    try_award("level_5", (user.level or 1) >= 5)
    try_award("level_10", (user.level or 1) >= 10)
    try_award("level_20", (user.level or 1) >= 20)
    try_award("level_30", (user.level or 1) >= 30)

    # In-person meetups
    in_person_count = db.query(func.count(Interaction.id)).filter(
        Interaction.user_id == user.id,
        Interaction.interaction_type == InteractionType.in_person,
    ).scalar() or 0
    try_award("in_person_5", in_person_count >= 5)

    # Inner circle
    if contact and (contact.relationship_xp or 0) >= 1000:
        try_award("inner_circle", True)

    # Party achievements
    party_count = db.query(func.count(Party.id)).filter(
        Party.creator_id == user.id, Party.status == PartyStatus.completed
    ).scalar() or 0
    try_award("party_3", party_count >= 3)
    try_award("party_10", party_count >= 10)

    # Challenge achievements
    challenge_count = db.query(func.count(Challenge.id)).filter(
        Challenge.challenger_id == user.id, Challenge.status == ChallengeStatus.completed
    ).scalar() or 0
    try_award("challenge_5", challenge_count >= 5)
    try_award("challenge_10", challenge_count >= 10)

    # Gate achievements
    gate_count = db.query(func.count(Gate.id)).filter(
        Gate.creator_id == user.id, Gate.status == "cleared"
    ).scalar() or 0
    try_award("gate_3", gate_count >= 3)
    try_award("gate_10", gate_count >= 10)

    # Boss achievements
    boss_count = db.query(func.count(BossRaid.id)).filter(
        BossRaid.creator_id == user.id, BossRaid.status == "cleared"
    ).scalar() or 0
    try_award("boss_1", boss_count >= 1)
    try_award("boss_5", boss_count >= 5)

    # Shadow achievements
    shadow_count = user.shadow_army_count or 0
    try_award("shadow_5", shadow_count >= 5)
    try_award("shadow_20", shadow_count >= 20)

    # Chain achievements
    chain_count = db.query(func.count(QuestChain.id)).filter(
        QuestChain.user_id == user.id, QuestChain.status == QuestChainStatus.completed
    ).scalar() or 0
    try_award("chain_1", chain_count >= 1)
    try_award("chain_3", chain_count >= 3)

    # Diverse interactions (all 6 types in last 7 days)
    week_ago = datetime.utcnow() - timedelta(days=7)
    distinct_types = db.query(Interaction.interaction_type).filter(
        Interaction.user_id == user.id,
        Interaction.timestamp >= week_ago,
    ).distinct().all()
    try_award("diverse_5", len(distinct_types) >= 6)

    # Monarch rank
    from .models import HunterRank
    try_award("monarch", user.hunter_rank == HunterRank.monarch)

    # HP survive (recovered from <20 to 100)
    try_award("hp_survive", (user.hp or 0) >= 100 and "was_low_hp" in (user.title or ""))
    # Note: hp_survive tracked via flag — set when HP drops below 20

    # Perfect week = 7+ streak
    try_award("perfect_week", streak >= 7)

    # Circle founder
    circle_count = db.query(func.count(Circle.id)).filter(Circle.user_id == user.id).scalar() or 0
    try_award("circle_1", circle_count >= 1)

    # Skill unlock
    skill_count = db.query(func.count(UserSkill.id)).filter(UserSkill.user_id == user.id).scalar() or 0
    try_award("skill_1", skill_count >= 1)

    if new_achievements:
        user.level = level_from_xp(user.xp)
        db.commit()

    return new_achievements


# ══════════════════════════════════════════════
# PHASE 5: BOSS RAID MECHANICS
# ══════════════════════════════════════════════

BOSS_TEMPLATES = {
    "shadow_beast": {
        "name": "Shadow Beast",
        "description": "A basic shadow creature. Deal damage by logging any interaction.",
        "hp": 100,
        "xp_reward": 200,
        "stat_points": 3,
        "phases": 1,
        "mechanic": "basic",  # any interaction deals damage
    },
    "the_drifter": {
        "name": "The Drifter",
        "description": "A restless spirit that can only be harmed by diverse social efforts. Use 3+ different interaction types to deal damage.",
        "hp": 300,
        "xp_reward": 500,
        "stat_points": 5,
        "phases": 1,
        "mechanic": "diverse",  # requires 3+ different interaction types
    },
    "social_hydra": {
        "name": "Social Hydra",
        "description": "A three-headed beast. Each head requires a different attack: Call, Text, and In-Person. All three within 24h to deal massive damage.",
        "hp": 500,
        "xp_reward": 800,
        "stat_points": 8,
        "phases": 3,
        "mechanic": "hydra",  # 3 heads: call, text, in_person — all 3 in 24h for damage
    },
    "the_monarch": {
        "name": "The Monarch",
        "description": "The ultimate boss. Requires sustained effort: each interaction chips away, but damage increases with your streak. 1000 HP, 14-day time limit.",
        "hp": 1000,
        "xp_reward": 1500,
        "stat_points": 15,
        "phases": 3,
        "mechanic": "monarch",  # damage scales with streak + stats
    },
}


"""
MapleStory-style damage formula adapted for CRM:
  damage = ((class_mult * mainstat + secondary_stat) / 100) * attack_power * mastery_range
  - mainstat depends on social class (Connector=CHA, Nurturer=EMP, Catalyst=INI, Sage=WIS)
  - secondary_stat is the second-highest stat
  - attack_power comes from interaction quality (type + duration)
  - mastery_range adds variance (0.8-1.0 for beginners, 0.9-1.0 for masters)
"""

# Interaction "attack power" — replaces weapon attack in MapleStory
INTERACTION_ATTACK_POWER = {
    InteractionType.in_person: 30,
    InteractionType.video_call: 22,
    InteractionType.call: 18,
    InteractionType.email: 12,
    InteractionType.text: 10,
    InteractionType.social_media: 8,
}

# Class multipliers — which stat is "main" for each class (like STR for Warriors)
CLASS_MAIN_STAT = {
    "connector": "stat_charisma",
    "nurturer": "stat_empathy",
    "catalyst": "stat_initiative",
    "sage": "stat_wisdom",
}

CLASS_WEAPON_MULT = {
    "connector": 4.0,   # Broad reach, moderate per-hit
    "nurturer": 3.5,    # Steady, reliable damage
    "catalyst": 4.5,    # High burst from groups
    "sage": 3.0,        # Lower base but streak scaling
}


def _get_main_secondary_stats(user: User) -> tuple:
    """Get main stat value and secondary stat value based on class."""
    class_key = user.social_class or "connector"
    main_attr = CLASS_MAIN_STAT.get(class_key, "stat_charisma")
    main_val = getattr(user, main_attr, 1) or 1

    # Secondary = second highest stat (like DEX for Warriors in MapleStory)
    all_stats = {
        "stat_charisma": user.stat_charisma or 1,
        "stat_empathy": user.stat_empathy or 1,
        "stat_consistency": user.stat_consistency or 1,
        "stat_initiative": user.stat_initiative or 1,
        "stat_wisdom": user.stat_wisdom or 1,
    }
    del all_stats[main_attr]
    secondary_val = max(all_stats.values())

    return main_val, secondary_val


def calculate_damage(user: User, interaction: Interaction) -> dict:
    """MapleStory-style damage formula. Returns breakdown dict."""
    class_key = user.social_class or "connector"
    weapon_mult = CLASS_WEAPON_MULT.get(class_key, 4.0)
    main_val, secondary_val = _get_main_secondary_stats(user)

    # Attack power from interaction type + duration bonus
    atk = INTERACTION_ATTACK_POWER.get(interaction.interaction_type, 10)
    duration_atk = min(15, int((interaction.duration_minutes or 0) * 0.3))
    total_atk = atk + duration_atk

    # Core formula: ((weapon_mult * mainstat + secondary) / 100) * attack
    raw_max = ((weapon_mult * main_val + secondary_val) / 100) * total_atk
    raw_max = max(raw_max, 1)

    # Mastery range (MapleStory: skills increase mastery from 20% to 60%)
    # Here: job tier increases mastery
    job_tier = user.job_tier or 0
    mastery = 0.5 + job_tier * 0.1  # 0.5 base, up to 0.9 at 4th job
    min_damage = int(raw_max * mastery)
    max_damage = int(raw_max)

    # Apply critical hit (10% chance, 1.5x damage)
    is_crit = random.random() < 0.10 + (user.stat_initiative or 1) * 0.005
    actual = random.randint(min_damage, max(min_damage, max_damage))
    if is_crit:
        actual = int(actual * 1.5)

    return {
        "damage": max(1, actual),
        "min_damage": min_damage,
        "max_damage": max_damage,
        "is_crit": is_crit,
        "main_stat": main_val,
        "attack_power": total_atk,
        "mastery": mastery,
    }


def calculate_boss_damage(user: User, interaction: Interaction, boss: BossRaid, bonuses: dict, db: Session) -> int:
    """Calculate damage dealt to a boss using MapleStory-style formula + boss mechanics."""
    boss_type = boss.boss_type or "shadow_beast"
    template = BOSS_TEMPLATES.get(boss_type, BOSS_TEMPLATES["shadow_beast"])
    mechanic = template["mechanic"]
    mechanic_data = json.loads(boss.mechanic_data or "{}")

    # Base damage from stat formula
    dmg_result = calculate_damage(user, interaction)
    base_damage = dmg_result["damage"]

    if mechanic == "basic":
        damage = base_damage

    elif mechanic == "diverse":
        types_used = set(mechanic_data.get("types_used", []))
        types_used.add(interaction.interaction_type.value)
        mechanic_data["types_used"] = list(types_used)
        boss.mechanic_data = json.dumps(mechanic_data)

        if len(types_used) >= 3:
            damage = int(base_damage * 1.5)  # 1.5x when diverse
        else:
            damage = int(base_damage * 0.4)  # weak until diverse

    elif mechanic == "hydra":
        now = datetime.utcnow()
        heads = mechanic_data.get("heads", {"call": None, "text": None, "in_person": None})

        itype = interaction.interaction_type.value
        if itype in ("call", "video_call"):
            heads["call"] = now.isoformat()
        elif itype in ("text", "social_media", "email"):
            heads["text"] = now.isoformat()
        elif itype == "in_person":
            heads["in_person"] = now.isoformat()

        all_hit = True
        for head_time in heads.values():
            if head_time is None:
                all_hit = False
                break
            ht = datetime.fromisoformat(head_time)
            if (now - ht).total_seconds() > 86400:
                all_hit = False
                break

        mechanic_data["heads"] = heads
        boss.mechanic_data = json.dumps(mechanic_data)

        if all_hit:
            damage = int(base_damage * 3.0)  # massive hit when all 3 heads
            mechanic_data["heads"] = {"call": None, "text": None, "in_person": None}
            boss.mechanic_data = json.dumps(mechanic_data)
        else:
            damage = int(base_damage * 0.3)  # chip damage

    elif mechanic == "monarch":
        streak = user.streak_days or 0
        streak_mult = 1.0 + min(streak, 30) * 0.05  # up to 2.5x at 30-day streak
        damage = int(base_damage * streak_mult)

    else:
        damage = base_damage

    # Apply buff multipliers
    buff_mult = get_active_buff_multiplier(user, "boss_damage")
    damage = int(damage * buff_mult)

    # Apply wisdom global bonus
    damage = int(damage * bonuses.get("global_xp_mult", 1.0))

    return max(1, damage)


def progress_boss_raids(user: User, interaction: Interaction, bonuses: dict, db: Session):
    """Deal damage to all active boss raids when an interaction is logged."""
    active_raids = db.query(BossRaid).filter(
        BossRaid.creator_id == user.id,
        BossRaid.status == "active",
    ).all()

    for boss in active_raids:
        # Check expiry
        if boss.expires_at and datetime.utcnow() > boss.expires_at:
            boss.status = "failed"
            continue

        damage = calculate_boss_damage(user, interaction, boss, bonuses, db)
        boss.boss_hp = max(0, (boss.boss_hp or 0) - damage)

        # Check if boss is defeated
        if boss.boss_hp <= 0:
            boss.status = "cleared"
            boss.cleared_at = datetime.utcnow()
            boss.boss_hp = 0

            # Award rewards
            user.xp = (user.xp or 0) + (boss.xp_reward or 200)
            user.level = level_from_xp(user.xp)
            user.stat_points = (user.stat_points or 0) + (boss.stat_points_reward or 3)

            # HP recovery
            recover_hp(user, "boss_clear")


# ══════════════════════════════════════════════
# PHASE 6: SKILL TREE & SOCIAL CLASSES
# ══════════════════════════════════════════════

SOCIAL_CLASSES = {
    "connector": {
        "name": "Connector",
        "description": "Master of breadth — more quests, more contacts, wider reach",
        "unlock_level": 5,
        "skills": {
            "wide_net": {"name": "Wide Net", "desc": "+1 max active quest per level", "max_level": 3, "sp_cost": 1},
            "social_butterfly": {"name": "Social Butterfly", "desc": "+50% XP for new contacts per level", "max_level": 3, "sp_cost": 1},
            "speed_dial": {"name": "Speed Dial", "desc": "+15% XP from text/social media per level", "max_level": 2, "sp_cost": 2},
            "first_impression": {"name": "First Impression", "desc": "+30 XP when adding a new contact", "max_level": 1, "sp_cost": 2},
            "network_effect": {"name": "Network Effect", "desc": "+3% global XP per 10 contacts", "max_level": 2, "sp_cost": 3},
            "hub_master": {"name": "Hub Master", "desc": "Circles give +25% XP per level", "max_level": 2, "sp_cost": 3},
        },
    },
    "nurturer": {
        "name": "Nurturer",
        "description": "Master of depth — stronger bonds, faster relationship growth",
        "unlock_level": 5,
        "skills": {
            "deep_roots": {"name": "Deep Roots", "desc": "+15% relationship XP per level", "max_level": 3, "sp_cost": 1},
            "healing_touch": {"name": "Healing Touch", "desc": "+5 HP per interaction per level", "max_level": 3, "sp_cost": 1},
            "emotional_intel": {"name": "Emotional Intelligence", "desc": "+20% XP from calls/video per level", "max_level": 2, "sp_cost": 2},
            "inner_strength": {"name": "Inner Strength", "desc": "+10 max HP per level", "max_level": 2, "sp_cost": 2},
            "bond_master": {"name": "Bond Master", "desc": "Relationship levels unlock 20% faster", "max_level": 2, "sp_cost": 3},
            "soulmate": {"name": "Soulmate", "desc": "Inner Circle contacts give 2x XP", "max_level": 1, "sp_cost": 3},
        },
    },
    "catalyst": {
        "name": "Catalyst",
        "description": "Master of groups — bigger parties, better events, more fun",
        "unlock_level": 10,
        "skills": {
            "party_leader": {"name": "Party Leader", "desc": "+2 max party members per level", "max_level": 3, "sp_cost": 1},
            "rally_cry": {"name": "Rally Cry", "desc": "+25% party XP per level", "max_level": 3, "sp_cost": 1},
            "challenge_master": {"name": "Challenge Master", "desc": "+30% challenge XP per level", "max_level": 2, "sp_cost": 2},
            "event_horizon": {"name": "Event Horizon", "desc": "Recurring parties give +50% XP", "max_level": 1, "sp_cost": 2},
            "mob_mentality": {"name": "Mob Mentality", "desc": "+5% XP per party member joined", "max_level": 2, "sp_cost": 3},
            "legendary_host": {"name": "Legendary Host", "desc": "Parties auto-complete gate progress", "max_level": 1, "sp_cost": 3},
        },
    },
    "sage": {
        "name": "Sage",
        "description": "Master of consistency — longer streaks, stronger discipline",
        "unlock_level": 10,
        "skills": {
            "iron_will": {"name": "Iron Will", "desc": "+2 free streak freezes per level", "max_level": 3, "sp_cost": 1},
            "meditation": {"name": "Meditation", "desc": "+25% daily check-in XP per level", "max_level": 3, "sp_cost": 1},
            "discipline": {"name": "Discipline", "desc": "+10% XP when streak >= 7", "max_level": 2, "sp_cost": 2},
            "time_mastery": {"name": "Time Mastery", "desc": "Quest deadlines extended by 2 days", "max_level": 2, "sp_cost": 2},
            "zen_master": {"name": "Zen Master", "desc": "HP loss from missed days reduced by 50%", "max_level": 2, "sp_cost": 3},
            "enlightened": {"name": "Enlightened", "desc": "All stat gains doubled", "max_level": 1, "sp_cost": 3},
        },
    },
}


def choose_social_class(user: User, class_key: str, db: Session) -> dict:
    """Choose a social class. Can only be done once (or at cost to respec)."""
    if class_key not in SOCIAL_CLASSES:
        return {"error": "Unknown class"}

    cls = SOCIAL_CLASSES[class_key]
    if (user.level or 1) < cls["unlock_level"]:
        return {"error": f"Requires level {cls['unlock_level']}"}

    if user.social_class and user.social_class == class_key:
        return {"error": "Already this class"}

    # If switching classes, reset skills (cost: lose all invested SP)
    if user.social_class:
        db.query(UserSkill).filter(UserSkill.user_id == user.id).delete()
        user.social_class = ""
        db.commit()

    user.social_class = class_key
    db.commit()

    return {
        "class": class_key,
        "name": cls["name"],
        "description": cls["description"],
        "skills": cls["skills"],
    }


def unlock_skill(user: User, skill_key: str, db: Session) -> dict:
    """Unlock or level up a skill using SP. Checks prerequisites and job tier."""
    if not user.social_class:
        return {"error": "Choose a social class first"}

    cls = SOCIAL_CLASSES.get(user.social_class)
    if not cls:
        return {"error": "Invalid class"}

    skill_def = cls["skills"].get(skill_key)
    if not skill_def:
        return {"error": "Skill not available for your class"}

    # Check prerequisites (MapleStory-style)
    prereq_check = check_skill_prerequisites(user, skill_key, db)
    if not prereq_check["met"]:
        return {"error": prereq_check["reason"]}

    existing = db.query(UserSkill).filter(
        UserSkill.user_id == user.id,
        UserSkill.skill_key == skill_key,
    ).first()

    current_level = existing.level if existing else 0
    if current_level >= skill_def["max_level"]:
        return {"error": "Skill already at max level"}

    sp_cost = skill_def["sp_cost"]
    if (user.skill_points or 0) < sp_cost:
        return {"error": f"Need {sp_cost} SP, have {user.skill_points or 0}"}

    user.skill_points = (user.skill_points or 0) - sp_cost

    if existing:
        existing.level += 1
    else:
        skill = UserSkill(user_id=user.id, skill_key=skill_key, level=1)
        db.add(skill)

    db.commit()

    # Check skill achievement
    check_achievements(user, None, db)

    return {
        "skill_key": skill_key,
        "name": skill_def["name"],
        "new_level": (current_level + 1),
        "max_level": skill_def["max_level"],
        "sp_remaining": user.skill_points,
    }


def get_skill_tree(user: User, db: Session) -> dict:
    """Get full skill tree state for a user."""
    user_skills = {s.skill_key: s.level for s in
                   db.query(UserSkill).filter(UserSkill.user_id == user.id).all()}

    result = {
        "social_class": user.social_class or "",
        "skill_points": user.skill_points or 0,
        "classes": {},
    }

    for key, cls in SOCIAL_CLASSES.items():
        class_info = {
            "name": cls["name"],
            "description": cls["description"],
            "unlock_level": cls["unlock_level"],
            "available": (user.level or 1) >= cls["unlock_level"],
            "selected": user.social_class == key,
            "skills": {},
        }
        for sk, sd in cls["skills"].items():
            class_info["skills"][sk] = {
                "name": sd["name"],
                "description": sd["desc"],
                "max_level": sd["max_level"],
                "current_level": user_skills.get(sk, 0),
                "sp_cost": sd["sp_cost"],
                "unlocked": sk in user_skills,
            }
        result["classes"][key] = class_info

    return result


# ══════════════════════════════════════════════
# PHASE 7: CIRCLES
# ══════════════════════════════════════════════

CIRCLE_LEVEL_THRESHOLDS = [0, 100, 300, 600, 1000, 2000, 4000, 8000]
CIRCLE_XP_BONUS = 0.1  # +10% XP for interactions within a circle


def circle_level_from_xp(xp: int) -> int:
    level = 1
    for i, threshold in enumerate(CIRCLE_LEVEL_THRESHOLDS):
        if xp >= threshold:
            level = i + 1
    return level


def progress_circle_xp(user: User, contact: Contact, base_xp: int, db: Session):
    """Award circle XP when interacting with a contact who is in a circle."""
    memberships = db.query(CircleMember).filter(
        CircleMember.contact_id == contact.id
    ).all()

    for mem in memberships:
        circle = db.query(Circle).filter(Circle.id == mem.circle_id, Circle.user_id == user.id).first()
        if circle:
            circle.xp_pool = (circle.xp_pool or 0) + base_xp
            circle.level = circle_level_from_xp(circle.xp_pool)

            # Check circle quest progress
            active_cq = db.query(CircleQuest).filter(
                CircleQuest.circle_id == circle.id,
                CircleQuest.user_id == user.id,
                CircleQuest.status == "active",
            ).all()
            for cq in active_cq:
                _progress_circle_quest(cq, contact, db)


def _progress_circle_quest(cq: CircleQuest, contact: Contact, db: Session):
    """Track progress on a circle quest."""
    progress = json.loads(cq.progress_data or "{}")
    contact_key = str(contact.id)

    if cq.quest_type == "interact_all":
        # Track which members have been interacted with
        interacted = progress.get("interacted", {})
        interacted[contact_key] = True
        progress["interacted"] = interacted
        cq.progress_data = json.dumps(progress)

        # Check if all members interacted with
        circle = db.query(Circle).filter(Circle.id == cq.circle_id).first()
        if circle:
            member_ids = {str(m.contact_id) for m in circle.members}
            if member_ids and member_ids.issubset(set(interacted.keys())):
                cq.status = "completed"
                cq.completed_at = datetime.utcnow()
                # Award XP
                user = db.query(User).filter(User.id == cq.user_id).first()
                if user:
                    user.xp = (user.xp or 0) + cq.xp_reward
                    user.level = level_from_xp(user.xp)


def create_circle_quest(circle: Circle, user: User, db: Session) -> CircleQuest:
    """Auto-generate a circle quest: interact with all members."""
    member_count = db.query(func.count(CircleMember.id)).filter(
        CircleMember.circle_id == circle.id
    ).scalar() or 0

    if member_count == 0:
        return None

    xp_reward = 50 + member_count * 20  # scales with circle size

    cq = CircleQuest(
        circle_id=circle.id,
        user_id=user.id,
        title=f"Connect with your {circle.name} circle",
        description=f"Interact with all {member_count} members of {circle.name} within 7 days",
        quest_type="interact_all",
        target=member_count,
        xp_reward=xp_reward,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db.add(cq)
    db.commit()
    db.refresh(cq)
    return cq


# ══════════════════════════════════════════════
# PHASE 8: JOB ADVANCEMENT SYSTEM
# (MapleStory-style: Beginner → 1st → 2nd → 3rd → 4th Job)
# ══════════════════════════════════════════════

JOB_ADVANCEMENT = {
    # tier: {level_req, stat_req, title_suffix, stat_bonus, hp_bonus, sp_bonus}
    0: {"name": "Beginner", "level_req": 1, "stat_bonus": {}, "hp_bonus": 0, "sp_bonus": 0},
    1: {
        "name": "1st Job",
        "level_req": 5,
        "stat_req": 10,  # main stat must be >= 10
        "hp_bonus": 20,
        "sp_bonus": 3,
        "stat_bonus": {"main": 3},  # +3 to main stat
    },
    2: {
        "name": "2nd Job",
        "level_req": 15,
        "stat_req": 25,
        "hp_bonus": 40,
        "sp_bonus": 5,
        "stat_bonus": {"main": 5, "secondary": 2},
        "quest_req": "complete_5_quests",
    },
    3: {
        "name": "3rd Job",
        "level_req": 30,
        "stat_req": 50,
        "hp_bonus": 60,
        "sp_bonus": 8,
        "stat_bonus": {"main": 8, "secondary": 4, "all": 2},
        "quest_req": "clear_3_gates",
    },
    4: {
        "name": "4th Job",
        "level_req": 50,
        "stat_req": 80,
        "hp_bonus": 100,
        "sp_bonus": 15,
        "stat_bonus": {"main": 12, "secondary": 6, "all": 5},
        "quest_req": "clear_boss_monarch",
        "title": "Master",
    },
}

# Job advancement titles per class
JOB_TITLES = {
    "connector": ["Novice", "Networker", "Influencer", "Socialite", "Grand Connector"],
    "nurturer": ["Novice", "Caretaker", "Counselor", "Guardian", "Grand Nurturer"],
    "catalyst": ["Novice", "Organizer", "Coordinator", "Director", "Grand Catalyst"],
    "sage": ["Novice", "Apprentice", "Scholar", "Philosopher", "Grand Sage"],
}


def check_job_advancement(user: User, db: Session) -> dict:
    """Check if user can advance to next job tier. Returns advancement info."""
    current_tier = user.job_tier or 0
    next_tier = current_tier + 1

    if next_tier not in JOB_ADVANCEMENT:
        return {"can_advance": False, "reason": "Already at maximum job tier"}

    req = JOB_ADVANCEMENT[next_tier]

    # Level check
    if (user.level or 1) < req["level_req"]:
        return {"can_advance": False, "reason": f"Need level {req['level_req']} (currently {user.level or 1})"}

    # Must have chosen a class first
    if not user.social_class:
        return {"can_advance": False, "reason": "Choose a social class first"}

    # Main stat check
    main_attr = CLASS_MAIN_STAT.get(user.social_class, "stat_charisma")
    main_val = getattr(user, main_attr, 1) or 1
    if main_val < req.get("stat_req", 0):
        return {"can_advance": False, "reason": f"Need {main_attr.replace('stat_', '').title()} >= {req['stat_req']} (currently {main_val})"}

    # Quest requirement check
    quest_req = req.get("quest_req")
    if quest_req:
        if quest_req == "complete_5_quests":
            count = db.query(func.count(Quest.id)).filter(
                Quest.user_id == user.id, Quest.status == QuestStatus.completed
            ).scalar() or 0
            if count < 5:
                return {"can_advance": False, "reason": f"Need 5 completed quests (have {count})"}
        elif quest_req == "clear_3_gates":
            count = db.query(func.count(Gate.id)).filter(
                Gate.creator_id == user.id, Gate.status == "cleared"
            ).scalar() or 0
            if count < 3:
                return {"can_advance": False, "reason": f"Need 3 cleared gates (have {count})"}
        elif quest_req == "clear_boss_monarch":
            count = db.query(func.count(BossRaid.id)).filter(
                BossRaid.creator_id == user.id, BossRaid.boss_type == "the_monarch",
                BossRaid.status == "cleared",
            ).scalar() or 0
            if count < 1:
                return {"can_advance": False, "reason": "Must defeat The Monarch boss"}

    return {"can_advance": True, "next_tier": next_tier, "requirements": req}


def perform_job_advancement(user: User, db: Session) -> dict:
    """Advance user to next job tier. Awards stat bonuses, HP, SP."""
    check = check_job_advancement(user, db)
    if not check.get("can_advance"):
        return {"error": check.get("reason", "Cannot advance")}

    next_tier = check["next_tier"]
    req = JOB_ADVANCEMENT[next_tier]

    # Apply stat bonuses (MapleStory gives permanent stat boosts on job advancement)
    main_attr = CLASS_MAIN_STAT.get(user.social_class, "stat_charisma")
    stat_bonus = req.get("stat_bonus", {})

    if "main" in stat_bonus:
        current = getattr(user, main_attr, 1) or 1
        setattr(user, main_attr, current + stat_bonus["main"])

    if "secondary" in stat_bonus:
        # Add to all non-main stats
        for attr in ["stat_charisma", "stat_empathy", "stat_consistency", "stat_initiative", "stat_wisdom"]:
            if attr != main_attr:
                current = getattr(user, attr, 1) or 1
                setattr(user, attr, current + stat_bonus["secondary"])
                break  # only highest secondary

    if "all" in stat_bonus:
        for attr in ["stat_charisma", "stat_empathy", "stat_consistency", "stat_initiative", "stat_wisdom"]:
            current = getattr(user, attr, 1) or 1
            setattr(user, attr, current + stat_bonus["all"])

    # HP bonus (MapleStory Warriors get +200-350 HP on job advancement)
    user.hp = min(HP_MAX, (user.hp or 0) + req.get("hp_bonus", 0))

    # SP bonus
    user.skill_points = (user.skill_points or 0) + req.get("sp_bonus", 0)

    # Update job tier
    user.job_tier = next_tier

    # Update title to job title
    class_key = user.social_class or "connector"
    titles = JOB_TITLES.get(class_key, JOB_TITLES["connector"])
    if next_tier < len(titles):
        user.title = titles[next_tier]

    db.commit()

    return {
        "new_tier": next_tier,
        "tier_name": req["name"],
        "title": user.title,
        "stat_bonuses": stat_bonus,
        "hp_bonus": req.get("hp_bonus", 0),
        "sp_bonus": req.get("sp_bonus", 0),
    }


def get_job_advancement_info(user: User, db: Session) -> dict:
    """Get full job advancement state for display."""
    current_tier = user.job_tier or 0
    class_key = user.social_class or ""
    titles = JOB_TITLES.get(class_key, ["Novice"] * 5)

    tiers = []
    for tier_num, req in JOB_ADVANCEMENT.items():
        tiers.append({
            "tier": tier_num,
            "name": req["name"],
            "title": titles[tier_num] if tier_num < len(titles) else "???",
            "level_req": req["level_req"],
            "stat_req": req.get("stat_req", 0),
            "quest_req": req.get("quest_req", ""),
            "completed": current_tier >= tier_num,
            "current": current_tier == tier_num,
        })

    check = check_job_advancement(user, db)

    return {
        "current_tier": current_tier,
        "current_title": titles[current_tier] if current_tier < len(titles) else "Master",
        "social_class": class_key,
        "tiers": tiers,
        "can_advance": check.get("can_advance", False),
        "advance_reason": check.get("reason", ""),
    }


# ══════════════════════════════════════════════
# PHASE 9: BUFF / DEBUFF TEMPORARY EFFECTS
# (MapleStory: skills grant temporary stat boosts with duration)
# ══════════════════════════════════════════════

BUFF_DEFINITIONS = {
    "social_surge": {
        "name": "Social Surge",
        "description": "+20% XP for all interactions",
        "duration_hours": 24,
        "effect": {"xp_mult": 1.2},
        "trigger": "party_complete",
        "icon": "zap",
    },
    "deep_focus": {
        "name": "Deep Focus",
        "description": "+30% relationship XP",
        "duration_hours": 12,
        "effect": {"relationship_xp_mult": 1.3},
        "trigger": "long_interaction",  # 30+ min interaction
        "icon": "brain",
    },
    "streak_fire": {
        "name": "Streak Fire",
        "description": "+15% global XP (7+ day streak)",
        "duration_hours": 48,
        "effect": {"xp_mult": 1.15},
        "trigger": "streak_7",
        "icon": "flame",
    },
    "boss_slayer": {
        "name": "Boss Slayer",
        "description": "+25% boss damage",
        "duration_hours": 24,
        "effect": {"boss_damage": 1.25},
        "trigger": "boss_clear",
        "icon": "sword",
    },
    "chain_momentum": {
        "name": "Chain Momentum",
        "description": "+10% XP, stacks per active chain step",
        "duration_hours": 72,
        "effect": {"xp_mult": 1.1},
        "trigger": "chain_step_complete",
        "icon": "link",
    },
    "circle_harmony": {
        "name": "Circle Harmony",
        "description": "+20% circle XP when all members contacted this week",
        "duration_hours": 168,  # 7 days
        "effect": {"circle_xp_mult": 1.2},
        "trigger": "circle_quest_complete",
        "icon": "sparkles",
    },
    "exhaustion": {
        "name": "Exhaustion",
        "description": "-50% XP (HP reached 0)",
        "duration_hours": 24,
        "effect": {"xp_mult": 0.5},
        "trigger": "hp_zero",
        "icon": "dizzy",
        "is_debuff": True,
    },
    "gate_rush": {
        "name": "Gate Rush",
        "description": "+30% gate clear speed",
        "duration_hours": 12,
        "effect": {"gate_speed": 1.3},
        "trigger": "gate_clear",
        "icon": "door",
    },
}


def apply_buff(user: User, buff_key: str, db: Session):
    """Apply a timed buff to user. Stored as JSON in user.active_buffs."""
    if buff_key not in BUFF_DEFINITIONS:
        return

    buff_def = BUFF_DEFINITIONS[buff_key]
    now = datetime.utcnow()
    expires = now + timedelta(hours=buff_def["duration_hours"])

    buffs = json.loads(user.active_buffs or "{}") if hasattr(user, 'active_buffs') and user.active_buffs else {}

    buffs[buff_key] = {
        "applied_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "name": buff_def["name"],
        "icon": buff_def["icon"],
        "is_debuff": buff_def.get("is_debuff", False),
    }

    if hasattr(user, 'active_buffs'):
        user.active_buffs = json.dumps(buffs)
    db.commit()


def get_active_buffs(user: User) -> list:
    """Get currently active (non-expired) buffs."""
    if not hasattr(user, 'active_buffs') or not user.active_buffs:
        return []

    buffs = json.loads(user.active_buffs or "{}")
    now = datetime.utcnow()
    active = []
    expired_keys = []

    for key, data in buffs.items():
        expires = datetime.fromisoformat(data["expires_at"])
        if now < expires:
            remaining_seconds = (expires - now).total_seconds()
            buff_def = BUFF_DEFINITIONS.get(key, {})
            active.append({
                "key": key,
                "name": data.get("name", key),
                "icon": data.get("icon", "star"),
                "is_debuff": data.get("is_debuff", False),
                "description": buff_def.get("description", ""),
                "remaining_hours": round(remaining_seconds / 3600, 1),
                "remaining_seconds": int(remaining_seconds),
            })
        else:
            expired_keys.append(key)

    # Clean up expired buffs
    if expired_keys:
        for k in expired_keys:
            del buffs[k]
        if hasattr(user, 'active_buffs'):
            user.active_buffs = json.dumps(buffs)

    return active


def get_active_buff_multiplier(user: User, effect_key: str) -> float:
    """Get combined multiplier from all active buffs for a given effect."""
    if not hasattr(user, 'active_buffs') or not user.active_buffs:
        return 1.0

    buffs = json.loads(user.active_buffs or "{}")
    now = datetime.utcnow()
    total_mult = 1.0

    for key, data in buffs.items():
        expires = datetime.fromisoformat(data["expires_at"])
        if now < expires:
            buff_def = BUFF_DEFINITIONS.get(key, {})
            effect = buff_def.get("effect", {})
            if effect_key in effect:
                total_mult *= effect[effect_key]

    return total_mult


def check_and_apply_buffs(user: User, trigger: str, db: Session):
    """Check if any buff should be applied based on trigger event."""
    for buff_key, buff_def in BUFF_DEFINITIONS.items():
        if buff_def["trigger"] == trigger:
            apply_buff(user, buff_key, db)


# ══════════════════════════════════════════════
# PHASE 10: SKILL PREREQUISITES
# (MapleStory: skills require previous skills at certain levels)
# ══════════════════════════════════════════════

SKILL_PREREQUISITES = {
    # Connector tree
    "speed_dial": {"requires": "social_butterfly", "min_level": 2},
    "first_impression": {"requires": "wide_net", "min_level": 1},
    "network_effect": {"requires": "speed_dial", "min_level": 1},
    "hub_master": {"requires": "first_impression", "min_level": 1},
    # Nurturer tree
    "emotional_intel": {"requires": "deep_roots", "min_level": 2},
    "inner_strength": {"requires": "healing_touch", "min_level": 2},
    "bond_master": {"requires": "emotional_intel", "min_level": 1},
    "soulmate": {"requires": "inner_strength", "min_level": 1},
    # Catalyst tree
    "challenge_master": {"requires": "party_leader", "min_level": 2},
    "event_horizon": {"requires": "rally_cry", "min_level": 2},
    "mob_mentality": {"requires": "challenge_master", "min_level": 1},
    "legendary_host": {"requires": "event_horizon", "min_level": 1},
    # Sage tree
    "discipline": {"requires": "iron_will", "min_level": 2},
    "time_mastery": {"requires": "meditation", "min_level": 2},
    "zen_master": {"requires": "discipline", "min_level": 1},
    "enlightened": {"requires": "time_mastery", "min_level": 1},
}

# Job tier requirements for skills (MapleStory: 2nd job skills need 2nd job, etc.)
SKILL_JOB_TIER_REQ = {
    # Tier 1 skills (1st job) - cost 1 SP
    "wide_net": 1, "social_butterfly": 1,
    "deep_roots": 1, "healing_touch": 1,
    "party_leader": 1, "rally_cry": 1,
    "iron_will": 1, "meditation": 1,
    # Tier 2 skills (2nd job) - cost 2 SP
    "speed_dial": 2, "first_impression": 2,
    "emotional_intel": 2, "inner_strength": 2,
    "challenge_master": 2, "event_horizon": 2,
    "discipline": 2, "time_mastery": 2,
    # Tier 3 skills (3rd job) - cost 3 SP
    "network_effect": 3, "hub_master": 3,
    "bond_master": 3, "soulmate": 3,
    "mob_mentality": 3, "legendary_host": 3,
    "zen_master": 3, "enlightened": 3,
}


def check_skill_prerequisites(user: User, skill_key: str, db: Session) -> dict:
    """Check if user meets prerequisites for a skill."""
    # Job tier check
    tier_req = SKILL_JOB_TIER_REQ.get(skill_key, 0)
    if (user.job_tier or 0) < tier_req:
        return {"met": False, "reason": f"Requires {JOB_ADVANCEMENT[tier_req]['name']} advancement"}

    # Prerequisite skill check
    prereq = SKILL_PREREQUISITES.get(skill_key)
    if prereq:
        req_skill = prereq["requires"]
        req_level = prereq["min_level"]
        existing = db.query(UserSkill).filter(
            UserSkill.user_id == user.id,
            UserSkill.skill_key == req_skill,
        ).first()
        current_level = existing.level if existing else 0
        if current_level < req_level:
            # Look up the display name
            cls = SOCIAL_CLASSES.get(user.social_class, {})
            skill_name = cls.get("skills", {}).get(req_skill, {}).get("name", req_skill)
            return {"met": False, "reason": f"Requires {skill_name} Lv{req_level} (have Lv{current_level})"}

    return {"met": True}


# ══════════════════════════════════════════════
# PHASE 11: CLASS-SPECIFIC LEVEL-UP BONUSES
# (MapleStory: Warriors gain +200-350 HP, Mages gain +450 MP per level)
# ══════════════════════════════════════════════

CLASS_LEVELUP_BONUSES = {
    "connector": {
        "main_stat_gain": 2,  # +2 Charisma per level
        "main_stat": "stat_charisma",
        "hp_gain": 3,         # small HP per level
        "description": "+2 CHA per level",
    },
    "nurturer": {
        "main_stat_gain": 2,  # +2 Empathy per level
        "main_stat": "stat_empathy",
        "hp_gain": 5,         # more HP (like Warriors)
        "description": "+2 EMP, +5 HP per level",
    },
    "catalyst": {
        "main_stat_gain": 2,  # +2 Initiative per level
        "main_stat": "stat_initiative",
        "hp_gain": 4,
        "description": "+2 INI per level",
    },
    "sage": {
        "main_stat_gain": 2,  # +2 Wisdom per level
        "main_stat": "stat_wisdom",
        "hp_gain": 2,         # least HP (like Mages)
        "int_gain": 1,        # +1 to ALL stats (wisdom of the sage)
        "description": "+2 WIS, +1 all stats per level",
    },
}


def apply_levelup_bonuses(user: User, levels_gained: int):
    """Apply class-specific stat gains on level up (MapleStory-style)."""
    class_key = user.social_class
    if not class_key or class_key not in CLASS_LEVELUP_BONUSES:
        return

    bonus = CLASS_LEVELUP_BONUSES[class_key]

    for _ in range(levels_gained):
        # Main stat gain
        main_attr = bonus["main_stat"]
        current = getattr(user, main_attr, 1) or 1
        setattr(user, main_attr, current + bonus["main_stat_gain"])

        # HP gain (MapleStory: Warriors +200-350 HP per level)
        hp_gain = bonus.get("hp_gain", 2)
        # HP gain also scales with consistency (like INT scaling MP in MapleStory)
        consistency_bonus = ((user.stat_consistency or 1) - 1) // 10
        user.hp = min(HP_MAX, (user.hp or 0) + hp_gain + consistency_bonus)

        # Sage special: +1 all stats (like maple mage INT bonus)
        if bonus.get("int_gain"):
            for attr in ["stat_charisma", "stat_empathy", "stat_consistency", "stat_initiative", "stat_wisdom"]:
                if attr != main_attr:
                    cur = getattr(user, attr, 1) or 1
                    setattr(user, attr, cur + bonus["int_gain"])


# ══════════════════════════════════════════════
# PHASE 12: CIRCLE / GUILD ECONOMY
# (MapleStory: Guild GP, ranks, capacity, emblem costs)
# ══════════════════════════════════════════════

CIRCLE_RANKS = ["Initiate", "Member", "Officer", "Captain", "Leader"]
CIRCLE_CAPACITY_BY_LEVEL = [5, 8, 12, 18, 25, 35, 50, 75]  # members per circle level
CIRCLE_GP_PER_INTERACTION = 5
CIRCLE_RANK_THRESHOLDS = [0, 50, 200, 500, 1000]  # GP needed for each rank

# GP costs for circle upgrades (like MapleStory guild costs)
CIRCLE_UPGRADE_COSTS = {
    "expand_capacity": 100,    # +5 members
    "create_quest": 50,        # create circle quest
    "change_emblem": 200,      # change circle icon
    "boost_xp": 500,           # temporary circle XP boost
}


def get_circle_details(circle, user: User, db: Session) -> dict:
    """Get detailed circle info with GP economy, ranks, capacity."""
    members = db.query(CircleMember).filter(CircleMember.circle_id == circle.id).all()
    member_count = len(members)

    level = circle.level or 1
    level_idx = min(level - 1, len(CIRCLE_CAPACITY_BY_LEVEL) - 1)
    capacity = CIRCLE_CAPACITY_BY_LEVEL[level_idx]

    gp = circle.xp_pool or 0  # GP = circle's XP pool

    # Calculate member ranks based on individual GP contributions
    member_details = []
    for mem in members:
        contact = db.query(Contact).filter(Contact.id == mem.contact_id).first()
        if contact:
            member_gp = contact.relationship_xp or 0
            rank_idx = 0
            for i, threshold in enumerate(CIRCLE_RANK_THRESHOLDS):
                if member_gp >= threshold:
                    rank_idx = i
            member_details.append({
                "contact_id": contact.id,
                "name": contact.name,
                "rank": CIRCLE_RANKS[min(rank_idx, len(CIRCLE_RANKS) - 1)],
                "rank_index": rank_idx,
                "gp": member_gp,
            })

    return {
        "id": circle.id,
        "name": circle.name,
        "level": level,
        "gp": gp,
        "next_level_gp": CIRCLE_LEVEL_THRESHOLDS[min(level, len(CIRCLE_LEVEL_THRESHOLDS) - 1)],
        "capacity": capacity,
        "member_count": member_count,
        "members": member_details,
        "can_add_members": member_count < capacity,
        "upgrade_costs": CIRCLE_UPGRADE_COSTS,
    }


# ══════════════════════════════════════════════
# ENHANCED DASHBOARD DATA
# ══════════════════════════════════════════════

def get_enhanced_dashboard(user: User, db: Session) -> dict:
    """Get full enhanced dashboard data including all new systems."""
    bonuses = get_stat_bonuses(user, db)
    buffs = get_active_buffs(user)
    job_info = get_job_advancement_info(user, db)
    skill_tree = get_skill_tree(user, db)

    # Add prerequisite info to skill tree
    for class_key, class_info in skill_tree["classes"].items():
        for skill_key, skill_info in class_info["skills"].items():
            prereq = SKILL_PREREQUISITES.get(skill_key)
            if prereq:
                skill_info["prerequisite"] = prereq
                prereq_check = check_skill_prerequisites(user, skill_key, db)
                skill_info["prereq_met"] = prereq_check["met"]
                skill_info["prereq_reason"] = prereq_check.get("reason", "")
            else:
                skill_info["prerequisite"] = None
                skill_info["prereq_met"] = True
                skill_info["prereq_reason"] = ""

            # Job tier requirement
            skill_info["job_tier_req"] = SKILL_JOB_TIER_REQ.get(skill_key, 0)

    return {
        "stat_bonuses": bonuses,
        "active_buffs": buffs,
        "job_advancement": job_info,
        "skill_tree": skill_tree,
        "damage_preview": _get_damage_preview(user),
    }


def _get_damage_preview(user: User) -> dict:
    """Show user their current damage range (like MapleStory stat window)."""
    class_key = user.social_class or "connector"
    weapon_mult = CLASS_WEAPON_MULT.get(class_key, 4.0)
    main_val, secondary_val = _get_main_secondary_stats(user)

    # Use average interaction ATK for preview
    avg_atk = 18
    raw_max = ((weapon_mult * main_val + secondary_val) / 100) * avg_atk
    job_tier = user.job_tier or 0
    mastery = 0.5 + job_tier * 0.1

    return {
        "min_damage": max(1, int(raw_max * mastery)),
        "max_damage": max(1, int(raw_max)),
        "main_stat": main_val,
        "secondary_stat": secondary_val,
        "weapon_mult": weapon_mult,
        "mastery": mastery,
        "class": class_key,
    }
