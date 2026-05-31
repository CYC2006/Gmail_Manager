import json
import os

from src.config_manager import get_selected_interests, get_selected_major
from src.categories import MATCHABLE

_OPTIONS_PATH = os.path.join(os.path.dirname(__file__), "settings", "preference_options.json")

_label_cache: list[str] | None = None


def invalidate_label_cache() -> None:
    """Clear the cached labels so the next call re-reads from disk.
    Call this after saving user preferences."""
    global _label_cache
    _label_cache = None


def _load_labels() -> list[str]:
    """Return the label strings of all currently selected preferences (major + interests).
    Result is cached for the lifetime of the process; call invalidate_label_cache() after
    preference changes."""
    global _label_cache
    if _label_cache is not None:
        return _label_cache

    try:
        with open(_OPTIONS_PATH, "r", encoding="utf-8") as f:
            opts = json.load(f)
    except Exception:
        return []

    selected_interests = set(get_selected_interests())
    selected_major     = get_selected_major()
    labels = []

    if selected_major:
        for m in opts.get("major", []):
            if m["id"] == selected_major:
                labels.append(m["label"])
                break

    for item in opts.get("interest", []):
        if item["id"] in selected_interests:
            labels.append(item["label"])

    _label_cache = labels
    return _label_cache


def match_preferences(subject: str, body: str, category: str) -> list[str]:
    """
    Check whether any selected preference labels appear in the email text.
    Only runs for 講座活動 and 一般宣導 categories.
    Returns a list of matched labels, or an empty list if no match or wrong category.
    """
    if not any(cat in category for cat in MATCHABLE):
        return []

    labels = _load_labels()
    if not labels:
        return []

    text = (subject + " " + body).lower()
    return [lbl for lbl in labels if lbl.lower() in text]
