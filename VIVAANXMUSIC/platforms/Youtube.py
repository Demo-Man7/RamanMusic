import asyncio
import os
import random
import re
from typing import Union
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import aiohttp
import yt_dlp
import requests
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from py_yt import Playlist


# Single API downloader. Configure these in Heroku Config Vars if the provider
# changes; direct yt-dlp remains the fallback.
YOUTUBE_API_URL = os.environ.get(
    "YOUTUBE_API_URL",
    os.environ.get("SHRUTI_API_URL", "https://api01.shrutibots.site"),
).rstrip("/")
YOUTUBE_API_KEY = os.environ.get(
    "YOUTUBE_API_KEY",
    os.environ.get("SHRUTI_API_KEY", "ShrutiBotsgbxTAhugEwUZWzgaosDX"),
)

DOWNLOAD_DIR = "downloads"

# Faster file/network transfer settings.
DOWNLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MB
AUDIO_DOWNLOAD_TIMEOUT = 300
VIDEO_DOWNLOAD_TIMEOUT = 600

# Short-lived cache for resolved YouTube media URLs.
# The URL is never stored in the queue permanently because YouTube URLs expire.
_STREAM_URL_CACHE = {}
_STREAM_URL_CACHE_TTL = 45
_COOKIE_FILE_CACHE = None
_COOKIE_LOOKUP_DONE = False


def time_to_seconds(value):
    if not value:
        return 0

    try:
        total = 0
        for part in str(value).split(":"):
            total = total * 60 + int(part)
        return total
    except (ValueError, TypeError):
        return 0


def _video_id(link: str) -> str:
    if not link:
        return ""

    link = str(link).strip()

    if re.fullmatch(r"[\w-]{6,}", link):
        return link

    try:
        parsed = urlparse(link)
        host = (parsed.netloc or "").lower()

        if "youtu.be" in host:
            video_id = parsed.path.strip("/").split("/")[0]
            if re.fullmatch(r"[\w-]{6,}", video_id):
                return video_id

        if (
            "youtube.com" in host
            or "youtube-nocookie.com" in host
        ):
            query = parse_qs(parsed.query)

            if query.get("v"):
                return query["v"][0]

            parts = [
                part
                for part in parsed.path.split("/")
                if part
            ]

            if (
                len(parts) >= 2
                and parts[0] in {
                    "shorts",
                    "embed",
                    "live",
                    "v",
                }
            ):
                return parts[1]

    except Exception:
        pass

    patterns = [
        r"(?:youtu\.be/)([\w-]{6,})",
        r"(?:youtube\.com/watch\?[^#]*v=)([\w-]{6,})",
        r"(?:youtube\.com/shorts/)([\w-]{6,})",
        r"(?:youtube\.com/embed/)([\w-]{6,})",
        r"(?:youtube\.com/live/)([\w-]{6,})",
    ]

    for pattern in patterns:
        match = re.search(pattern, link)
        if match:
            return match.group(1)

    return ""


def _clean_youtube_url(link: str) -> str:
    if not link:
        return ""

    video_id = _video_id(link)

    if video_id:
        return (
            "https://www.youtube.com/watch?v="
            f"{video_id}"
        )

    return str(link).strip()


def _normalize_title(value: str) -> str:
    value = str(value or "").lower().strip()

    value = re.sub(
        r"\([^)]*\)|\[[^]]*\]",
        " ",
        value,
    )

    value = re.sub(
        r"\b("
        r"official|video|audio|lyrics|lyric|full|song|music|"
        r"hd|4k|remastered|version|visualizer|mv|"
        r"lvideo|fullvideo|status"
        r")\b",
        " ",
        value,
    )

    return re.sub(
        r"[^a-z0-9]+",
        "",
        value,
    )


def _title_words(value: str):
    value = str(value or "").lower()

    value = re.sub(
        r"\([^)]*\)|\[[^]]*\]",
        " ",
        value,
    )

    value = re.sub(
        r"\b("
        r"official|video|audio|lyrics|lyric|full|song|music|"
        r"hd|4k|remastered|version|visualizer|mv"
        r")\b",
        " ",
        value,
    )

    words = re.findall(
        r"[a-z0-9]+",
        value,
    )

    return {
        word
        for word in words
        if len(word) >= 4
    }


