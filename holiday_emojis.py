"""Fragment->emoji mapping for holidays backed by a JSON file.

On import this module attempts to load `holiday_emojis.json` located
next to the module. If the file is missing or invalid, a default
mapping is written to disk and used.
"""
from typing import Optional, List, Tuple, Any
from pathlib import Path
import json
import logging

LOG = logging.getLogger(__name__)

# Path to JSON file stored next to this module
_JSON_PATH = Path(__file__).parent / "holiday_emojis.json"

# Default fragments (kept in code so we can bootstrap the JSON file)
_DEFAULT_FRAGMENTS: List[Tuple[str, str]] = [
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
    ("язык", "🗣️"),
    ("экскурс", "🧭"),
    ("фельдшер", "🩺"),
    ("полярн", "🐻‍❄️"),
    ("оптимист", "😄"),
]


def _write_default_json(path: Path) -> None:
    try:
        data: List[Tuple[str, str]] = _DEFAULT_FRAGMENTS
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        LOG.info("Wrote default emoji fragments to %s", path)
    except OSError:
        LOG.exception("Failed to write default emoji JSON to %s", path)


def _load_fragments(path: Path) -> List[Tuple[str, str]]:
    if not path.exists():
        _write_default_json(path)
        return list(_DEFAULT_FRAGMENTS)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Expecting list of [frag, emoji] or list of objects; normalize both
        fragments: List[Tuple[str, str]] = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, list) and len(item) >= 2:
                    fragments.append((str(item[0]), str(item[1])))
                elif isinstance(item, dict) and "frag" in item and "emoji" in item:
                    fragments.append((str(item["frag"]), str(item["emoji"])))
        if not fragments:
            LOG.warning("Emoji JSON loaded but contains no valid fragments, using defaults")
            return list(_DEFAULT_FRAGMENTS)
        return fragments
    except Exception:
        LOG.exception("Failed to load emoji JSON from %s, using defaults", path)
        return list(_DEFAULT_FRAGMENTS)


# Public FRAGMENTS variable: ordered list of (fragment, emoji)
FRAGMENTS: List[Tuple[str, str]] = _load_fragments(_JSON_PATH)


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
