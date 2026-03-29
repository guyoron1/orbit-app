"""
AI Layer for Orbit — powered by Claude.

Provides:
  - Conversation starters based on relationship context
  - AI-powered relationship insights and summaries
"""

import os
from datetime import datetime
from typing import Optional

import anthropic

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def get_client():
    if not ANTHROPIC_API_KEY:
        return None
    return anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


def generate_conversation_starters(
    contact_name: str,
    relationship_type: str,
    notes: str,
    days_since_contact: float,
    last_interaction_type: Optional[str],
    health: float,
    recent_interactions_summary: str,
) -> list[str]:
    """Generate 3 personalized conversation starters for a contact."""
    client = get_client()
    if not client:
        return _fallback_starters(contact_name, relationship_type, days_since_contact)

    prompt = f"""You are a relationship coach helping someone reconnect with people they care about.

Generate exactly 3 short, natural conversation starters for reaching out to this person.
Each should be 1-2 sentences max. Be warm but not cheesy. Reference specific details when available.

Contact: {contact_name}
Relationship: {relationship_type}
Notes about them: {notes}
Days since last contact: {days_since_contact:.0f}
Last interaction type: {last_interaction_type or 'unknown'}
Relationship health: {health:.0f}%
Recent history: {recent_interactions_summary}

Rules:
- Be specific to this person, not generic
- Vary the tone: one casual, one thoughtful, one action-oriented
- If notes mention interests/events, reference them
- Keep it authentic — no corporate speak
- Return ONLY the 3 starters, one per line, no numbering or bullets"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        lines = [
            line.strip()
            for line in response.content[0].text.strip().split("\n")
            if line.strip()
        ]
        return lines[:3] if lines else _fallback_starters(contact_name, relationship_type, days_since_contact)
    except Exception:
        return _fallback_starters(contact_name, relationship_type, days_since_contact)


def generate_relationship_summary(
    contacts_data: list[dict],
    total_contacts: int,
    avg_health: float,
    interactions_this_week: int,
) -> str:
    """Generate an AI-powered weekly relationship summary."""
    client = get_client()
    if not client:
        return _fallback_summary(total_contacts, avg_health, interactions_this_week)

    declining = [c for c in contacts_data if c.get("trend") == "declining"]
    improving = [c for c in contacts_data if c.get("trend") == "improving"]

    declining_names = ", ".join(c["name"] for c in declining[:5])
    improving_names = ", ".join(c["name"] for c in improving[:5])

    prompt = f"""You are a relationship intelligence assistant. Give a brief, insightful weekly summary.

Stats:
- Total contacts: {total_contacts}
- Average relationship health: {avg_health:.0f}%
- Interactions this week: {interactions_this_week}
- Declining relationships: {declining_names or 'none'}
- Improving relationships: {improving_names or 'none'}

Write 2-3 sentences that are:
1. Specific and actionable (not vague praise)
2. Mention specific names if relationships need attention
3. Celebrate wins briefly
4. Suggest one concrete action for the week

Keep it under 60 words. Be direct, warm, and helpful."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception:
        return _fallback_summary(total_contacts, avg_health, interactions_this_week)


def _fallback_starters(name: str, rel_type: str, days: float) -> list[str]:
    """Deterministic fallback when Claude API is unavailable."""
    if days > 30:
        return [
            f"Hey {name}! It's been a while — how have you been?",
            f"Was just thinking about you, {name}. What's new in your world?",
            f"Long overdue catch-up? Would love to hear what you've been up to, {name}.",
        ]
    elif days > 14:
        return [
            f"Hey {name}, how's your week going?",
            f"Been meaning to reach out — anything exciting happening, {name}?",
            f"Want to grab coffee or hop on a call soon, {name}?",
        ]
    else:
        return [
            f"Hey {name}! Quick check-in — how are things?",
            f"Thinking of you, {name}. Hope all is well!",
            f"Any plans this weekend, {name}? Would be great to catch up.",
        ]


def _fallback_summary(total: int, health: float, interactions: int) -> str:
    if health >= 80:
        return f"Strong week! Your {total} relationships are averaging {health:.0f}% health with {interactions} interactions. Keep the momentum going."
    elif health >= 60:
        return f"Solid progress with {interactions} interactions this week. A few relationships could use attention to get your average above 80%."
    else:
        return f"Your network needs some love — average health is {health:.0f}%. Focus on 2-3 people this week to turn things around."