def _youtube_cookie_file():
    """Resolve optional YouTube cookies from Heroku Config Vars.

    Set YOUTUBE_COOKIES_FILE to an existing Netscape cookie file path, or set
    YOUTUBE_COOKIES to the Netscape cookie-file contents. The project's legacy
    COOKIES variable (a paste URL) is also supported. Session cookies are not
    bundled in the distributable ZIP.
    """
    global _COOKIE_FILE_CACHE, _COOKIE_LOOKUP_DONE

    cookie_path = os.environ.get("YOUTUBE_COOKIES_FILE", "").strip()
    if cookie_path and os.path.isfile(cookie_path):
        return cookie_path

    cookie_value = os.environ.get("YOUTUBE_COOKIES", "")
    if cookie_value and os.path.isfile(cookie_value):
        return cookie_value

    if not cookie_value and not _COOKIE_LOOKUP_DONE:
        _COOKIE_LOOKUP_DONE = True
        legacy_url = os.environ.get("COOKIES", "").strip()
        if legacy_url.startswith(("https://", "http://")):
            paste_id = urlparse(legacy_url).path.rstrip("/").split("/")[-1]
            if paste_id:
                try:
                    response = requests.get(
                        f"https://batbin.me/raw/{paste_id}", timeout=10
                    )
                    response.raise_for_status()
                    cookie_value = response.text
                except Exception:
                    cookie_value = ""

    if not cookie_value:
        return _COOKIE_FILE_CACHE if _COOKIE_FILE_CACHE and os.path.isfile(_COOKIE_FILE_CACHE) else None

    if "# Netscape HTTP Cookie File" not in cookie_value and "youtube.com" not in cookie_value:
        return None

    cookie_path = "/tmp/thakurmusic-youtube-cookies.txt"
    try:
        if not os.path.isfile(cookie_path) or Path(cookie_path).read_text(errors="ignore") != cookie_value:
            with open(cookie_path, "w", encoding="utf-8") as cookie_file:
                cookie_file.write(cookie_value)
            try:
                os.chmod(cookie_path, 0o600)
            except OSError:
                pass
        _COOKIE_FILE_CACHE = cookie_path
        return cookie_path
    except OSError:
        return None


def _ydl_opts():
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "ignoreerrors": True,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 4,
    }
    cookie_file = _youtube_cookie_file()
    if cookie_file:
        options["cookiefile"] = cookie_file
    return options


async def _extract_info(
    link: str,
    download=False,
    opts=None,
):
    def run():
        options = dict(_ydl_opts())

        if opts:
            options.update(opts)

        options["skip_download"] = not download

        with yt_dlp.YoutubeDL(options) as ydl:
            return ydl.extract_info(
                link,
                download=download,
            )

    return await asyncio.to_thread(run)


async def _oembed_info(url: str):
    """Get public title/thumbnail metadata without requiring YouTube login."""
    try:
        timeout = aiohttp.ClientTimeout(total=12, connect=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"},
            ) as response:
                if response.status != 200:
                    return None
                data = await response.json(content_type=None)
                vid = _video_id(url)
                if not vid or not isinstance(data, dict):
                    return None
                return {
                    "id": vid,
                    "title": data.get("title") or f"YouTube video {vid}",
                    "thumbnail": data.get("thumbnail_url") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                    "duration": 0,
                }
    except Exception:
        return None


async def _search_youtube(query: str):
    def run():
        options = _ydl_opts()
        options.update({
            "extract_flat": True,
            "ignoreerrors": True,
        })

        with yt_dlp.YoutubeDL(options) as ydl:
            data = ydl.extract_info(
                f"ytsearch1:{query}",
                download=False,
            )

            entries = (
                data.get("entries")
                if data
                else []
            ) or []

            return entries[0] if entries else None

    try:
        return await asyncio.to_thread(run)
    except Exception:
        return None


