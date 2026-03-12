# ISRC Fetcher

Looks up ISRC codes for songs in your Excel file using Spotify + MusicBrainz.

---

## Windows — First-time setup

1. Double-click **`INSTALL.bat`** — downloads and installs Python if missing, installs packages, creates a Desktop shortcut.
2. Double-click **"ISRC Fetcher"** on your Desktop to start.

---

## Mac — First-time setup

1. Open **Terminal** and run:

   ```bash
   cd /path/to/app
   bash setup.sh
   ```

   This installs Python (via Homebrew if needed), packages, and creates a launcher on your Desktop.

2. Double-click **"Start ISRC Fetcher.command"** on your Desktop to start.

---

## How to use

1. The app opens in your browser automatically.
2. Enter your **Spotify Client ID and Secret** → click **Save Credentials**
   *(Get them free at [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) — create an app)*
3. Click **Browse** and pick your `.xlsx` file.
4. Click **Fetch ISRC Codes**.

**Output columns written:**

- **H** — ISRC code
- **P** — Match status (`Exact match` / `Duration mismatch` / `Not found`)
- **Q / R / S** — Found title, artist, duration from API (delete after verifying)

Rows that already have an ISRC in column H are skipped automatically.

---

## CLI (optional)

```bash
python3 -m isrc_fetcher.standalone "file.xlsx" --all
python3 -m isrc_fetcher.standalone "file.xlsx" --rows 2-50
python3 -m isrc_fetcher.standalone "file.xlsx" --all \
  --spotify-id YOUR_ID --spotify-secret YOUR_SECRET --save-credentials
```
