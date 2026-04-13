import json
import os

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(_DATA_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(_DATA_DIR, "config.json")

_DEFAULTS = {
    "groq_api_keys": [],
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
