import json
import os
from pathlib import Path
from typing import Optional, Dict, Any

class I18nManager:
    """Manager for multi-language support."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(I18nManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self.current_language = "en"
        self.translations: Dict[str, Dict[str, str]] = {}
        self.locales_dir = Path(__file__).parent / "locales"
        self._initialized = True
        self._load_translations()

    def _load_translations(self):
        """Load all translation files from the locales directory."""
        if not self.locales_dir.exists():
            return

        for file_path in self.locales_dir.glob("*.json"):
            lang_code = file_path.stem
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.translations[lang_code] = json.load(f)
            except Exception as e:
                # Fallback to empty if loading fails
                self.translations[lang_code] = {}

    def set_language(self, lang_code: str):
        """Set the current language."""
        if lang_code in self.translations:
            self.current_language = lang_code
        else:
            # Fallback to English if language not found
            self.current_language = "en"

    def translate(self, key_path: str, **kwargs) -> str:
        """
        Translate a key to the current language.
        
        Args:
            key_path: The translation key (e.g., "cli.error_loading_config")
            **kwargs: Values for placeholder substitution
            
        Returns:
            Translated string or the key itself if not found
        """
        keys = key_path.split(".")
        val = self.translations.get(self.current_language, {})
        
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                # Fallback to English if not found in current language
                val = self.translations.get("en", {})
                for k2 in keys:
                    if isinstance(val, dict) and k2 in val:
                        val = val[k2]
                    else:
                        return key_path
                break
        
        if isinstance(val, str):
            try:
                return val.format(**kwargs)
            except KeyError:
                return val
        return key_path

# Global instance
i18n = I18nManager()

def _(key_path: str, **kwargs) -> str:
    """Alias for i18n.translate."""
    return i18n.translate(key_path, **kwargs)
