import config
"""
YouTube.py — Compact YouTube platform for AloneMusic
Original: TheAloneTeam/AloneMusic (GNU v3.0)
"""

import asyncio, os, re, json, time, logging, random
import urllib.parse
from typing import Union

import httpx
import yt_dlp

# Keep API logging compatible with the rest of this module.
LOGGER = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────
# Configure the audio-download API in Heroku Config Vars. Keep the existing
# Ritesh endpoint as the default, but allow deployments to override it safely.
API_URL = os.getenv("YOUTUBE_AUDIO_API_URL", os.getenv("API_URL", os.getenv("RITESH_API_URL", "https://web.riteshyt.in"))).rstrip("/")
API_KEY = os.getenv("YOUTUBE_AUDIO_API_KEY", os.getenv("API_KEY", "riteshfree15605c22c26533fa5833d0fe"))

# ── Dynamic imports with graceful fallbacks ───────────────────
try:
    from pyrogram.enums import MessageEntityType
    from pyrogram.types import Message
except ImportError:
    class MessageEntityType: URL = "url"; TEXT_LINK = "text_link"
    class Message: pass

try:
    from youtubesearchpython.__future__ import VideosSearch, Playlist
except ImportError:
    VideosSearch = None; Playlist = None

try:
    from AloneMusic.utils.database import is_on_off
except ImportError:
    async def is_on_off(*a, **k): return True

try:
    from AloneMusic.utils.formatters import time_to_seconds
except ImportError:
    def time_to_seconds(s):
        if not s: return 0
        try:
            p = list(map(int, s.split(":")))
            return (p[0] * 3600 + p[1] * 60 + p[2]) if len(p) == 3 \
                else (p[0] * 60 + p[1]) if len(p) == 2 else p[0]
        except Exception: return 0


# ── Utility helpers ───────────────────────────────────────────
def extract_vidid(q):
    if not q: return None
    if re.match(r"^[a-zA-Z0-9_-]{11}$", q): return q
    m = re.search(r'(?:youtube\.com/(?:[^/]+/.+/|(?:v|e(?:mbed)?)\/|shorts\/|.*[?&]v=)|youtu\.be\/)([^\ "&?/\s]{11})', q)
    return m.group(1) if m else None


