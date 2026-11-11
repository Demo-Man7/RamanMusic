import re
from os import getenv
from dotenv import load_dotenv
from pyrogram import filters

# Load environment variables from .env file
load_dotenv()

# ── Core bot config ────────────────────────────────────────────────────────────
API_ID = int(getenv("API_ID", 27798659))
API_HASH = getenv("API_HASH", "26100c77cee02e5e34b2bbee58440f86")
BOT_TOKEN = getenv("BOT_TOKEN")

OWNER_ID = int(getenv("OWNER_ID"))
OWNER_LINK = getenv("OWNER_LINK")
BOT_USERNAME = getenv("BOT_USERNAME")
BOT_NAME = getenv("BOT_NAME")
ASSUSERNAME = getenv("ASSUSERNAME")

# ── Database & logging ─────────────────────────────────────────────────────────
MONGO_DB_URI = getenv("MONGO_DB_URI")
LOGGER_ID = int(getenv("LOGGER_ID"))

# ── Limits (durations in min/sec; sizes in bytes) ──────────────────────────────
DURATION_LIMIT_MIN = int(getenv("DURATION_LIMIT", 99999))
SONG_DOWNLOAD_DURATION = int(getenv("SONG_DOWNLOAD_DURATION", "99999"))
SONG_DOWNLOAD_DURATION_LIMIT = int(getenv("SONG_DOWNLOAD_DURATION_LIMIT", "99999"))
TG_AUDIO_FILESIZE_LIMIT = int(getenv("TG_AUDIO_FILESIZE_LIMIT", "157286400"))
TG_VIDEO_FILESIZE_LIMIT = int(getenv("TG_VIDEO_FILESIZE_LIMIT", "1288490189999"))
PLAYLIST_FETCH_LIMIT = int(getenv("PLAYLIST_FETCH_LIMIT", "100"))

# ── External APIs ──────────────────────────────────────────────────────────────
API_URL = getenv("API_URL")        # optional
API_KEY = getenv("API_KEY")        # optional
DEEP_API = getenv("DEEP_API")      # optional
REPLICATE_API_TOKEN = getenv("REPLICATE_API_TOKEN")  # optional
REPLICATE_API_TOKENS = getenv("REPLICATE_API_TOKENS", "")  # optional comma-separated pool
GENVID_USE_PUBLIC_FALLBACKS = getenv("GENVID_USE_PUBLIC_FALLBACKS", "0")
HF_TOKEN = getenv("HF_TOKEN")  # optional
HF_TOKENS = getenv("HF_TOKENS", "")  # optional comma-separated pool
OCR_SPACE_API_KEY = getenv("OCR_SPACE_API_KEY", "helloworld")  # optional shared free key

# Vars For API End Pont.
ARC_API_URL = getenv("ARC_API_URL", "https://api.arcmusic.fun")
ARC_API_KEY = getenv("ARC_API_KEY", "ARC4671e290cb3ff11230be62")

# ── Hosting / deployment ───────────────────────────────────────────────────────
HEROKU_APP_NAME = getenv("HEROKU_APP_NAME")
HEROKU_API_KEY = getenv("HEROKU_API_KEY")

# ── Git / updates ──────────────────────────────────────────────────────────────
UPSTREAM_REPO = getenv("UPSTREAM_REPO", "https://github.com/Demo-Man7/RamanMusic")
UPSTREAM_BRANCH = getenv("UPSTREAM_BRANCH", "main")
GIT_TOKEN = getenv("GIT_TOKEN")  # needed if repo is private

# ── Support links ──────────────────────────────────────────────────────────────
SUPPORT_CHANNEL = getenv("SUPPORT_CHANNEL", "https://t.me/+NWuw-XNh0EVlNGI1")
SUPPORT_CHAT = getenv("SUPPORT_CHAT", "https://t.me/+5v9dp0IR5KYyZTc1")

# ── Assistant auto-leave ───────────────────────────────────────────────────────
AUTO_LEAVING_ASSISTANT = False
AUTO_LEAVE_ASSISTANT_TIME = int(getenv("ASSISTANT_LEAVE_TIME", "30000"))

# ── Debug ──────────────────────────────────────────────────────────────────────
DEBUG_IGNORE_LOG = True

# ── Spotify (optional) ─────────────────────────────────────────────────────────
SPOTIFY_CLIENT_ID = getenv("SPOTIFY_CLIENT_ID", "22b6125bfe224587b722d6815002db2b")
SPOTIFY_CLIENT_SECRET = getenv("SPOTIFY_CLIENT_SECRET", "c9c63c6fbf2f467c8bc68624851e9773")

# ── Session strings (optional) ─────────────────────────────────────────────────
STRING1 = getenv("STRING_SESSION")
STRING2 = getenv("STRING_SESSION2")
STRING3 = getenv("STRING_SESSION3")
STRING4 = getenv("STRING_SESSION4")
STRING5 = getenv("STRING_SESSION5")

