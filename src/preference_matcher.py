import json
import os

from src.config_manager import get_selected_interests
from src.categories import MATCHABLE

_OPTIONS_PATH = os.path.join(os.path.dirname(__file__), "settings", "preference_options.json")

_interest_cache: list[dict] | None = None


def invalidate_label_cache() -> None:
    """Clear the cached interests so the next call re-reads from disk."""
    global _interest_cache
    _interest_cache = None


def _load_interests() -> list[dict]:
    """Return [{id, label, keywords}] for all currently selected interests.
    Cached for the lifetime of the process; call invalidate_label_cache() after saves."""
    global _interest_cache
    if _interest_cache is not None:
        return _interest_cache

    try:
        with open(_OPTIONS_PATH, "r", encoding="utf-8") as f:
            opts = json.load(f)
    except Exception:
        return []

    selected = set(get_selected_interests())
    result = []
    for cat in opts.get("categories", []):
        for item in cat.get("interests", []):
            if item["id"] in selected:
                result.append({
                    "id":       item["id"],
                    "label":    item["label"],
                    "keywords": item.get("keywords", []),
                })

    _interest_cache = result
    return result


def match_preferences(subject: str, body: str, category: str) -> list[str]:
    """
    Check whether any selected interest keywords appear in the email text.
    Only runs for 講座活動 and 一般宣導 categories.
    Returns a list of matched interest labels, or [] if no match or wrong category.
    """
    if not any(cat in category for cat in MATCHABLE):
        return []

    interests = _load_interests()
    if not interests:
        return []

    text = (subject + " " + body).lower()
    matched = []
    for interest in interests:
        terms = [interest["label"]] + interest["keywords"]
        if any(term.lower() in text for term in terms):
            matched.append(interest["label"])
    return matched
