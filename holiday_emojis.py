"""Simple fragment->emoji mapping for holidays.

This module uses a straightforward ordered list of substring fragments
mapped to emojis. The first matching fragment is used. Keep this file
simple so it's easy to extend with more fragments.
"""
from typing import Optional, List, Tuple

# Ordered list of (fragment, emoji). Fragments are checked in order.
FRAGMENTS: List[Tuple[str, str]] = [
    ("23 февр", "🪖"),
    ("23 февра", "🪖"),
    ("отечест", "🪖"),
    ("новый год", "🎉"),
    ("рождество", "🎄"),
    ("пасха", "✝️"),
    ("победа", "🎖️"),
    ("8 март", "🌷"),
    ("женский", "🌷"),
    ("валентин", "💘"),
    ("влюбл", "💘"),
    ("маслениц", "🥞"),
    ("труд", "🛠️"),
    ("мать", "🤱"),
    ("отец", "👨‍👧"),
    ("день рождения", "🎂"),
    ("юбилей", "🎂"),
    ("город", "🏙️"),
    ("флаг", "🏳️"),
    ("росси", "🇷🇺"),
    ("россия", "🇷🇺"),
    ("язык", "🗣️"),
    ("экскурс", "🧭"),
    ("фельдшер", "🩺"),
    ("полярн", "🐻‍❄️"),
    ("оптимист", "😄"),
]


def emoji_for_holiday(name: str) -> Optional[str]:
    """Return an emoji for a given holiday name by simple substring match."""
    if not name:
        return None
    low = name.lower()
    for frag, emoji in FRAGMENTS:
        if frag in low:
            return emoji
    return None


def decorate_holiday(name: str) -> str:
    """Prefix holiday name with an emoji when a fragment matches."""
    em = emoji_for_holiday(name) or "🎉"
    return f"{em} {name}"
