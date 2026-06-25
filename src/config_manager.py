import json
import os

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(_DATA_DIR, exist_ok=True)

CONFIG_FILE       = os.path.join(_DATA_DIR, "config.json")
USER_PREFS_FILE   = os.path.join(_DATA_DIR, "user_preferences.json")

WEB_SETTINGS_FILE = os.path.join(_DATA_DIR, "web_settings.json")

_DEFAULTS = {
    "groq_api_keys": [],
    "api_keys": [],  # [{key: str, provider: str}]
}

_WEB_DEFAULTS = {"theme": "dark"}

_USER_PREFS_DEFAULTS = {
    "selected_major":      "",   # single department id
    "selected_interests":  [],   # list of interest/hobby ids (multi-select)
    "custom_preferences":  [],   # list of {id, label, keywords} added by the user
    "user_name":           "",   # display name
    "user_gender":         "",   # "male" | "female" | "undisclosed"
    "gmail_account":       "",   # Gmail address used to initialise the connection
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


def get_api_keys() -> list[dict]:
    """Return list of saved API key entries [{key, provider}].
    Migrates old groq_api_keys format on first call if api_keys is empty."""
    cfg = load_config()
    entries = cfg.get("api_keys", [])
    entries = [e for e in entries if isinstance(e, dict) and e.get("key", "").strip()]
    if not entries:
        # One-time migration from old flat groq_api_keys list
        old = [k for k in cfg.get("groq_api_keys", []) if k.strip()]
        entries = [{"key": k, "provider": "groq"} for k in old]
    return entries


def save_api_keys(entries: list[dict]):
    """Save list of API key entries [{key, provider}]."""
    cfg = load_config()
    cfg["api_keys"] = [
        {"key": e["key"].strip(), "provider": e.get("provider", "groq")}
        for e in entries if e.get("key", "").strip()
    ]
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
        return
    # invalidate label cache so the next match_preferences call re-reads fresh data
    from src.preference_matcher import invalidate_label_cache
    invalidate_label_cache()


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


def get_user_name() -> str:
    return load_user_prefs().get("user_name", "")


def save_user_name(name: str):
    prefs = load_user_prefs()
    prefs["user_name"] = name
    save_user_prefs(prefs)


def get_user_gender() -> str:
    return load_user_prefs().get("user_gender", "")


def save_user_gender(gender: str):
    prefs = load_user_prefs()
    prefs["user_gender"] = gender
    save_user_prefs(prefs)


def load_web_settings() -> dict:
    if not os.path.exists(WEB_SETTINGS_FILE):
        return dict(_WEB_DEFAULTS)
    try:
        with open(WEB_SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in _WEB_DEFAULTS.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return dict(_WEB_DEFAULTS)


def save_web_settings(data: dict):
    try:
        with open(WEB_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[CONFIG] Failed to save web_settings: {e}")


def get_theme() -> str:
    return load_web_settings().get("theme", "dark")


def save_theme(theme: str):
    s = load_web_settings()
    s["theme"] = theme
    save_web_settings(s)


def get_gmail_account() -> str:
    return load_user_prefs().get("gmail_account", "")


def save_gmail_account(address: str):
    prefs = load_user_prefs()
    prefs["gmail_account"] = address
    save_user_prefs(prefs)