async def _download_from_api(
    base_url: str,
    api_key: str,
    video_id: str,
    file_type: str,
    output_path: str,
    timeout_seconds: int,
) -> Union[str, None]:
    """Download a binary audio/video response from one API.

    Some providers return a JSON object containing a direct URL instead of
    the media bytes. Handle both formats without ever decoding binary media
    as UTF-8.
    """
    if not base_url or not video_id:
        return None

    tmp = output_path + ".part"
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except Exception:
        pass

    timeout = aiohttp.ClientTimeout(
        total=timeout_seconds,
        connect=15,
        sock_connect=15,
        sock_read=120,
    )
    connector = aiohttp.TCPConnector(
        limit=30,
        limit_per_host=10,
        ttl_dns_cache=300,
        enable_cleanup_closed=True,
    )

    params = {
        "url": video_id,
        "type": file_type,
    }
    if api_key:
        params["api_key"] = api_key

    try:
        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            read_bufsize=DOWNLOAD_CHUNK_SIZE,
        ) as session:
            async with session.get(
                f"{base_url}/download",
                params=params,
                allow_redirects=True,
            ) as resp:
                if resp.status != 200:
                    return None

                content_type = (
                    resp.headers.get("content-type", "")
                    .lower()
                )

                # JSON/text responses may contain a direct media URL.
                if (
                    "application/json" in content_type
                    or "text/" in content_type
                ):
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        return None

                    direct_url = None
                    if isinstance(data, dict):
                        for key in (
                            "url",
                            "download_url",
                            "download",
                            "link",
                            "stream_url",
                        ):
                            value = data.get(key)
                            if value:
                                direct_url = str(value)
                                break

                    if not direct_url:
                        return None

                    async with session.get(
                        direct_url,
                        allow_redirects=True,
                    ) as media:
                        if media.status != 200:
                            return None
                        with open(tmp, "wb") as file:
                            async for chunk in media.content.iter_chunked(
                                DOWNLOAD_CHUNK_SIZE
                            ):
                                if chunk:
                                    file.write(chunk)
                else:
                    # IMPORTANT: write raw bytes directly; do not call
                    # resp.text()/resp.json() on binary media.
                    with open(tmp, "wb") as file:
                        async for chunk in resp.content.iter_chunked(
                            DOWNLOAD_CHUNK_SIZE
                        ):
                            if chunk:
                                file.write(chunk)

        if (
            os.path.exists(tmp)
            and os.path.getsize(tmp) > 0
        ):
            os.replace(tmp, output_path)
            return output_path

    except Exception:
        pass
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass

    return None


async def _api_download(
    video_id: str,
    file_type: str,
    output_path: str,
    timeout_seconds: int,
) -> Union[str, None]:
    """Try the configured single API; fall back to direct yt-dlp if it fails."""
    if not YOUTUBE_API_URL:
        return None
    return await _download_from_api(
        YOUTUBE_API_URL,
        YOUTUBE_API_KEY,
        video_id,
        file_type,
        output_path,
        timeout_seconds,
    )


async def download_song(
    link: str,
) -> Union[str, None]:

    url = _clean_youtube_url(link)
    vid = _video_id(url)

    if not vid:
        return None

    os.makedirs(
        DOWNLOAD_DIR,
        exist_ok=True,
    )

    cached_files = [
        os.path.join(
            DOWNLOAD_DIR,
            f"{vid}.mp3",
        ),
        os.path.join(
            DOWNLOAD_DIR,
            f"{vid}.m4a",
        ),
        os.path.join(
            DOWNLOAD_DIR,
            f"{vid}.webm",
        ),
        os.path.join(
            DOWNLOAD_DIR,
            f"{vid}.opus",
        ),
    ]

    for cached in cached_files:
        if (
            os.path.exists(cached)
            and os.path.getsize(cached) > 0
        ):
            return cached

    # Fast API downloader first.
    result = await _api_download(
        vid,
        "audio",
        cached_files[0],
        AUDIO_DOWNLOAD_TIMEOUT,
    )

    if result:
        return result

    # Direct yt-dlp fallback.
    try:
        def run():
            base = os.path.join(
                DOWNLOAD_DIR,
                vid,
            )

            opts = _ydl_opts()
            opts.update({
                "format": (
                    "bestaudio[ext=m4a]/"
                    "bestaudio[ext=webm]/"
                    "bestaudio/best"
                ),
                "outtmpl": (
                    base + ".%(ext)s"
                ),
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "retries": 3,
                "fragment_retries": 3,
                "socket_timeout": 30,
                "concurrent_fragment_downloads": 4,
            })

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            candidates = [
                base + ".m4a",
                base + ".webm",
                base + ".opus",
                base + ".mp3",
                base + ".mp4",
            ]

            for path in candidates:
                if (
                    os.path.exists(path)
                    and os.path.getsize(path) > 0
                ):
                    return path

            return None

        return await asyncio.to_thread(run)

    except Exception:
        return None


