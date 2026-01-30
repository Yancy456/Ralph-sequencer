import yaml
import os
from pathlib import Path
from typing import Any, Dict

SETTINGS_FILE = Path.home() / ".ralph-sq-settings.yaml"

def load_settings() -> Dict[str, Any]:
    """Load settings from the persistent storage."""
    if not SETTINGS_FILE.exists():
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}

def save_settings(settings: Dict[str, Any]) -> None:
    """Save settings to the persistent storage."""
    try:
        # Load existing settings first to merge
        existing = load_settings()
        existing.update(settings)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            yaml.safe_dump(existing, f, default_flow_style=False, allow_unicode=True)
    except Exception:
        pass

def get_setting(key: str, default: Any = None) -> Any:
    """Get a specific setting value."""
    settings = load_settings()
    return settings.get(key, default)

def set_setting(key: str, value: Any) -> None:
    """Set a specific setting value."""
    save_settings({key: value})