# ── Media assets ───────────────────────────────────────────────────────────────
START_VIDS = [
"https://files.catbox.moe/5dc4r1.jpg",
"https://files.catbox.moe/8dx37s.jpg",
"https://files.catbox.moe/9jfiap.jpg",
"https://files.catbox.moe/csdelk.jpg",
"https://files.catbox.moe/ma73xg.jpg",
]

# welcome Media assets 
WEL_VIDS = [
"https://graph.org/file/aee93acfc99ff17e094a7-3e96c75f9bcb0dacde.jpg",
"https://graph.org/file/cb0758c395ca82dfc3a6d-d6a5f3d5ac2f0484dd.jpg",
]

STICKERS = [
    "CAACAgUAAxkBAAFOuWNqUMj28Rrfpr3APoGQH5oC2qGq7wACwyAAAh7UeVa0AcYt3xU9tzwE",
    "CAACAgUAAxkBAAFOzY5qUf7pqrHwL11t17WP478cstKPAQACOhsAAm8FeVa4Vkbih4qtXzwE",
]
HELP_IMG_URL = "https://graph.org/file/78b55a06dcf988a7450c6-85c42d0143fc5cfe23.jpg"
PING_VID_URL = "https://graph.org/file/78b55a06dcf988a7450c6-85c42d0143fc5cfe23.jpg"
PLAYLIST_IMG_URL = "https://graph.org/file/78b55a06dcf988a7450c6-85c42d0143fc5cfe23.jpg"
STATS_VID_URL = "https://graph.org/file/78b55a06dcf988a7450c6-85c42d0143fc5cfe23.jpg"
TELEGRAM_AUDIO_URL = "https://graph.org/file/04bd59e594e57ddbe4bdf-d6b9f8986a9c47ea0f.jpg"
TELEGRAM_VIDEO_URL = "https://graph.org/file/6113efcbbf9bfdff42989-d08059a184b881ce29.jpg"
STREAM_IMG_URL = "https://graph.org/file/e4f3f2ca893b5f803813d-85226e9dbf2c1ba47c.jpg"
SOUNCLOUD_IMG_URL = "https://graph.org/file/bd312919bc588df051f1f-33745f4d122a8880f1.jpg"
YOUTUBE_IMG_URL = "https://graph.org/file/e4f3f2ca893b5f803813d-85226e9dbf2c1ba47c.jpg"
SPOTIFY_ARTIST_IMG_URL = SPOTIFY_ALBUM_IMG_URL = SPOTIFY_PLAYLIST_IMG_URL = YOUTUBE_IMG_URL
# ── Helpers ────────────────────────────────────────────────────────────────────
def time_to_seconds(time: str) -> int:
    return sum(int(x) * 60**i for i, x in enumerate(reversed(time.split(":"))))

DURATION_LIMIT = time_to_seconds(f"{DURATION_LIMIT_MIN}:00")

# ───── Bot Introduction Messages ───── #
AYU = ["💞", "🦋", "🔍", "🧪", "⚡️", "🔥", "🎩", "🌈", "🍷", "🥂", "🥃", "🕊️", "🪄", "💌", "🧨"]
AYUV = [
    "**★ 𝐇єʏ {0} ,**\n\n**⋟ 𝐈 ᴧϻ {1} ᴧ ϻᴜsɪᴄ + ϻᴧηᴧɢєϻєηт ʙσт 𝟺 ɢʀσᴜᴘ/ᴄʜᴧηηєʟ 🚀**\n\n**<u>✦ 𝐊єʏ 𝐅єᴧтᴜʀєs :-</u>**\n\n**▸ 𝐏ʟᴧʏ sσηɢ ɪη ᴠσɪᴄє ᴄʜᴧᴛ.**\n**▸ 𝐈 ᴄᴧη єᴧsɪʟʏ ʜᴧηᴅʟє ɢʀσᴜᴘs.**\n**▸ 𝐅ᴧsт sϻσσтʜ ʜᴅ ǫᴜᴧʟɪтʏ ησ ᴧᴅs.**\n**▸ 𝐇ɪsᴛᴏʀʏ, ɪɴғᴏ, ᴧηтɪ ғʟσσᴅ ᴧᴄтɪσηs.**\n**▸ 𝐌σʀє ᴅєтᴧɪʟs → тᴧᴘ ʜєʟᴘ ʙᴜттση.**\n**────────────────────────**"
]    

# ── Runtime structures ─────────────────────────────────────────────────────────
BANNED_USERS = filters.user()
adminlist, lyrical, votemode, autoclean, confirmer = {}, {}, {}, [], {}

# ── Minimal validation ─────────────────────────────────────────────────────────
if SUPPORT_CHANNEL and not re.match(r"^https?://", SUPPORT_CHANNEL):
    raise SystemExit("[ERROR] - Invalid SUPPORT_CHANNEL URL. Must start with https://")

if SUPPORT_CHAT and not re.match(r"^https?://", SUPPORT_CHAT):
    raise SystemExit("[ERROR] - Invalid SUPPORT_CHAT URL. Must start with https://")