async def check_file_size(link):
    def _parse(f): return sum(x.get("filesize", 0) for x in f) if f else 0
    async def _info():
        p = await asyncio.create_subprocess_exec("yt-dlp", "-J", link,
              stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await p.communicate()
        if p.returncode != 0:
            print(f"Error:\n{err.decode()}"); return None
        return json.loads(out.decode())
    info = await _info()
    if not info: return None
    f = info.get("formats", [])
    return _parse(f) if f else None


async def download_assistant(query, dl_type):
    safe, ext = urllib.parse.quote(query), "mp3" if dl_type == "audio" else "mp4"
    if API_KEY:
        return f"{API_URL}/downloads/{API_KEY}/{safe}.{ext}"
    return f"{API_URL}/downloads/stream?query={safe}&dl_type={dl_type}"


# ── YouTubeAPI ────────────────────────────────────────────────
class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.listbase = "https://youtube.com/playlist?list="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        self._client = None
        self._recent_prefetches = {}

    async def get_client(self):
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=3.0), follow_redirects=True, limits=httpx.Limits(max_connections=20, max_keepalive_connections=10))
        return self._client

    async def exists(self, link, videoid: Union[bool, str] = None):
        if videoid: link = self.base + link
        return bool(re.search(self.regex, link))

    async def url(self, message_1):
        """Return a YouTube URL from command text, captions, or a replied message.

        Telegram does not always populate URL entities consistently (especially for
        captions and copied links), so fall back to scanning the actual text.
        """
        msgs = [message_1]
        replied = getattr(message_1, "reply_to_message", None)
        if replied is not None:
            msgs.append(replied)

        url_pattern = re.compile(
            r"https?://(?:www\.|m\.|music\.)?(?:youtube\.com/(?:watch\?[^\s<>]+|shorts/[^\s<>]+|live/[^\s<>]+|embed/[^\s<>]+|playlist\?[^\s<>]+)|youtu\.be/[^\s<>]+)",
            re.IGNORECASE,
        )
        for m in msgs:
            text_value = getattr(m, "text", None) or getattr(m, "caption", None) or ""
            entities = list(getattr(m, "entities", None) or [])
            entities += list(getattr(m, "caption_entities", None) or [])
            for e in entities:
                try:
                    entity_type = str(getattr(e, "type", "")).lower()
                    if "text_link" in entity_type:
                        candidate = getattr(e, "url", None)
                    elif "url" in entity_type:
                        candidate = text_value[e.offset:e.offset + e.length]
                    else:
                        continue
                    if candidate and re.search(r"(?:youtube\.com|youtu\.be)", candidate, re.I):
                        return candidate.rstrip(".,!?)\]}")
                except Exception:
                    continue
            match = url_pattern.search(text_value)
            if match:
                return match.group(0).rstrip(".,!?)\]}")
        return None

    def _clean_link(self, link):
        """Normalize YouTube URLs without breaking playlist links."""
        if not link:
            return ""
        link = str(link).strip().strip("<>()[]{}.,!\"' ")
        # Keep playlist IDs intact; only remove common tracking parameters.
        if "list=" in link:
            try:
                parsed = urllib.parse.urlsplit(link)
                query = urllib.parse.parse_qs(parsed.query)
                keep = {}
                for key in ("v", "list", "index", "start_radio"):
                    if key in query:
                        keep[key] = query[key]
                return urllib.parse.urlunsplit((
                    parsed.scheme or "https", parsed.netloc or "www.youtube.com",
                    parsed.path, urllib.parse.urlencode(keep, doseq=True), ""
                ))
            except Exception:
                return link.split("&si=")[0].split("?si=")[0]
        try:
            parsed = urllib.parse.urlsplit(link)
            query = urllib.parse.parse_qs(parsed.query)
            if "v" in query:
                return f"https://www.youtube.com/watch?v={query['v'][0]}"
            vid = extract_vidid(link)
            if vid:
                return f"https://www.youtube.com/watch?v={vid}"
        except Exception:
            pass
        return link.split("&si=")[0].split("?si=")[0]

    async def _fetch_details(self, link):
        """Fetch track metadata with a short retry for transient API/network failures."""
        link = self._clean_link(link)
        if not API_URL:
            return None
        params = {"link": link}
        if API_KEY:
            params["api_key"] = API_KEY
        for attempt in range(2):
            try:
                r = await (await self.get_client()).get(
                    f"{API_URL.rstrip('/')}/details",
                    params=params,
                    timeout=httpx.Timeout(8.0, connect=3.0),
                )
                if r.status_code == 200:
                    data = r.json()
                    if isinstance(data, dict) and data.get("title"):
                        return data
                logging.warning("YouTube details API returned HTTP %s (attempt %s)", r.status_code, attempt + 1)
            except Exception as e:
                logging.warning("YouTube details API failed (attempt %s): %s", attempt + 1, e)
            if attempt == 0:
                await asyncio.sleep(0.25)
        return None

    async def _search_ytdlp(self, query):
        """Fallback search when the configured metadata API temporarily fails."""
        query = str(query or "").strip()
        if not query or re.match(r"https?://", query, re.I):
            return None
        def _search():
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "extract_flat": True,
                "socket_timeout": 6,
                "playlistend": 1,
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                data = ydl.extract_info("ytsearch1:" + query, download=False)
                entries = (data or {}).get("entries") or []
                return entries[0] if entries else None
        try:
            entry = await asyncio.get_running_loop().run_in_executor(None, _search)
            if not isinstance(entry, dict) or not entry.get("id"):
                return None
            vid = entry["id"]
            duration = entry.get("duration") or 0
            try:
                duration = int(duration)
            except (TypeError, ValueError):
                duration = 0
            mins = f"{duration // 60}:{duration % 60:02d}" if duration else "0:00"
            return {
                "title": entry.get("title") or query,
                "link": f"https://www.youtube.com/watch?v={vid}",
                "vidid": vid,
                "duration_min": mins,
                "duration_sec": duration,
                "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            }
        except Exception as e:
            logging.warning("yt-dlp search fallback failed: %s", e)
            return None

    async def details(self, link, videoid=None):
        if videoid:
            link = self.base + link
        link = self._clean_link(link)
        vid = extract_vidid(link)
        if API_URL:
            d = await self._fetch_details(link)
            if isinstance(d, dict) and d.get("title"):
                return (d.get("title"), d.get("duration_min") or "0:00", d.get("duration_sec", 0),
                        d.get("thumbnail") or (f"https://i.ytimg.com/vi/{d.get('vidid') or vid}/hqdefault.jpg" if (d.get('vidid') or vid) else None), d.get("vidid") or vid)
        if vid:
            info = await self._extract_metadata(link)
            if info:
                return info["title"], info["duration_min"], info["duration_sec"], info["thumb"], info["vidid"]
        if VideosSearch:
            try:
                res = await VideosSearch(link, limit=1).next()
                if res and res.get("result"):
                    x = res["result"][0]
                    dur = x.get("duration")
                    return x.get("title"), dur or "0:00", int(time_to_seconds(dur)) if dur not in (None, "None") else 0, (x.get("thumbnails") or [{}])[0].get("url", "").split("?")[0], x.get("id")
            except Exception as e:
                logging.warning(f"Local VideosSearch fallback failed in details: {e}")
        return None, None, 0, None, None

    async def title(self, link, videoid=None):
        if videoid: link = self.base + link
        link = self._clean_link(link)
        if API_URL:
            d = await self._fetch_details(link)
            if d and d.get("title"): return d["title"]
        if VideosSearch:
            try:
                res = await (VideosSearch(link, limit=1)).next()
                if res and res.get("result"): return res["result"][0]["title"]
            except Exception as e: logging.warning(f"Local VideosSearch fallback failed in title: {e}")
        return None

    async def duration(self, link, videoid=None):
        if videoid: link = self.base + link
        link = self._clean_link(link)
        if API_URL:
            d = await self._fetch_details(link)
            if d and d.get("duration_min"): return d["duration_min"]
        if VideosSearch:
            try:
                res = await (VideosSearch(link, limit=1)).next()
                if res and res.get("result"): return res["result"][0]["duration"]
            except Exception as e: logging.warning(f"Local VideosSearch fallback failed in duration: {e}")
        return None

    async def thumbnail(self, link, videoid=None):
        if videoid: link = self.base + link
        link = self._clean_link(link)
        if API_URL:
            d = await self._fetch_details(link)
            if d and d.get("thumbnail"): return d["thumbnail"]
        if VideosSearch:
            try:
                res = await (VideosSearch(link, limit=1)).next()
                if res and res.get("result"): return res["result"][0]["thumbnails"][0]["url"].split("?")[0]
            except Exception as e: logging.warning(f"Local VideosSearch fallback failed in thumbnail: {e}")
        return None

    async def video(self, link, videoid=None):
        if videoid: link = self.base + link
        link = self._clean_link(link)
        try:
            res = await self.download(link, None, video=True)
            if res and isinstance(res, tuple) and res[0]: return 1, res[0]
        except Exception as e: logging.warning(f"Downloading API video locally failed: {e}")
        try:
            p = await asyncio.create_subprocess_exec("yt-dlp", "-g", "-f", "best[height<=?720][width<=?1280]", link,
                  stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await p.communicate()
            return (1, out.decode().split("\n")[0]) if out else (0, err.decode())
        except Exception as e: return 0, str(e)

    async def playlist(self, link, limit, user_id, videoid=None):
        if videoid: link = self.listbase + link
        link = self._clean_link(link)
        params = {"link": link, "limit": limit}
        if API_KEY: params["api_key"] = API_KEY
        try:
            r = await (await self.get_client()).get(f"{API_URL}/playlist", params=params)
            if r.status_code == 200: return r.json().get("videos")
            LOGGER(__name__).error(f"API Playlist Error ({r.status_code}): {r.text}")
        except Exception as e: LOGGER(__name__).error(f"Error fetching playlist from API: {e}")
        return None

    async def get_related_videos(self, vidid: str):
        # Limit autoplay tracks to 10 minutes (600 seconds)
        autoplay_limit = min(config.DURATION_LIMIT, 600)

        # Priority 1: Using YouTube Radio Mix (RD Mix) for best relevance
        url = f"https://www.youtube.com/watch?v={vidid}&list=RD{vidid}"
        ydl_opts = {
            "quiet": True,
            "extract_flat": "in_playlist",
            "playlist_items": "2-20",
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                loop = asyncio.get_event_loop()
                info = await loop.run_in_executor(
                    None, lambda: ydl.extract_info(url, download=False)
                )
                if "entries" in info:
                    ids = []
                    for e in info["entries"]:
                        if not e.get("id") or e["id"] == vidid:
                            continue

                        duration = e.get("duration")
                        if duration and duration > autoplay_limit:
                            continue

                        ids.append(e["id"])

                    if ids:
                        return ids
        except:
            pass

        # Priority 2: Search by title for relevance
        title = await self.title(vidid, True)
        if title:
            try:
                results = VideosSearch(f"{title} related songs", limit=10)
                related = []
                for result in (await results.next())["result"]:
                    duration_str = result.get("duration")
                    if duration_str:
                        try:
                            seconds = time_to_seconds(duration_str)
                            if seconds > autoplay_limit:
                                continue
                        except:
                            pass

                    if result["id"] != vidid:
                        related.append(result["id"])
                if related:
                    return related
            except:
                pass

        # Final Fallback: Broad search but still filtering duration
        categories = [
            "Latest Hindi Songs",
            "Top Bollywood Hits",
            "Indian Pop Songs",
            "New English Songs",
            "Trending Music India",
        ]
        try:
            query = random.choice(categories)
            results = VideosSearch(query, limit=20)
            related = []
            for result in (await results.next())["result"]:
                duration_str = result.get("duration")
                if duration_str:
                    try:
                        seconds = time_to_seconds(duration_str)
                        if seconds > autoplay_limit:
                            continue
                    except:
                        pass

                if result["id"] != vidid:
                    related.append(result["id"])
            if related:
                return related
        except:
            pass

        return []
    async def _extract_metadata(self, link):
        """Metadata fallback that does not invoke yt-dlp or VideosSearch.

        YouTube may block datacenter IPs with a bot-check. oEmbed can provide a
        title for publicly embeddable videos without attempting stream extraction.
        Audio itself must come from the configured audio API.
        """
        link = self._clean_link(link)
        vid = extract_vidid(link)
        if not vid:
            return None
        try:
            client = await self.get_client()
            r = await client.get(
                "https://www.youtube.com/oembed",
                params={"url": f"https://www.youtube.com/watch?v={vid}", "format": "json"},
                timeout=httpx.Timeout(8.0, connect=3.0),
                headers={"User-Agent": "Mozilla/5.0"},
            )
            if r.status_code == 200:
                data = r.json()
                title = data.get("title")
                if title:
                    thumb = data.get("thumbnail_url") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                    return {"title": title, "link": f"https://www.youtube.com/watch?v={vid}",
                            "vidid": vid, "duration_min": "0:00", "duration_sec": 0,
                            "thumb": thumb, "thumbnail": thumb}
        except Exception as e:
            logging.warning("YouTube oEmbed metadata fallback failed for %s: %s", vid, e)
        return None

    async def track(self, link, videoid=None):
        if videoid:
            link = self.base + link
        link = self._clean_link(link)
        vid = extract_vidid(link)
        # For a direct video URL, extract that exact video; do not search the URL as text.
        if vid:
            if API_URL:
                d = await self._fetch_details(link)
                if isinstance(d, dict) and d.get("title"):
                    out_id = d.get("vidid") or vid
                    return ({"title": d.get("title"), "link": d.get("link") or f"https://www.youtube.com/watch?v={out_id}",
                             "vidid": out_id, "duration_min": d.get("duration_min") or "0:00",
                             "thumb": d.get("thumbnail") or f"https://i.ytimg.com/vi/{out_id}/hqdefault.jpg"}, out_id)
            info = await self._extract_metadata(link)
            if info:
                return ({"title": info["title"], "link": info["link"], "vidid": info["vidid"],
                         "duration_min": info["duration_min"], "thumb": info["thumb"]}, info["vidid"])
        # Search queries (not direct URLs) still use the configured API/search library.
        if API_URL:
            d = await self._fetch_details(link)
            if isinstance(d, dict) and d.get("title"):
                out_id = d.get("vidid")
                return ({"title": d.get("title"), "link": d.get("link") or (f"https://www.youtube.com/watch?v={out_id}" if out_id else link),
                         "vidid": out_id, "duration_min": d.get("duration_min") or "0:00",
                         "thumb": d.get("thumbnail") or (f"https://i.ytimg.com/vi/{out_id}/hqdefault.jpg" if out_id else None)}, out_id)
        # Fallback for temporary API failures. This runs off the event loop and
        # only searches metadata; actual audio retrieval remains in download().
        fallback = await self._search_ytdlp(link)
        if fallback:
            return ({"title": fallback["title"], "link": fallback["link"],
                     "vidid": fallback["vidid"], "duration_min": fallback["duration_min"],
                     "thumb": fallback["thumb"]}, fallback["vidid"])
        # Do not use VideosSearch here: some installed versions pass the removed
        # httpx `proxies=` argument and fail before returning any results.
        return None, None

    async def formats(self, link, videoid=None):
        if videoid: link = self.base + link
        link = self._clean_link(link)
        if API_URL:
            params = {"link": link}
            if API_KEY: params["api_key"] = API_KEY
            try:
                r = await (await self.get_client()).get(f"{API_URL}/formats", params=params)
                if r.status_code == 200:
                    f = r.json().get("formats", [])
                    for x in f: x["yturl"] = link
                    return f, link
            except Exception as e: logging.warning(f"Error fetching formats from API: {e}")
        def _extract():
            with yt_dlp.YoutubeDL({"quiet": True}) as y: return y.extract_info(link, download=False)
        try:
            r = await asyncio.to_thread(_extract)
            out = []
            for f in r.get("formats", []):
                try:
                    if "dash" not in str(f.get("format", "")).lower():
                        out.append({"format": f.get("format"), "filesize": f.get("filesize"), "format_id": f.get("format_id"),
                                    "ext": f.get("ext"), "format_note": f.get("format_note"), "yturl": link})
                except Exception: continue
            return out, link
        except Exception as e: logging.warning(f"Formats extraction failed: {e}"); return [], link

    async def slider(self, link, query_type, videoid=None):
        if videoid: link = self.base + link
        link = self._clean_link(link)
        if API_URL:
            params = {"query": link, "limit": 10}
            if API_KEY: params["api_key"] = API_KEY
            try:
                r = await (await self.get_client()).get(f"{API_URL}/search", params=params)
                if r.status_code == 200:
                    result = r.json().get("result", [])
                    if result and len(result) > query_type:
                        t = result[query_type]
                        return t["title"], t["duration"], t["thumbnails"][0]["url"].split("?")[0] if t.get("thumbnails") else None, t["id"]
            except Exception as e: logging.warning(f"Error in slider/search from API: {e}")
        if VideosSearch:
            try:
                res = await (VideosSearch(link, limit=10)).next()
                result = res.get("result")
                if result and len(result) > query_type:
                    t = result[query_type]
                    return t["title"], t["duration"], t["thumbnails"][0]["url"].split("?")[0], t["id"]
            except Exception as e: logging.warning(f"Local slider fallback failed: {e}")
        return None, None, None, None

    async def prefetch(self, link, video=False):
        if not API_URL: return False
        dl_type = "video" if video else "audio"
        link = self._clean_link(link)
        now = time.time()
        vidid = extract_vidid(link) or link
        ck = f"{vidid}_{dl_type}"
        if ck in self._recent_prefetches and now - self._recent_prefetches[ck] < 30: return True
        self._recent_prefetches[ck] = now
        if len(self._recent_prefetches) > 100:
            self._recent_prefetches = {k: v for k, v in self._recent_prefetches.items() if now - v < 300}
        params = {"query": link, "dl_type": dl_type, "prefetch": "true"}
        if API_KEY: params["api_key"] = API_KEY
        try:
            await (await self.get_client()).get(f"{API_URL}/download", params=params)
            return True
        except Exception as e: logging.warning(f"Prefetch failed for {link}: {e}")
        return False

    async def prefetch_queue(self, queries, video=False):
        if not API_URL or not queries: return False
        params = {}
        if API_KEY: params["api_key"] = API_KEY
        try:
            await (await self.get_client()).post(f"{API_URL}/prefetch_bulk",
                  json={"queries": queries, "dl_type": "video" if video else "audio"}, params=params)
            return True
        except Exception as e: logging.warning(f"Bulk prefetch failed: {e}")
        return False

    async def download(self, link, mystic, video=None, videoid=None, songaudio=None,
                       songvideo=None, format_id=None, title=None):
        if videoid: link = self.base + link
        async def _dl_api(ql, dt, fp):
            """Fetch audio/video from the configured download API.

            Pass the canonical YouTube URL (not only the 11-char video ID), as
            many download APIs expect a URL in their `query` parameter. Try the
            stream endpoint first, then the documented-style /downloads/key/file
            route used by some Ritesh API deployments.
            """
            if not API_URL: return False
            clean_query = self._clean_link(ql)
            vidid = extract_vidid(clean_query) or clean_query
            params = {"query": clean_query, "dl_type": dt}
            if API_KEY: params["api_key"] = API_KEY
            os.makedirs(os.path.dirname(fp) or "downloads", exist_ok=True)
            client = await self.get_client()
            attempts = [(f"{API_URL}/download", params)]
            if API_KEY and re.fullmatch(r"[A-Za-z0-9_-]{11}", vidid or ""):
                ext = "mp4" if dt == "video" else "mp3"
                attempts.append((f"{API_URL}/downloads/{urllib.parse.quote(API_KEY, safe='')}/{vidid}.{ext}", None))
            for endpoint, query_params in attempts:
                try:
                    async with client.stream("GET", endpoint, params=query_params, timeout=httpx.Timeout(180.0, connect=8.0)) as r:
                        if r.status_code != 200:
                            logging.warning("YouTube audio API returned HTTP %s for %s", r.status_code, endpoint.split("?")[0])
                            continue
                        content_type = (r.headers.get("content-type") or "").lower()
                        if "json" in content_type or "text/html" in content_type:
                            # Do not save API error pages as MP3/MP4 files.
                            body = await r.aread()
                            logging.warning("YouTube audio API returned non-media content (%s): %.180s", content_type, body.decode("utf-8", "ignore"))
                            continue
                        written = 0
                        with open(fp, "wb") as f:
                            async for chunk in r.aiter_bytes(131072):
                                if chunk:
                                    f.write(chunk)
                                    written += len(chunk)
                        if written > 16384:
                            return True
                        try: os.remove(fp)
                        except OSError: pass
                except Exception as e:
                    logging.warning("API download failed at %s: %s", endpoint.split("?")[0], e)
            if os.path.exists(fp):
                try: os.remove(fp)
                except OSError: pass
            logging.warning("Configured audio API could not download video %s", vidid)
            return False
        if API_URL:
            dt = "video" if (video or songvideo) else "audio"
            link = self._clean_link(link)
            vidid = extract_vidid(link) or link
            ext = "mp4" if dt == "video" else "mp3"
            # Reuse a completed local download instead of downloading the same song again.
            # This is the largest safe speed-up for repeated /play requests.
            if not songaudio and not songvideo and re.fullmatch(r"[A-Za-z0-9_-]{11}", vidid or ""):
                cached = os.path.abspath(os.path.join("downloads", f"{vidid}.{ext}"))
                if os.path.isfile(cached) and os.path.getsize(cached) > 16_384:
                    return cached, True
            if songvideo:
                fp = f"downloads/{title}.mp4"
                if await _dl_api(link, "video", fp): return fp
            elif songaudio:
                fp = f"downloads/{title}.mp3"
                if await _dl_api(link, "audio", fp): return fp
            else:
                fp = f"downloads/{vidid}.{ext}"
                # Do not issue a separate prefetch request immediately before
                # downloading the same track. On APIs where /download starts a
                # job, that duplicate request can compete with the real download
                # and increase first-play latency. The completed file is cached
                # at downloads/<video-id>.<ext> and reused on later requests.
                if await _dl_api(link, dt, fp): return fp, True
        os.makedirs("downloads", exist_ok=True)
        loop = asyncio.get_running_loop()
        _base_opts = {"geo_bypass": True, "nocheckcertificate": True, "quiet": True, "no_warnings": True, "socket_timeout": 15, "retries": 1, "fragment_retries": 1}
        def _audio_dl():
            opts = {**_base_opts, "format": "bestaudio[ext=m4a]/bestaudio/best", "outtmpl": "downloads/%(id)s.%(ext)s"}
            with yt_dlp.YoutubeDL(opts) as x:
                info = x.extract_info(link, download=True)
                return x.prepare_filename(info)
        def _video_dl():
            opts = {**_base_opts, "format": "best[height<=720][ext=mp4]/best[height<=720]/best", "outtmpl": "downloads/%(id)s.%(ext)s", "merge_output_format": "mp4"}
            with yt_dlp.YoutubeDL(opts) as x:
                info = x.extract_info(link, download=True)
                path = x.prepare_filename(info)
                if not os.path.exists(path):
                    merged = path.rsplit(".", 1)[0] + ".mp4"
                    if os.path.exists(merged):
                        return merged
                return path
        def _song_video_dl():
            yt_dlp.YoutubeDL({**_base_opts, "format": f"{format_id}+140", "outtmpl": f"downloads/{title}",
                              "prefer_ffmpeg": True, "merge_output_format": "mp4"}).download([link])
        def _song_audio_dl():
            yt_dlp.YoutubeDL({**_base_opts, "format": format_id, "outtmpl": f"downloads/{title}.%(ext)s",
                              "prefer_ffmpeg": True,
                              "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]}).download([link])
        if songvideo:
            await loop.run_in_executor(None, _song_video_dl); return f"downloads/{title}.mp4"
        if songaudio:
            await loop.run_in_executor(None, _song_audio_dl); return f"downloads/{title}.mp3"
        if video:
            if await is_on_off(1):
                direct = True; df = await loop.run_in_executor(None, _video_dl)
            else:
                p = await asyncio.create_subprocess_exec("yt-dlp", "-g", "-f", "best[height<=?720][width<=?1280]", f"{link}",
                      stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                out, err = await p.communicate()
                if out: return out.decode().split("\n")[0], False
                fs = await check_file_size(link)
                if not fs: print("None file Size"); return
                if fs / (1024 * 1024) > 250: print(f"File size {fs/(1024*1024):.2f} MB exceeds the 100MB limit."); return None
                direct = True; df = await loop.run_in_executor(None, _video_dl)
            return df, direct
        return await loop.run_in_executor(None, _audio_dl), True

    async def close(self):
        if self._client and not self._client.is_closed: await self._client.aclose()


YouTube = YouTubeAPI()
