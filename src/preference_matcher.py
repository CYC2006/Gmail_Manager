import json
import os

from src.config_manager import get_selected_interests, get_selected_major

_OPTIONS_PATH = os.path.join(os.path.dirname(__file__), "settings", "preference_options.json")

# only these categories are checked for keyword matches
_MATCHABLE_CATEGORIES = {"講座活動", "一般宣導"}


def _load_labels() -> list[str]:
    """Return the label strings of all currently selected preferences (major + interests)."""
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

    return labels


def match_preferences(subject: str, body: str, category: str) -> list[str]:
    """
    Check whether any selected preference labels appear in the email text.
    Only runs for 講座活動 and 一般宣導 categories.
    Returns a list of matched labels, or an empty list if no match or wrong category.
    """
    if not any(cat in category for cat in _MATCHABLE_CATEGORIES):
        return []

    labels = _load_labels()
    if not labels:
        return []

    text = (subject + " " + body).lower()
    return [lbl for lbl in labels if lbl.lower() in text]
