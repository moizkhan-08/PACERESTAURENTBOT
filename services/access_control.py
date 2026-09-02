import re
from config import settings


def normalize_phone(phone: str) -> str:
    """Extract clean digits from JID or formatted phone number."""
    if not phone:
        return ""
    number = phone.split("@")[0]
    return re.sub(r"\D", "", number)


def is_number_allowed(sender_jid: str) -> bool:
    """
    Checks if a sender is allowed when ALLOWED_NUMBERS_ONLY is enabled.
    In production mode (ALLOWED_NUMBERS_ONLY=False), all senders are accepted.
    """
    if not settings.ALLOWED_NUMBERS_ONLY:
        return True

    allowed_raw = [n.strip() for n in settings.ALLOWED_NUMBERS.split(",") if n.strip()]
    allowed_numbers = {normalize_phone(n) for n in allowed_raw}
    sender_clean = normalize_phone(sender_jid)
    return sender_clean in allowed_numbers
