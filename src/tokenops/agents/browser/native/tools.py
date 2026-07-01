"""Browser backend + tools for the demo browser agent.

The backend is **pluggable** so the governance story is identical in tests and on stage:
  * ``HttpxBrowser`` — fetches pages from the local bench-site over HTTP (or a fetch fn in
    tests). Deterministic, offline, no heavy dependency. Default.
  * ``PlaywrightBrowser`` — drives a real headful Chromium for the live talk (optional; only
    imported if used).

A "snapshot" is the visible page text (stand-in for the accessibility tree) — that is what
gets fed to the model, so DOM size drives real token counts (compaction/caching deltas).
"""

from __future__ import annotations

import re
from typing import Callable, Protocol
from urllib.parse import urljoin


class BrowserBackend(Protocol):
    current_url: str

    def navigate(self, url: str) -> str: ...
    def snapshot(self) -> str: ...
    def click(self, element_id: str) -> str: ...   # returns the URL after the click
    def extract(self, element_id: str) -> str: ...


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")


def _visible_text(html: str) -> str:
    """Strip tags → visible text (the model's view of the page)."""
    text = _TAG.sub(" ", html)
    text = _WS.sub(" ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _find_by_id(html: str, element_id: str) -> str:
    """Return the raw <tag ...> that carries id="element_id" (first match)."""
    m = re.search(rf'<[^>]*\bid="{re.escape(element_id)}"[^>]*>', html)
    return m.group(0) if m else ""


def _href_of(tag: str) -> str | None:
    m = re.search(r'href="([^"]+)"', tag)
    return m.group(1) if m else None


def _text_after_id(html: str, element_id: str) -> str:
    m = re.search(rf'<[^>]*\bid="{re.escape(element_id)}"[^>]*>([^<]*)<', html)
    return (m.group(1).strip() if m else "")


class HttpxBrowser:
    """Fetches local bench-site pages. ``fetch(path) -> html`` is injectable (tests pass a
    TestClient-backed fetch; production defaults to an httpx GET)."""

    def __init__(self, base_url: str = "http://127.0.0.1:8090",
                 fetch: Callable[[str], str] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.current_url = self.base_url + "/"
        self._html = ""
        self._fetch = fetch or self._http_fetch

    def _http_fetch(self, path: str) -> str:
        import httpx
        return httpx.get(self.base_url + path, timeout=10.0).text

    def _path(self, url: str) -> str:
        full = urljoin(self.current_url, url)
        return full[len(self.base_url):] if full.startswith(self.base_url) else url

    def navigate(self, url: str) -> str:
        path = self._path(url) or "/"
        self._html = self._fetch(path)
        self.current_url = self.base_url + path
        return self.current_url

    def snapshot(self) -> str:
        if not self._html:
            self.navigate("/")
        return _visible_text(self._html)

    def click(self, element_id: str) -> str:
        href = _href_of(_find_by_id(self._html, element_id))
        if href and href != "#":
            return self.navigate(href)
        return self.current_url  # non-navigating click (e.g. a button)

    def extract(self, element_id: str) -> str:
        return _text_after_id(self._html, element_id)
