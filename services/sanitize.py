import re

_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_MAX_LEN = 300


def sanitize_free_text(text: str) -> str:
    """
    Sanitizes free-text customer inputs (e.g. delivery_address, notes, names)
    before embedding them into outbound WhatsApp messages or notification dispatches.
    Strips zero-width injection characters, neutralizes markdown formatting fences,
    and caps total string length.
    """
    if not text:
        return ""
    text = str(text)
    text = _ZERO_WIDTH.sub("", text)
    text = text.replace("`", "'")
    text = text.strip()[:_MAX_LEN]
    return text
