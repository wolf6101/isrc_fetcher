"""Browser UI — loads HTML from ui.html next to this file."""
import os

_here = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_here, "ui.html"), encoding="utf-8") as _f:
    HTML_PAGE = _f.read()
