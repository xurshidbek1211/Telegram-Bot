import re

_MD_SPECIAL_RE = re.compile(r"([_*`\[])")


def escape_md(text) -> str:
    """Escape legacy Telegram Markdown special characters in user-generated text.

    Telegram's legacy "Markdown" parse mode treats _ * ` [ as formatting
    entities. Any unescaped/unbalanced occurrence of these characters in
    dynamic content (names, usernames, channel links, etc.) causes
    aiogram.exceptions.TelegramBadRequest: "can't parse entities".
    """
    if text is None:
        return ""
    text = str(text)
    return _MD_SPECIAL_RE.sub(r"\\\1", text)
