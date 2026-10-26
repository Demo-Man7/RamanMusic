"""
YouTube.py — Compact YouTube platform for AloneMusic
Based on the code supplied by the user; optimized connection reuse and safe file caching.
"""

import asyncio
import os
import re
import json
import time
import logging
import urllib.parse
from typing import Union

import httpx
import yt_dlp

API_URL = os.getenv("API_URL", "https://web.riteshyt.in").rstrip("/")
API_KEY = os.getenv("API_KEY", "riteshfree15605c22c26533fa5833d0fe")

try:
    from pyrogram.enums import MessageEntityType
    from pyrogram.types import Message
except ImportError:
    class MessageEntityType:
        URL = "url"
        TEXT_LINK = "text_link"
    class Message:
        pass

try:
    from youtubesearchpython.__future__ import VideosSearch, Playlist
except ImportError:
    VideosSearch = None
    Playlist = None

try:
    from AviaxMusic.utils.database import is_on_off
except ImportError:
    async def is_on_off(*args, **kwargs):
        return True

try:
    from AviaxMusic.utils.formatters import time_to_seconds
except ImportError:
    def time_to_seconds(value):
        if not value:
            return 0
        try:
            parts = list(map(int, value.split(":")))
            if len(parts) == 3:
                return parts[0] * 3600 + parts[1] * 60 + parts[2]
            if len(parts) == 2:
                return parts[0] * 60 + parts[1]
            return parts[0]
        except Exception:
            return 0


def extract_vidid(query):
    if not query:
        return None
    query = str(query)
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", query):
        return query
    match = re.search(
        r'(?:youtube\.com/(?:[^/]+/.+/|(?:v|e(?:mbed)?)\/|shorts\/|.*[?&]v=)|youtu\.be\/)([^\"&?/\s]{11})',
        query,
    )
    return match.group(1) if match else None


