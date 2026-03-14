"""Configuration management — stores API credentials in a local JSON file."""

import json
import os
import tempfile

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".isrc_fetcher")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "spotify_accounts": [],
    "source": "deezer",
    "openai_api_key": "",
    "columns": {},
}


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except (json.JSONDecodeError, OSError):
            # Corrupted config — fall back to defaults
            return dict(DEFAULT_CONFIG)
    return dict(DEFAULT_CONFIG)


def save_config(config: dict):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    # Atomic write: write to temp file first, then rename
    tmp_fd, tmp_path = tempfile.mkstemp(dir=CONFIG_DIR, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        os.replace(tmp_path, CONFIG_FILE)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
