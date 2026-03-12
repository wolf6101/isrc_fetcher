"""Shared Excel column indices (1-based) for the ISRC spreadsheet schema."""

COL_DURACION           = 2   # B — duration (M:SS)
COL_TITULO_GRABACION   = 3   # C — track title
COL_INTERPRETES        = 4   # D — artist(s)
COL_ISRC               = 8   # H — ISRC code (output)
COL_STATUS             = 16  # P — match status (Exact match / Duration mismatch / Not found)
COL_FOUND_TITLE        = 17  # Q — API-returned title  (verification; delete after review)
COL_FOUND_ARTIST       = 18  # R — API-returned artist (verification; delete after review)
COL_FOUND_DURATION     = 19  # S — API-returned duration (verification; delete after review)