async def download_video(
    link: str,
) -> Union[str, None]:

    url = _clean_youtube_url(link)
    vid = _video_id(url)

    if not vid:
        return None

    os.makedirs(
        DOWNLOAD_DIR,
        exist_ok=True,
    )

    path = os.path.join(
        DOWNLOAD_DIR,
        f"{vid}.mp4",
    )

    if (
        os.path.exists(path)
        and os.path.getsize(path) > 0
    ):
        return path

    result = await _api_download(
        vid,
        "video",
        path,
        VIDEO_DOWNLOAD_TIMEOUT,
    )

    if result:
        return result

    try:
        def run():
            opts = _ydl_opts()
            opts.update({
                "format": (
                    "bestvideo[ext=mp4]+"
                    "bestaudio[ext=m4a]/"
                    "best[ext=mp4]/"
                    "best"
                ),
                "merge_output_format": "mp4",
                "outtmpl": path,
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "retries": 3,
                "fragment_retries": 3,
                "socket_timeout": 30,
                "concurrent_fragment_downloads": 4,
            })

            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])

            if (
                os.path.exists(path)
                and os.path.getsize(path) > 0
            ):
                return path

            for extension in (
                ".mkv",
                ".webm",
                ".mp4",
            ):
                candidate = os.path.join(
                    DOWNLOAD_DIR,
                    f"{vid}{extension}",
                )

                if (
                    os.path.exists(candidate)
                    and os.path.getsize(candidate) > 0
                ):
                    return candidate

            return None

        return await asyncio.to_thread(run)

    except Exception:
        return None



def _language_search_queries(title: str):
    """Return same-language search queries for autoplay."""
    text = str(title or "").lower()

    if re.search(r"[\u0900-\u097f]", text):
        if any(word in text for word in ("भोजपुरी", "भोजपुर", "खेसारी", "पवन", "शिल्पी", "रितेश")):
            label = "bhojpuri"
        else:
            label = "hindi"
    else:
        labels = [
            (("bhojpuri", "khesari", "pawan singh", "shilpi raj", "ritesh pandey"), "bhojpuri"),
            (("punjabi", "diljit", "sidhu", "karan aujla", "ap dhillon"), "punjabi"),
            (("haryanvi", "sapna chaudhary", "renuka panwar"), "haryanvi"),
            (("marathi",), "marathi"),
            (("gujarati", "garba"), "gujarati"),
            (("bengali", "bangla"), "bengali"),
            (("tamil",), "tamil"),
            (("telugu",), "telugu"),
            (("kannada",), "kannada"),
            (("malayalam",), "malayalam"),
            (("nepali",), "nepali"),
        ]
        label = "hindi"
        for terms, found_label in labels:
            if any(term in text for term in terms):
                label = found_label
                break

    return [
        f"{title} {label} song",
        f"latest {label} songs official audio",
        f"popular {label} songs",
        f"{label} songs",
    ]


