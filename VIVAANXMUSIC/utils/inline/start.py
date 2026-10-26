import config
from VIVAANXMUSIC import app
from VIVAANXMUSIC.button_styles import primary_button, success_button, danger_button


def start_panel(_):
    buttons = [
        [
            success_button(
                text=_["S_B_1"],
                url=f"https://t.me/{app.username}?startgroup=true",
            ),
            danger_button(
                text=_["S_B_2"],
                url=config.SUPPORT_CHANNEL,
            ),
        ],
        [
            primary_button(
                text=_["S_B_4"],
                url=config.SUPPORT_CHAT,
            ),
        ],
    ]
    return buttons


def private_panel(_):
    buttons = [
        [
            success_button(
                text=_["S_B_1"],
                url=f"https://t.me/{app.username}?startgroup=true",
            )
        ],
        [
            primary_button(
                text=_["S_B_7"],
                url=(
                    f"https://t.me/{config.OWNER_USERNAME.lstrip('@')}"
                    if getattr(config, "OWNER_USERNAME", None)
                    else f"tg://user?id={config.OWNER_ID}"
                ),
            ),
            primary_button(
                text=_["S_B_4"],
                url=config.SUPPORT_CHAT,
            ),
        ],
        [
            primary_button(
                text=_["S_B_3"],
                callback_data="open_help",
            ),
        ],
        [
            danger_button(
                text=_["S_B_2"],
                url=config.SUPPORT_CHANNEL,
            ),
        ],
    ]
    return buttons