async def check_file_size(link):
    def _parse(formats):
        return sum((item.get("filesize") or item.get("filesize_approx") or 0) for item in formats or [])

    async def _info():
        process = await asyncio.create_subprocess_exec(
            "yt-dlp", "-J", link,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        output, error = await process.communicate()
        if process.returncode != 0:
            logging.warning("yt-dlp file-size check failed: %s", error.decode(errors="ignore")[-1000:])
            return None
        try:
            return json.loads(output.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    info = await _info()
    if not info:
        return None
    formats = info.get("formats", [])
    return _parse(formats) if formats else None


async def download_assistant(query, dl_type):
    safe_query = urllib.parse.quote(query)
    extension = "mp3" if dl_type == "audio" else "mp4"
    if API_KEY:
        return f"{API_URL}/downloads/{API_KEY}/{safe_query}.{extension}"
    return f"{API_URL}/downloads/stream?query={safe_query}&dl_type={dl_type}"


class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.listbase = "https://youtube.com/playlist?list="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.status = "https://www.youtube.com/oembed?url="
        self.reg = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
        self._client = None
        self._recent_prefetches = {}
        self._details_cache = {}
        self._details_cache_ttl = 45

    async def get_client(self):
        """Reuse one async client so TCP/TLS connections can be kept alive."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=5.0),
                follow_redirects=True,
                limits=httpx.Limits(
                    max_connections=30,
                    max_keepalive_connections=10,
                    keepalive_expiry=30.0,
                ),
            )
        return self._client

    async def exists(self, link, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + str(link)
        return bool(link and re.search(self.regex, str(link)))

    async def url(self, message_1):
        messages = [message_1]
        reply = getattr(message_1, "reply_to_message", None)
        if reply:
            messages.append(reply)
        for message in messages:
            entities = getattr(message, "entities", None) or []
            text_value = getattr(message, "text", None) or getattr(message, "caption", None) or ""
            for entity in entities:
                if str(getattr(entity, "type", "")).lower().endswith("url"):
                    return text_value[entity.offset:entity.offset + entity.length]
            caption_entities = getattr(message, "caption_entities", None) or []
            for entity in caption_entities:
                entity_type = str(getattr(entity, "type", "")).lower()
                if entity_type.endswith("text_link") and getattr(entity, "url", None):
                    return entity.url
        return None

    def _clean_link(self, link):
        if not link:
            return ""
        link = str(link).strip()
        # Preserve playlist IDs and video IDs; only remove common tracking parameters.
        link = re.sub(r"([?&])(si|feature|pp|ab_channel)=[^&]*", "", link)
        link = link.rstrip("?&")
        return link

    async def _fetch_details(self, link):
        link = self._clean_link(link)
        now = time.monotonic()
        cached = self._details_cache.get(link)
        if cached and now - cached[0] < self._details_cache_ttl:
            return cached[1]

        params = {"link": link}
        if API_KEY:
            params["api_key"] = API_KEY
        try:
            client = await self.get_client()
            response = await client.get(f"{API_URL}/details", params=params)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and data:
                    self._details_cache[link] = (now, data)
                    if len(self._details_cache) > 300:
                        self._details_cache = {
                            key: value for key, value in self._details_cache.items()
                            if now - value[0] < self._details_cache_ttl
                        }
                    return data
        except Exception as exc:
            logging.warning("Error fetching details from API: %s", exc)
        return None

    async def details(self, link, videoid=None):
        if videoid:
            link = self.base + str(link)
        link = self._clean_link(link)
        if API_URL:
            data = await self._fetch_details(link)
            if data:
                return data.get("title"), data.get("duration_min"), data.get("duration_sec", 0), data.get("thumbnail"), data.get("vidid")
        if VideosSearch:
            try:
                result = await VideosSearch(link, limit=1).next()
                items = result.get("result", []) if result else []
                if items:
                    item = items[0]
                    duration = item.get("duration")
                    return item.get("title"), duration, time_to_seconds(duration), item.get("thumbnails", [{}])[0].get("url", "").split("?")[0], item.get("id")
            except Exception as exc:
                logging.warning("Local VideosSearch fallback failed in details: %s", exc)
        return None, None, 0, None, None

    async def title(self, link, videoid=None):
        if videoid:
            link = self.base + str(link)
        link = self._clean_link(link)
        if API_URL:
            data = await self._fetch_details(link)
            if data and data.get("title"):
                return data["title"]
        if VideosSearch:
            try:
                result = await VideosSearch(link, limit=1).next()
                items = result.get("result", []) if result else []
                if items:
                    return items[0].get("title")
            except Exception as exc:
                logging.warning("Local VideosSearch fallback failed in title: %s", exc)
        return None

    async def duration(self, link, videoid=None):
        if videoid:
            link = self.base + str(link)
        link = self._clean_link(link)
        if API_URL:
            data = await self._fetch_details(link)
            if data and data.get("duration_min"):
                return data["duration_min"]
        if VideosSearch:
            try:
                result = await VideosSearch(link, limit=1).next()
                items = result.get("result", []) if result else []
                if items:
                    return items[0].get("duration")
            except Exception as exc:
                logging.warning("Local VideosSearch fallback failed in duration: %s", exc)
        return None

    async def thumbnail(self, link, videoid=None):
        if videoid:
            link = self.base + str(link)
        link = self._clean_link(link)
        if API_URL:
            data = await self._fetch_details(link)
            if data and data.get("thumbnail"):
                return data["thumbnail"]
        if VideosSearch:
            try:
                result = await VideosSearch(link, limit=1).next()
                items = result.get("result", []) if result else []
                if items:
                    return items[0].get("thumbnails", [{}])[0].get("url", "").split("?")[0]
            except Exception as exc:
                logging.warning("Local VideosSearch fallback failed in thumbnail: %s", exc)
        return None

    async def video(self, link, videoid=None):
        if videoid:
            link = self.base + str(link)
        link = self._clean_link(link)
        try:
            result = await self.download(link, None, video=True)
            if result and isinstance(result, tuple) and result[0]:
                return 1, result[0]
        except Exception as exc:
            logging.warning("Downloading API video locally failed: %s", exc)
        try:
            process = await asyncio.create_subprocess_exec(
                "yt-dlp", "-g", "-f", "best[height<=?720][width<=?1280]", link,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            output, error = await process.communicate()
            if output:
                return 1, output.decode(errors="ignore").splitlines()[0]
            return 0, error.decode(errors="ignore")
        except Exception as exc:
            return 0, str(exc)

    async def playlist(self, link, limit, user_id, videoid=None):
        if videoid:
            link = self.listbase + str(link)
        link = self._clean_link(link)
        params = {"link": link, "limit": limit}
        if API_KEY:
            params["api_key"] = API_KEY
        try:
            response = await (await self.get_client()).get(f"{API_URL}/playlist", params=params)
            if response.status_code == 200:
                return response.json().get("videos")
            logging.error("API Playlist Error (%s): %s", response.status_code, response.text[:500])
        except Exception as exc:
            logging.error("Error fetching playlist from API: %s", exc)
        return None

    async def track(self, link, videoid=None):
        if videoid:
            link = self.base + str(link)
        link = self._clean_link(link)
        if API_URL:
            data = await self._fetch_details(link)
            if data:
                return ({
                    "title": data.get("title"),
                    "link": data.get("link") or link,
                    "vidid": data.get("vidid") or extract_vidid(link),
                    "duration_min": data.get("duration_min"),
                    "thumb": data.get("thumbnail"),
                }, data.get("vidid") or extract_vidid(link))
        if VideosSearch:
            try:
                result = await VideosSearch(link, limit=1).next()
                items = result.get("result", []) if result else []
                if items:
                    item = items[0]
                    return ({
                        "title": item.get("title"),
                        "link": item.get("link") or link,
                        "vidid": item.get("id"),
                        "duration_min": item.get("duration"),
                        "thumb": item.get("thumbnails", [{}])[0].get("url", "").split("?")[0],
                    }, item.get("id"))
            except Exception as exc:
                logging.warning("Local track fallback failed: %s", exc)
        return None, None

    async def formats(self, link, videoid=None):
        if videoid:
            link = self.base + str(link)
        link = self._clean_link(link)
        if API_URL:
            params = {"link": link}
            if API_KEY:
                params["api_key"] = API_KEY
            try:
                response = await (await self.get_client()).get(f"{API_URL}/formats", params=params)
                if response.status_code == 200:
                    formats = response.json().get("formats", [])
                    for item in formats:
                        item["yturl"] = link
                    return formats, link
            except Exception as exc:
                logging.warning("Error fetching formats from API: %s", exc)

        def _extract():
            options = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
            with yt_dlp.YoutubeDL(options) as downloader:
                return downloader.extract_info(link, download=False)
        try:
            info = await asyncio.to_thread(_extract)
            output = []
            for item in info.get("formats", []):
                if "dash" not in str(item.get("format", "")).lower():
                    output.append({
                        "format": item.get("format"), "filesize": item.get("filesize"),
                        "format_id": item.get("format_id"), "ext": item.get("ext"),
                        "format_note": item.get("format_note"), "yturl": link,
                    })
            return output, link
        except Exception as exc:
            logging.warning("Formats extraction failed: %s", exc)
            return [], link

    async def slider(self, link, query_type, videoid=None):
        if videoid:
            link = self.base + str(link)
        link = self._clean_link(link)
        if API_URL:
            params = {"query": link, "limit": 10}
            if API_KEY:
                params["api_key"] = API_KEY
            try:
                response = await (await self.get_client()).get(f"{API_URL}/search", params=params)
                if response.status_code == 200:
                    results = response.json().get("result", [])
                    if results and len(results) > query_type:
                        item = results[query_type]
                        thumb = item.get("thumbnails", [{}])[0].get("url") if item.get("thumbnails") else None
                        return item.get("title"), item.get("duration"), thumb.split("?")[0] if thumb else None, item.get("id")
            except Exception as exc:
                logging.warning("Error in slider/search from API: %s", exc)
        if VideosSearch:
            try:
                result = await VideosSearch(link, limit=10).next()
                items = result.get("result", []) if result else []
                if items and len(items) > query_type:
                    item = items[query_type]
                    thumb = item.get("thumbnails", [{}])[0].get("url")
                    return item.get("title"), item.get("duration"), thumb.split("?")[0] if thumb else None, item.get("id")
            except Exception as exc:
                logging.warning("Local slider fallback failed: %s", exc)
        return None, None, None, None

    async def prefetch(self, link, video=False):
        if not API_URL:
            return False
        dl_type = "video" if video else "audio"
        link = self._clean_link(link)
        now = time.time()
        video_id = extract_vidid(link) or link
        cache_key = f"{video_id}_{dl_type}"
        if cache_key in self._recent_prefetches and now - self._recent_prefetches[cache_key] < 30:
            return True
        self._recent_prefetches[cache_key] = now
        if len(self._recent_prefetches) > 100:
            self._recent_prefetches = {key: value for key, value in self._recent_prefetches.items() if now - value < 300}
        params = {"query": link, "dl_type": dl_type, "prefetch": "true"}
        if API_KEY:
            params["api_key"] = API_KEY
        try:
            await (await self.get_client()).get(f"{API_URL}/download", params=params)
            return True
        except Exception as exc:
            logging.warning("Prefetch failed for %s: %s", link, exc)
            return False

    async def prefetch_queue(self, queries, video=False):
        if not API_URL or not queries:
            return False
        params = {"api_key": API_KEY} if API_KEY else {}
        try:
            await (await self.get_client()).post(
                f"{API_URL}/prefetch_bulk",
                json={"queries": queries, "dl_type": "video" if video else "audio"},
                params=params,
            )
            return True
        except Exception as exc:
            logging.warning("Bulk prefetch failed: %s", exc)
            return False

    async def download(self, link, mystic, video=None, videoid=None, songaudio=None,
                       songvideo=None, format_id=None, title=None):
        if videoid:
            link = self.base + str(link)
        link = self._clean_link(link)

        async def _dl_api(query_link, dl_type, file_path):
            if not API_URL:
                return False
            # Avoid re-downloading a completed file.
            if os.path.isfile(file_path) and os.path.getsize(file_path) > 0:
                return True

            video_id = extract_vidid(query_link) or query_link
            params = {"query": video_id, "dl_type": dl_type}
            if API_KEY:
                params["api_key"] = API_KEY
            os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
            temp_path = file_path + ".part"
            try:
                client = await self.get_client()
                async with client.stream(
                    "GET", f"{API_URL}/download", params=params,
                    timeout=httpx.Timeout(120.0, connect=5.0),
                ) as response:
                    if response.status_code != 200:
                        logging.warning("Download API returned HTTP %s for %s", response.status_code, video_id)
                        return False
                    with open(temp_path, "wb") as output_file:
                        async for chunk in response.aiter_bytes(256 * 1024):
                            if chunk:
                                output_file.write(chunk)
                if not os.path.isfile(temp_path) or os.path.getsize(temp_path) == 0:
                    return False
                os.replace(temp_path, file_path)
                return True
            except Exception as exc:
                logging.warning("API download failed for %s: %s", video_id, exc)
                return False
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass

        if API_URL:
            dl_type = "video" if (video or songvideo) else "audio"
            video_id = extract_vidid(link) or link
            extension = "mp4" if dl_type == "video" else "mp3"
            os.makedirs("downloads", exist_ok=True)
            if songvideo:
                file_path = f"downloads/{title}.mp4"
                if await _dl_api(link, "video", file_path):
                    return file_path
            elif songaudio:
                file_path = f"downloads/{title}.mp3"
                if await _dl_api(link, "audio", file_path):
                    return file_path
            else:
                file_path = f"downloads/{video_id}.{extension}"
                if await _dl_api(link, dl_type, file_path):
                    return file_path, True

        loop = asyncio.get_running_loop()
        base_options = {
            "geo_bypass": True,
            "nocheckcertificate": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 15,
            "retries": 2,
            "fragment_retries": 2,
        }

        def _audio_dl():
            os.makedirs("downloads", exist_ok=True)
            options = {**base_options, "format": "bestaudio/best", "outtmpl": "downloads/%(id)s.%(ext)s"}
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(link, download=False)
                file_path = os.path.join("downloads", f"{info['id']}.{info['ext']}")
                if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                    return file_path
                downloader.download([link])
                # Locate actual extension in case yt-dlp selected a different one.
                candidates = [os.path.join("downloads", f"{info['id']}.{info['ext']}")]
                for candidate in candidates:
                    if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
                        return candidate
                return file_path

        def _video_dl():
            os.makedirs("downloads", exist_ok=True)
            options = {
                **base_options,
                "format": "best[height<=720][width<=1280]/best",
                "outtmpl": "downloads/%(id)s.%(ext)s",
                "merge_output_format": "mp4",
            }
            with yt_dlp.YoutubeDL(options) as downloader:
                info = downloader.extract_info(link, download=False)
                downloader.download([link])
                video_id = info.get("id")
                for extension in ("mp4", info.get("ext", "mp4"), "mkv", "webm"):
                    candidate = os.path.join("downloads", f"{video_id}.{extension}")
                    if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
                        return candidate
                return os.path.join("downloads", f"{video_id}.mp4")

        def _song_video_dl():
            options = {
                **base_options,
                "format": f"{format_id}+140",
                "outtmpl": f"downloads/{title}.%(ext)s",
                "prefer_ffmpeg": True,
                "merge_output_format": "mp4",
            }
            with yt_dlp.YoutubeDL(options) as downloader:
                downloader.download([link])

        def _song_audio_dl():
            options = {
                **base_options,
                "format": format_id,
                "outtmpl": f"downloads/{title}.%(ext)s",
                "prefer_ffmpeg": True,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
            }
            with yt_dlp.YoutubeDL(options) as downloader:
                downloader.download([link])

        if songvideo:
            await loop.run_in_executor(None, _song_video_dl)
            return f"downloads/{title}.mp4"
        if songaudio:
            await loop.run_in_executor(None, _song_audio_dl)
            return f"downloads/{title}.mp3"
        if video:
            if await is_on_off(1):
                direct = True
                downloaded_file = await loop.run_in_executor(None, _video_dl)
            else:
                process = await asyncio.create_subprocess_exec(
                    "yt-dlp", "-g", "-f", """best[height<=?720][width<=?1280]""", link,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                output, error = await process.communicate()
                if output:
                    return output.decode(errors="ignore").splitlines()[0], False
                size = await check_file_size(link)
                if not size:
                    logging.warning("Could not determine video file size")
                    return None
                if size / (1024 * 1024) > 250:
                    logging.warning("Video file exceeds 250 MB limit")
                    return None
                direct = True
                downloaded_file = await loop.run_in_executor(None, _video_dl)
            return downloaded_file, direct
        return await loop.run_in_executor(None, _audio_dl), True

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None


YouTube = YouTubeAPI()
                 
