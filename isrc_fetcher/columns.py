"""Excel column helpers for the ISRC spreadsheet schema."""


def letter_to_col(letter: str) -> int:
    """Convert column letter(s) to 1-based index. E.g. 'A'->1, 'B'->2, 'Z'->26, 'AA'->27."""
    letter = letter.strip().upper()
    result = 0
    for ch in letter:
        result = result * 26 + (ord(ch) - ord('A') + 1)
    return result


# Default column letters — overridden by config
DEFAULT_COLUMNS = {
    "duracion":         "B",   # Duration input
    "titulo":           "C",   # Track title input
    "interpretes":      "D",   # Artist(s) input
    "isrc":             "H",   # ISRC output
    "status":           "P",   # Status output
    "found_title":      "Q",   # Found title output
    "found_artist":     "R",   # Found artist output
    "found_duration":   "S",   # Found duration output
    "cleaned_title":    "T",   # AI-cleaned title
    "cleaned_artist":   "U",   # AI-cleaned artist
    # Validation-specific output columns
    "val_status":       "V",   # Validation status
    "val_found_title":  "W",   # Validation found title
    "val_found_artist": "X",   # Validation found artist
    "val_found_duration": "Y", # Validation found duration
}


def get_cols(cfg: dict) -> dict:
    """Return column index dict from config, falling back to defaults."""
    col_cfg = {**DEFAULT_COLUMNS, **cfg.get("columns", {})}
    return {k: letter_to_col(v) for k, v in col_cfg.items()}