class YouTubeAPI:

    def __init__(self):
        self.base = (
            "https://www.youtube.com/watch?v="
        )

        self.regex = (
            r"(?:youtube\.com|youtu\.be)"
        )

        self.status = (
            "https://www.youtube.com/oembed?url="
        )

        self.listbase = (
            "https://youtube.com/playlist?list="
        )

        self.reg = re.compile(
            r"\x1B(?:[@-Z\\-_]|"
            r"\[[0-?]*[ -/]*[@-~])"
        )

    async def exists(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            return bool(
                re.fullmatch(
                    r"[\w-]{6,}",
                    str(link),
                )
            )

        return bool(
            _video_id(link)
        )

    async def url(
        self,
        message_1: Message,
    ) -> Union[str, None]:

        messages = [message_1]

        if message_1.reply_to_message:
            messages.append(
                message_1.reply_to_message,
            )

        for message in messages:

            text = (
                message.text
                or message.caption
                or ""
            )

            entities = (
                message.entities
                or message.caption_entities
                or []
            )

            for entity in entities:

                if (
                    entity.type
                    == MessageEntityType.URL
                ):
                    found_url = text[
                        entity.offset:
                        entity.offset
                        + entity.length
                    ]

                    if _video_id(found_url):
                        return found_url

                if (
                    entity.type
                    == MessageEntityType.TEXT_LINK
                    and entity.url
                    and _video_id(entity.url)
                ):
                    return entity.url

        return None

    async def _get_info(
        self,
        url: str,
        search_query: str = None,
    ):
        info = None

        try:
            info = await _extract_info(url)
        except Exception:
            pass

        if info:
            return info

        video_id = _video_id(url)

        if video_id:
            info = await _search_youtube(
                video_id
            )

            if (
                info
                and str(
                    info.get("id") or ""
                ) == video_id
            ):
                return info

        if search_query:
            searched = await _search_youtube(search_query)
            if searched:
                return searched

        # For a valid direct YouTube URL, allow queueing even when YouTube
        # blocks yt-dlp metadata extraction. Actual media resolution is retried
        # separately by stream_url/download_song.
        if video_id:
            metadata = await _oembed_info(_clean_youtube_url(url))
            if metadata:
                return metadata

        return None

    async def details(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        url = (
            self.base + str(link)
            if videoid
            else _clean_youtube_url(link)
        )

        direct_id = _video_id(url)

        info = await self._get_info(
            url,
            None if direct_id else link,
        )

        if not info:
            raise ValueError(
                "YouTube track details could not be fetched"
            )

        title = (
            info.get("title")
            or "Unknown Title"
        )

        duration_sec = int(
            info.get("duration") or 0
        )

        duration_min = (
            f"{duration_sec // 60}:"
            f"{duration_sec % 60:02d}"
            if duration_sec
            else "00:00"
        )

        vidid = (
            info.get("id")
            or direct_id
        )

        thumbnail = (
            info.get("thumbnail")
            or (
                f"https://i.ytimg.com/vi/"
                f"{vidid}/hqdefault.jpg"
                if vidid
                else ""
            )
        )

        return (
            title,
            duration_min,
            duration_sec,
            thumbnail,
            vidid,
        )

    async def title(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        return (
            await self.details(
                link,
                videoid,
            )
        )[0]

    async def duration(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        return (
            await self.details(
                link,
                videoid,
            )
        )[1]

    async def thumbnail(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        return (
            await self.details(
                link,
                videoid,
            )
        )[3]

    async def stream_url(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        """Resolve a short-lived YouTube media URL without downloading the song.

        This is the fast playback path: yt-dlp only resolves the source URL,
        then PyTgCalls streams it directly. Queue entries keep the YouTube ID
        so an expired URL is never reused for the next song.
        """
        url = (
            self.base + str(link)
            if videoid
            else _clean_youtube_url(link)
        )

        vid = _video_id(url)
        if not vid:
            return None

        # Reuse a very recent resolved URL for fast Skip/queue transitions.
        cached = _STREAM_URL_CACHE.get(vid)
        if cached:
            cached_url, cached_at = cached
            if (asyncio.get_running_loop().time() - cached_at) < _STREAM_URL_CACHE_TTL:
                return cached_url
            _STREAM_URL_CACHE.pop(vid, None)

        try:
            options = {
                "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio",
                "noplaylist": True,
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "socket_timeout": 12,
                "retries": 1,
                "fragment_retries": 1,
            }
            info = await _extract_info(url, download=False, opts=options)
            if info:
                media_url = info.get("url")
                if media_url:
                    media_url = str(media_url)
                    _STREAM_URL_CACHE[vid] = (
                        media_url,
                        asyncio.get_running_loop().time(),
                    )
                    return media_url

                # Some yt-dlp versions expose the selected format only in formats.
                for fmt in info.get("formats") or []:
                    fmt_url = fmt.get("url")
                    if fmt_url and fmt.get("acodec") not in (None, "none"):
                        fmt_url = str(fmt_url)
                        _STREAM_URL_CACHE[vid] = (
                            fmt_url,
                            asyncio.get_running_loop().time(),
                        )
                        return fmt_url
        except Exception:
            pass

        # YouTube may require a signed-in session for direct stream extraction.
        # Try the configured download API and let PyTgCalls read the local file.
        try:
            local_audio = await download_song(url)
            if local_audio and os.path.isfile(local_audio) and os.path.getsize(local_audio) > 0:
                return local_audio
        except Exception:
            pass

        return None

    async def video(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        url = (
            self.base + str(link)
            if videoid
            else _clean_youtube_url(link)
        )

        try:
            downloaded_file = await download_video(
                url,
            )

            if downloaded_file:
                return 1, downloaded_file

            return (
                0,
                "Video download failed",
            )

        except Exception as error:
            return (
                0,
                f"Video download error: {error}",
            )

    async def playlist(
        self,
        link,
        limit,
        user_id,
        videoid: Union[bool, str] = None,
    ):
        if videoid:
            link = self.listbase + str(link)

        try:
            plist = await Playlist.get(link)

            videos = (
                plist.get("videos")
                or []
            )

            return [
                video.get("id")
                for video in videos[:limit]
                if video
                and video.get("id")
            ]

        except Exception:
            return []

    async def track(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        url = (
            self.base + str(link)
            if videoid
            else _clean_youtube_url(link)
        )

        direct_id = _video_id(url)

        info = await self._get_info(
            url,
            None if direct_id else link,
        )

        if not info:
            raise ValueError(
                "YouTube track details could not be fetched"
            )

        vidid = (
            info.get("id")
            or direct_id
        )

        if not vidid:
            raise ValueError(
                "YouTube video ID not found"
            )

        title = (
            info.get("title")
            or "Unknown Title"
        )

        duration_sec = int(
            info.get("duration") or 0
        )

        duration_min = (
            f"{duration_sec // 60}:"
            f"{duration_sec % 60:02d}"
            if duration_sec
            else "00:00"
        )

        yturl = (
            "https://www.youtube.com/watch?v="
            f"{vidid}"
        )

        thumbnail = (
            info.get("thumbnail")
            or (
                f"https://i.ytimg.com/vi/"
                f"{vidid}/hqdefault.jpg"
            )
        )

        return {
            "title": title,
            "link": yturl,
            "vidid": vidid,
            "duration_min": duration_min,
            "thumb": thumbnail,
        }, vidid

    async def autoplay(
        self,
        videoid: str,
        title: str = "",
        max_duration: Union[int, None] = None,
        exclude_ids=None,
        exclude_titles=None,
    ):
        seed_id = str(videoid or "").strip()
        query = str(title or "").strip()

        if not query:
            return None

        excluded_ids = {
            str(item).strip()
            for item in (exclude_ids or [])
            if str(item).strip()
        }

        if seed_id:
            excluded_ids.add(seed_id)

        excluded_titles = {
            _normalize_title(item)
            for item in (exclude_titles or [])
            if _normalize_title(item)
        }

        current_title = _normalize_title(query)

        if current_title:
            excluded_titles.add(current_title)

        current_words = _title_words(query)

        def run_search(search_query):
            options = _ydl_opts()
            options.update({
                "extract_flat": True,
                "ignoreerrors": True,
            })

            with yt_dlp.YoutubeDL(options) as ydl:
                data = ydl.extract_info(
                    f"ytsearch20:{search_query}",
                    download=False,
                )

                return (
                    data.get("entries")
                    if data
                    else []
                ) or []

        # Keep autoplay in the same language as the current song.
        search_queries = _language_search_queries(query)
        search_queries.extend([
            f"{query} official audio",
            f"{query} song",
        ])

        candidates = []
        seen_ids = set()
        seen_titles = set()

        for search_query in search_queries:
            try:
                entries = await asyncio.to_thread(
                    run_search,
                    search_query,
                )
            except Exception:
                continue

            for entry in entries:
                if not entry:
                    continue

                candidate_id = str(
                    entry.get("id") or ""
                ).strip()

                song_title = str(
                    entry.get("title") or ""
                ).strip()

                if (
                    not candidate_id
                    or not song_title
                ):
                    continue

                if (
                    candidate_id in excluded_ids
                    or candidate_id in seen_ids
                ):
                    continue

                normalized_title = (
                    _normalize_title(song_title)
                )

                if (
                    not normalized_title
                    or normalized_title
                    in excluded_titles
                    or normalized_title
                    in seen_titles
                ):
                    continue

                duration_sec = int(
                    entry.get("duration") or 0
                )

                if duration_sec <= 0:
                    continue

                if (
                    max_duration
                    and duration_sec
                    > int(max_duration)
                ):
                    continue

                candidate_words = _title_words(
                    song_title
                )

                overlap = (
                    current_words
                    & candidate_words
                )

                if (
                    len(current_words) >= 2
                    and len(overlap) >= 2
                ):
                    continue

                seen_ids.add(candidate_id)
                seen_titles.add(normalized_title)

                candidates.append({
                    "id": candidate_id,
                    "title": song_title,
                    "duration": duration_sec,
                    "entry": entry,
                })

                if len(candidates) >= 40:
                    break

            if len(candidates) >= 40:
                break

        if not candidates:
            return None

        selected = random.choice(candidates)

        entry = selected["entry"]
        candidate_id = selected["id"]
        song_title = selected["title"]
        duration_sec = selected["duration"]

        thumbnail = (
            entry.get("thumbnail")
            or (
                f"https://i.ytimg.com/vi/"
                f"{candidate_id}/hqdefault.jpg"
            )
        )

        return {
            "title": song_title,
            "link": (
                "https://www.youtube.com/"
                f"watch?v={candidate_id}"
            ),
            "vidid": candidate_id,
            "duration_sec": duration_sec,
            "duration_min": (
                f"{duration_sec // 60}:"
                f"{duration_sec % 60:02d}"
            ),
            "thumb": thumbnail,
        }

    async def formats(
        self,
        link: str,
        videoid: Union[bool, str] = None,
    ):
        url = (
            self.base + str(link)
            if videoid
            else _clean_youtube_url(link)
        )

        try:
            result = await _extract_info(url)

            if not result:
                return [], url

            formats_available = []

            for fmt in (
                result.get("formats", [])
            ):
                if (
                    "dash"
                    in str(
                        fmt.get(
                            "format",
                            "",
                        )
                    ).lower()
                ):
                    continue

                formats_available.append({
                    "format": fmt.get("format"),
                    "filesize": fmt.get("filesize"),
                    "format_id": fmt.get("format_id"),
                    "ext": fmt.get("ext"),
                    "format_note": fmt.get(
                        "format_note"
                    ),
                    "yturl": url,
                })

            return (
                formats_available,
                url,
            )

        except Exception:
            return [], url

    async def slider(
        self,
        link: str,
        query_type: int,
        videoid: Union[bool, str] = None,
    ):
        url = (
            self.base + str(link)
            if videoid
            else _clean_youtube_url(link)
        )

        def run():
            opts = _ydl_opts()
            opts["extract_flat"] = True

            with yt_dlp.YoutubeDL(opts) as ydl:
                if _video_id(url):
                    data = ydl.extract_info(
                        url,
                        download=False,
                    )

                    if (
                        data
                        and not data.get("entries")
                    ):
                        return data

                data = ydl.extract_info(
                    f"ytsearch10:{link}",
                    download=False,
                )

                entries = (
                    data.get("entries")
                    if data
                    else []
                ) or []

                if (
                    not entries
                    or query_type >= len(entries)
                ):
                    raise IndexError(
                        "YouTube search result not found"
                    )

                return entries[query_type]

        result = await asyncio.to_thread(run)

        if not result:
            raise ValueError(
                "YouTube result not found"
            )

        vidid = result["id"]

        duration = int(
            result.get("duration") or 0
        )

        duration_min = (
            f"{duration // 60}:"
            f"{duration % 60:02d}"
            if duration
            else "00:00"
        )

        thumb = (
            result.get("thumbnail")
            or (
                f"https://i.ytimg.com/vi/"
                f"{vidid}/hqdefault.jpg"
            )
        )

        return (
            result.get(
                "title",
                "Unknown Title",
            ),
            duration_min,
            thumb,
            vidid,
        )

    async def download(
        self,
        link: str,
        mystic,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ):
        url = (
            self.base + str(link)
            if videoid
            else _clean_youtube_url(link)
        )

        try:
            if video:
                file_path = await download_video(url)
            else:
                file_path = await download_song(url)

            if file_path:
                return file_path, True

            return None, False

        except Exception:
            return None, False


YouTube = YouTubeAPI()
