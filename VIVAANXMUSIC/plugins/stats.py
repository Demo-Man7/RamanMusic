"""
Enhanced Stats Plugin for VIVAANXMUSIC
"""
import time
from pyrogram import Client, filters
from pyrogram.types import Message
from VIVAANXMUSIC.misc import get_stats, STATS, increment_song_count, increment_video_count, add_user, add_group
from VIVAANXMUSIC.logging import LOGGER

logger = LOGGER(__name__)


def format_uptime(seconds):
    """Format seconds to readable uptime"""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{int(hours)}h {int(minutes)}m {int(secs)}s"


# Legacy /stats handler disabled: Rich handler lives in plugins/tools/stats.py
async def bot_stats(client: Client, message: Message):
    """Send bot statistics"""
    try:
        stats = get_stats()
        uptime = format_uptime(stats["uptime_seconds"])
        
        stats_text = f"""
🎵 **Bot Statistics** 🎵

📊 **Performance Metrics:**
├─ Songs Played: `{stats['songs_played']}`
├─ Videos Played: `{stats['videos_played']}`
├─ Total Plays: `{stats['songs_played'] + stats['videos_played']}`
├─ Users Active: `{stats['users_active']}`
├─ Groups Active: `{stats['groups_active']}`
└─ Uptime: `{uptime}`

✅ Bot is running smoothly!
"""
        
        await message.reply_text(stats_text)
        add_group(message.chat.id)
        add_user(message.from_user.id)
        
    except Exception as e:
        logger.error(f"Error in stats command: {e}")
        await message.reply_text("❌ Error fetching statistics")


# Legacy /ping handler disabled: Rich handler lives in plugins/tools/ping.py
async def ping_pong(client: Client, message: Message):
    """Check bot status"""
    start_time = time.time()
    
    sent_message = await message.reply_text("🏓 Pong!")
    
    end_time = time.time()
    ping_time = (end_time - start_time) * 1000
    
    stats = get_stats()
    uptime = format_uptime(stats["uptime_seconds"])
    
    await sent_message.edit_text(
        f"🏓 **Pong!**\n"
        f"⏱️ Response Time: `{ping_time:.2f}ms`\n"
        f"⏳ Uptime: `{uptime}`\n"
        f"👥 Active Users: `{stats['users_active']}`\n"
        f"📊 Active Groups: `{stats['groups_active']}`"
    )
    
    add_user(message.from_user.id)


# Legacy /help handler disabled: Rich handler lives in plugins/bot/help.py
async def help_command(client: Client, message: Message):
    """Send help message"""
    help_text = """
🎵 **VIVAANXMUSIC - Complete Music Bot** 🎵

**Music Commands:**
├─ `/play` - Play audio in voice chat
├─ `/vplay` - Play video in voice chat
├─ `/song` - Download a song
├─ `/spotify` - Download Spotify track
├─ `/apple` - Download Apple Music track
├─ `/lyrics` - Get song lyrics
├─ `/queue` - Show current queue
└─ `/player` - Player controls

**AI Features:**
├─ `/gpt` - Ask AI assistant
├─ `/claude` - Claude AI
├─ `/geminivision` - Analyze images
└─ `/editimg` - Edit images with AI

**Download Features:**
├─ `/youtube` - Download YouTube
├─ `/insta` - Download Instagram
├─ `/tiktok` - Download TikTok
├─ `/facebook` - Download Facebook
├─ `/x` - Download Twitter/X
└─ `/snap` - Download Snapchat

**Utilities:**
├─ `/weather` - Get weather
├─ `/movie` - Search movies
├─ `/news` - Get latest news
├─ `/ping` - Check bot status
└─ `/stats` - View statistics

**Settings:**
├─ `/settings` - Group settings
├─ `/autoplay` - Toggle autoplay
└─ `/vcnotify` - Toggle notifications

**Encryption:**
├─ `/encrypt` - Encrypt content
└─ `/decrypt` - Decrypt content

🎉 Enhanced version with improved performance!
📧 Contact: @support
"""
    
    await message.reply_text(help_text)
    add_user(message.from_user.id)


__all__ = ["bot_stats", "ping_pong", "help_command"]
