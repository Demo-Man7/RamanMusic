import asyncio
import re

import yt_dlp

import httpx
import spotipy
from bs4 import BeautifulSoup
from spotipy.oauth2 import SpotifyClientCredentials
from youtubesearchpython.future import VideosSearch

import config


SPOTIFY_WEB_HEADERS = {
    "Accept": "text/html,application/json",
    "User-Agent": "Mozilla/5.0",
}


class SpotifyAPI:
    def __init__(self):
        self.regex = r"^https:\/\/open\.spotify\.com\/.+"
        self.client_id = config.SPOTIFY_CLIENT_ID
        self.client_secret = config.SPOTIFY_CLIENT_SECRET
        self.og_title = re.compile(
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        self.og_desc = re.compile(
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
            re.IGNORECASE,
        )
        if self.client_id and self.client_secret:
            self.client_credentials_manager = SpotifyClientCredentials(
                self.client_id, self.client_secret
            )
            self.spotify = spotipy.Spotify(
                client_credentials_manager=self.client_credentials_manager
            )
        else:
            self.spotify = None

    def _resource_id(self, url: str, kind: str) -> str:
        match = re.search(rf"/{kind}/([A-Za-z0-9]+)", url or "")
        return match.group(1) if match else url

    async def _scrape_tracks(self, url: str, *, fallback_artist: str = ""):
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(25.0, connect=10.0),
            follow_redirects=True,
            trust_env=False,
            headers=SPOTIFY_WEB_HEADERS,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text

        soup = BeautifulSoup(html, "html.parser")
        if not fallback_artist:
            og_title = soup.find("meta", attrs={"property": "og:title"})
            fallback_artist = re.sub(
                r"\s*\|\s*Spotify\s*$",
                "",
                str((og_title or {}).get("content") or "").strip(),
                flags=re.IGNORECASE,
            )

        tracks: list[str] = []
        for row in soup.select('[data-testid="track-row"]'):
            title = row.get("aria-label") or ""
            title_node = row.select_one('[data-encore-id="listRowTitle"]')
            if title_node:
                title = title_node.get_text(" ", strip=True) or title
            title = re.sub(r"\s+", " ", title).strip()
            if not title:
                continue

            artists: list[str] = []
            details = row.select_one('[data-encore-id="listRowDetails"]')
            if details:
                for link in details.find_all("a"):
                    artist_name = re.sub(r"\s+", " ", link.get_text(" ", strip=True)).strip()
                    if artist_name and artist_name not in artists:
                        artists.append(artist_name)
            if not artists and fallback_artist and "/artist/" in url:
                artists.append(fallback_artist)

            query = f"{title} {' '.join(artists)}".strip()
            if query and query not in tracks:
                tracks.append(query)

        if not tracks:
            raise RuntimeError("Could not resolve Spotify public track list")
        return tracks

    async def valid(self, link: str) -> bool:
        return bool(re.search(self.regex, link or ""))

    async def track(self, link: str):
        info = ""
        if self.spotify:
            try:
                track = self.spotify.track(link)
                info = track["name"]
                for artist in track["artists"]:
                    fetched = f' {artist["name"]}'
                    if "Various Artists" not in fetched:
                        info += fetched
            except Exception:
                info = ""

        if not info:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, connect=10.0),
                follow_redirects=True,
                trust_env=False,
                headers=SPOTIFY_WEB_HEADERS,
            ) as client:
                try:
                    response = await client.get(
                        "https://open.spotify.com/oembed",
                        params={"url": link},
                    )
                    response.raise_for_status()
                    payload = response.json()
                    title = re.sub(
                        r"\s*\|\s*Spotify\s*$",
                        "",
                        str(payload.get("title") or "").strip(),
                        flags=re.IGNORECASE,
                    )
                    info = re.sub(r"\s+", " ", title).strip()
                except Exception:
                    response = await client.get(link)
                    response.raise_for_status()
                    html = response.text
                    title_match = self.og_title.search(html)
                    desc_match = self.og_desc.search(html)
                    if not title_match:
                        raise RuntimeError("Could not resolve Spotify track details")
                    title = re.sub(r"\s+", " ", title_match.group(1)).strip()
                    artist = ""
                    if desc_match:
                        desc = re.sub(r"\s+", " ", desc_match.group(1)).strip()
                        artist = desc.split("·", 1)[0].strip()
                    info = f"{title} {artist}".strip()

        if not info:
            raise RuntimeError("Could not resolve Spotify track details")

        # The search library can be rate-limited or return an empty response.
        # Fall back to yt-dlp search so Spotify tracks still resolve when possible.
        r = None
        try:
            data = await asyncio.wait_for(VideosSearch(info, limit=1).next(), timeout=8.0)
            results = (data or {}).get("result") or []
            if results:
                r = results[0]
        except Exception:
            r = None

        if r is None:
            def _search_ytdlp():
                opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                    "skip_download": True,
                    "socket_timeout": 8,
                    "retries": 1,
                    "extractor_retries": 1,
                }
                with yt_dlp.YoutubeDL(opts) as ydl:
                    search_info = ydl.extract_info(f"ytsearch1:{info}", download=False)
                    entries = (search_info or {}).get("entries") or []
                    return next((entry for entry in entries if entry), None)
            try:
                r = await asyncio.wait_for(asyncio.to_thread(_search_ytdlp), timeout=18.0)
            except Exception:
                r = None

        if not r:
            raise RuntimeError("Could not find a playable YouTube match for this Spotify track")

        vid = r.get("id") or ""
        title = r.get("title") or info
        link = r.get("webpage_url") or r.get("original_url") or (f"https://www.youtube.com/watch?v={vid}" if vid else "")
        thumbs = r.get("thumbnails") or []
        thumb = r.get("thumbnail") or ((thumbs[-1].get("url") if thumbs else ""))
        if not thumb and vid:
            thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        duration = int(r.get("duration") or 0)
        duration_min = f"{duration // 60}:{duration % 60:02d}" if duration else (r.get("duration_string") or "00:00")
        if not vid or not link:
            raise RuntimeError("YouTube search returned incomplete Spotify track details")
        track_details = {
            "title": title,
            "link": link,
            "vidid": vid,
            "duration_min": duration_min,
            "thumb": thumb.split("?")[0],
        }
        return track_details, vid

    async def playlist(self, url):
        playlist_id = self._resource_id(url, "playlist")
        if self.spotify:
            try:
                playlist = self.spotify.playlist(url)
                playlist_id = playlist["id"]
                results = []
                for item in playlist["tracks"]["items"]:
                    music_track = item["track"]
                    info = music_track["name"]
                    for artist in music_track["artists"]:
                        fetched = f' {artist["name"]}'
                        if "Various Artists" not in fetched:
                            info += fetched
                    results.append(info)
                if results:
                    return results, playlist_id
            except Exception:
                pass
        return await self._scrape_tracks(url), playlist_id

    async def album(self, url):
        album_id = self._resource_id(url, "album")
        if self.spotify:
            try:
                album = self.spotify.album(url)
                album_id = album["id"]
                results = []
                for item in album["tracks"]["items"]:
                    info = item["name"]
                    for artist in item["artists"]:
                        fetched = f' {artist["name"]}'
                        if "Various Artists" not in fetched:
                            info += fetched
                    results.append(info)
                if results:
                    return results, album_id
            except Exception:
                pass
        return await self._scrape_tracks(url), album_id

    async def artist(self, url):
        artist_id = self._resource_id(url, "artist")
        if self.spotify:
            try:
                artistinfo = self.spotify.artist(url)
                artist_id = artistinfo["id"]
                results = []
                artisttoptracks = self.spotify.artist_top_tracks(url)
                for item in artisttoptracks["tracks"]:
                    info = item["name"]
                    for artist in item["artists"]:
                        fetched = f' {artist["name"]}'
                        if "Various Artists" not in fetched:
                            info += fetched
                    results.append(info)
                if results:
                    return results, artist_id
            except Exception:
                pass
        return await self._scrape_tracks(url), artist_id
