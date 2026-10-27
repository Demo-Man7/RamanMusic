"""Best-effort metadata resolver for public media links.

This does not bypass logins, paywalls, DRM, or private content. It only reads
public metadata from extractors supported by yt-dlp and returns a search phrase
for the bot's already-configured YouTube playback pipeline.
"""
import asyncio
import ipaddress
import re
import socket
import time
from urllib.parse import urlparse

import yt_dlp

_CACHE = {}
_CACHE_TTL = 300
_CACHE_LIMIT = 256
_DIRECT_MEDIA_EXTENSIONS = (
    ".m3u8", ".mpd", ".mp3", ".m4a", ".aac", ".ogg", ".opus",
    ".wav", ".flac", ".mp4", ".webm", ".mkv", ".mov",
)


def _extract_title(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith((".local", ".internal", ".localhost")):
        return None
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            return None
    except (OSError, ValueError):
        return None
    if parsed.path.lower().endswith(_DIRECT_MEDIA_EXTENSIONS):
        return None

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 4,
        "retries": 0,
        "extractor_retries": 0,
        "fragment_retries": 0,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not isinstance(info, dict):
            return None
        title = str(info.get("track") or info.get("title") or "").strip()
        artist = str(
            info.get("artist") or info.get("creator") or info.get("uploader") or ""
        ).strip()
        if not title or len(title) < 2:
            return None
        # Avoid searching for generic page labels rather than actual media.
        if title.lower() in {"video", "watch", "home", "untitled", ""}:
            return None
        if artist and artist.lower() not in title.lower():
            title = f"{artist} - {title}"
        title = re.sub(r"\s+", " ", title).strip()
        return title[:240] if title else None
    except Exception:
        return None


class UniversalAPI:
    async def search_query(self, url: str):
        """Return a title/artist search phrase for a supported public media URL."""
        url = str(url or "").strip()
        if not url.startswith(("http://", "https://")):
            return None
        now = time.monotonic()
        cached = _CACHE.get(url)
        if cached and cached[1] > now:
            return cached[0]
        result = await asyncio.wait_for(asyncio.to_thread(_extract_title, url), timeout=7)
        if result:
            if len(_CACHE) >= _CACHE_LIMIT:
                _CACHE.clear()
            _CACHE[url] = (result, now + _CACHE_TTL)
        return result
