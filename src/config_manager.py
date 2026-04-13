import json
import os

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(_DATA_DIR, exist_ok=True)

CONFIG_FILE       = os.path.join(_DATA_DIR, "config.json")
USER_PREFS_FILE   = os.path.join(_DATA_DIR, "user_preferences.json")

_DEFAULTS = {
    "groq_api_keys": [],
}

_USER_PREFS_DEFAULTS = {
    "selected_major":      "",   # single department id
    "selected_interests":  [],   # list of interest/hobby ids (multi-select)
    "custom_preferences":  [],   # list of {id, label, keywords} added by the user
}


def load_config() -> dict:
    """Load config from disk, returning defaults for any missing keys."""
    if not os.path.exists(CONFIG_FILE):
        return dict(_DEFAULTS)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # fill in any missing keys with defaults
        for k, v in _DEFAULTS.items():
            data.setdefault(k, v)
        return data
    except Exception as e:
        print(f"[CONFIG] Failed to load config: {e}")
        return dict(_DEFAULTS)


def save_config(data: dict):
    """Persist config dict to disk."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[CONFIG] Failed to save config: {e}")


def get_groq_api_keys() -> list[str]:
    """Return list of saved Groq API keys (empty strings filtered out)."""
    return [k for k in load_config().get("groq_api_keys", []) if k.strip()]


def save_groq_api_keys(keys: list[str]):
    """Save list of Groq API keys."""
    cfg = load_config()
    cfg["groq_api_keys"] = [k.strip() for k in keys]
    save_config(cfg)


def load_user_prefs() -> dict:
    """Load user_preferences.json, returning defaults for missing keys."""
    if not os.path.exists(USER_PREFS_FILE):
        return dict(_USER_PREFS_DEFAULTS)
    try:
        with open(USER_PREFS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in _USER_PREFS_DEFAULTS.items():
            data.setdefault(k, v)
        return data
    except Exception as e:
        print(f"[CONFIG] Failed to load user_preferences: {e}")
        return dict(_USER_PREFS_DEFAULTS)


def save_user_prefs(data: dict):
    """Persist user_preferences.json to disk."""
    try:
        with open(USER_PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[CONFIG] Failed to save user_preferences: {e}")


def get_selected_major() -> str:
    return load_user_prefs().get("selected_major", "")


def save_selected_major(department_id: str):
    prefs = load_user_prefs()
    prefs["selected_major"] = department_id
    save_user_prefs(prefs)


def get_selected_interests() -> list[str]:
    return load_user_prefs().get("selected_interests", [])


def save_selected_interests(ids: list[str]):
    prefs = load_user_prefs()
    prefs["selected_interests"] = ids
    save_user_prefs(prefs)


def get_custom_preferences() -> list[dict]:
    return load_user_prefs().get("custom_preferences", [])


def save_custom_preferences(customs: list[dict]):
    prefs = load_user_prefs()
    prefs["custom_preferences"] = customs
    save_user_prefs(prefs)


