"""ISRC Fetcher — local HTTP server + browser UI.

Run: python3 app.py
Opens http://localhost:8765 in your browser automatically.
Works on Mac and Windows — no extra dependencies beyond openpyxl + requests.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from isrc_fetcher.columns import (
    COL_DURACION, COL_TITULO_GRABACION, COL_INTERPRETES,
    COL_ISRC, COL_STATUS,
    COL_FOUND_TITLE, COL_FOUND_ARTIST, COL_FOUND_DURATION,
)
from isrc_fetcher.config import load_config, save_config
from isrc_fetcher.fetcher import ISRCFetcher
from isrc_fetcher.ui import HTML_PAGE

import openpyxl

# ---------------------------------------------------------------------------
# Job state (shared between HTTP handler and background worker thread)
# ---------------------------------------------------------------------------

job_state: dict = {
    "running": False,
    "cancel": False,
    "log": [],
    "progress": 0,
    "total": 0,
    "done": False,
    "found": 0,
    "not_found": 0,
    "warnings": 0,
    "skipped": 0,
    "current": "",
}


def _log(msg: str) -> None:
    job_state["log"].append(msg)


def _parse_duration(raw) -> int | None:
    if raw is None:
        return None
    m = re.match(r"^(\d{1,2}):(\d{2})$", str(raw).strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def run_fetch(file_path: str, row_start: int, row_end: int) -> None:
    job_state.update(
        running=True, cancel=False, log=[], progress=0, done=False,
        found=0, not_found=0, warnings=0, skipped=0, current="",
    )

    try:
        cfg = load_config()
        fetcher = ISRCFetcher(
            spotify_client_id=cfg.get("spotify_client_id"),
            spotify_client_secret=cfg.get("spotify_client_secret"),
        )
        if not cfg.get("spotify_client_id"):
            _log("Warning: No Spotify credentials. Using MusicBrainz only (slower).")

        wb = openpyxl.load_workbook(file_path)
        ws = wb.active

        # Write column headers on first run
        if ws.cell(row=1, column=COL_STATUS).value != "ISRC_STATUS":
            ws.cell(row=1, column=COL_STATUS).value         = "ISRC_STATUS"
            ws.cell(row=1, column=COL_FOUND_TITLE).value    = "ISRC_FOUND_TITLE"
            ws.cell(row=1, column=COL_FOUND_ARTIST).value   = "ISRC_FOUND_ARTIST"
            ws.cell(row=1, column=COL_FOUND_DURATION).value = "ISRC_FOUND_DURATION"

        actual_end = ws.max_row if row_end == -1 else min(row_end, ws.max_row)
        rows = list(range(row_start, actual_end + 1))
        job_state["total"] = len(rows)
        _log(f"Processing {len(rows)} rows from {os.path.basename(file_path)}...")

        found = not_found = warnings = skipped = 0

        for i, row in enumerate(rows, 1):
            if job_state["cancel"]:
                _log("Cancelled by user.")
                wb.save(file_path)
                _log("Partial results saved.")
                break

            title          = ws.cell(row=row, column=COL_TITULO_GRABACION).value
            artist         = ws.cell(row=row, column=COL_INTERPRETES).value
            duration_raw   = ws.cell(row=row, column=COL_DURACION).value
            existing_isrc  = ws.cell(row=row, column=COL_ISRC).value
            job_state["progress"] = i

            if not title or not artist:
                continue

            if existing_isrc and str(existing_isrc).strip():
                skipped += 1
                job_state["skipped"] = skipped
                _log(f"[{i}/{len(rows)}] [R{row}] {artist} - {title} -> SKIPPED (has ISRC: {existing_isrc})")
                continue

            title  = str(title).strip()
            artist = str(artist).strip()
            job_state["current"] = f"{artist} — {title}"
            result = fetcher.fetch(title, artist, _parse_duration(duration_raw))

            if result["isrc"]:
                ws.cell(row=row, column=COL_ISRC).value = result["isrc"]
                found += 1
                job_state["found"] = found

                if result["warning"]:
                    warnings += 1
                    job_state["warnings"] = warnings
                    ws.cell(row=row, column=COL_STATUS).value = "Duration mismatch"
                    _log(f"[{i}/{len(rows)}] [R{row}] {artist} - {title} -> {result['isrc']} (duration mismatch)")
                else:
                    ws.cell(row=row, column=COL_STATUS).value = "Exact match"
                    _log(f"[{i}/{len(rows)}] [R{row}] {artist} - {title} -> {result['isrc']}")

                matched = result.get("matched")
                if matched:
                    ws.cell(row=row, column=COL_FOUND_TITLE).value  = matched.get("name", "")
                    ws.cell(row=row, column=COL_FOUND_ARTIST).value = matched.get("artist", "")
                    dur_ms = matched.get("duration_ms")
                    if dur_ms:
                        ws.cell(row=row, column=COL_FOUND_DURATION).value = (
                            f"{dur_ms // 1000 // 60}:{dur_ms // 1000 % 60:02d}"
                        )
            else:
                not_found += 1
                job_state["not_found"] = not_found
                ws.cell(row=row, column=COL_STATUS).value = "Not found"
                _log(f"[{i}/{len(rows)}] [R{row}] {artist} - {title} -> NOT FOUND")

        else:
            wb.save(file_path)

        _log("")
        _log(f"Done! Found: {found} | Not found: {not_found} | Duration warnings: {warnings} | Skipped: {skipped}")
        _log(f"Results saved to {os.path.basename(file_path)}")

    except Exception as e:
        _log(f"ERROR: {e}")
    finally:
        job_state["running"] = False
        job_state["done"] = True


# ---------------------------------------------------------------------------
# Native file dialog
# ---------------------------------------------------------------------------

def _open_file_dialog() -> str | None:
    if sys.platform == "darwin":
        script = (
            'set theFile to choose file of type {"xlsx", "xls", "xlsm"} '
            'with prompt "Select Excel file"\n'
            'return POSIX path of theFile'
        )
        try:
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                return r.stdout.strip()
        except Exception:
            pass

    elif sys.platform == "win32":
        ps = (
            'Add-Type -AssemblyName System.Windows.Forms; '
            '$d = New-Object System.Windows.Forms.OpenFileDialog; '
            '$d.Filter = "Excel files (*.xlsx;*.xls;*.xlsm)|*.xlsx;*.xls;*.xlsm"; '
            '$d.Title = "Select Excel file"; '
            'if ($d.ShowDialog() -eq "OK") { $d.FileName }'
        )
        try:
            r = subprocess.run(["powershell", "-Command", ps], capture_output=True, text=True, timeout=120)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
        except Exception:
            pass

    return None


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress default request logging

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, content):
        body = content.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        if self.path == "/":
            self._html(HTML_PAGE)
        elif self.path == "/api/config":
            self._json(load_config())
        elif self.path == "/api/status":
            self._json({k: job_state[k] for k in (
                "running", "progress", "total", "log", "done",
                "found", "not_found", "warnings", "skipped", "current",
            )})
        else:
            self.send_error(404)

    def do_POST(self):
        body = self._body()

        if self.path == "/api/config":
            save_config(json.loads(body))
            self._json({"ok": True})

        elif self.path == "/api/fetch":
            if job_state["running"]:
                self._json({"error": "Already running"}, 409)
                return
            data = json.loads(body)
            threading.Thread(
                target=run_fetch,
                args=(data["file"], data.get("row_start", 2), data.get("row_end", -1)),
                daemon=True,
            ).start()
            self._json({"ok": True})

        elif self.path == "/api/cancel":
            job_state["cancel"] = True
            self._json({"ok": True})

        elif self.path == "/api/browse":
            self._json({"path": _open_file_dialog()})

        else:
            self.send_error(404)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    port = 8765
    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://localhost:{port}"
    print(f"ISRC Fetcher running at {url}")
    print("Press Ctrl+C to stop.\n")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
