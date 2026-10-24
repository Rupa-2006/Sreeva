import re
from decimal import Decimal, InvalidOperation
from urllib.parse import quote


def normalize_phone(raw):
    """Return a clean 10-digit Indian mobile number, or '' if invalid.

    Accepts '98480 12345', '+91-98480-12345', '919848012345', '09848012345'.
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and digits[0] in "6789":
        return digits
    return ""


def whatsapp_url(phone, text):
    """Click-to-chat link. Opens WhatsApp with the message ready; no API key needed."""
    digits = normalize_phone(phone)
    if not digits:
        return ""
    return f"https://wa.me/91{digits}?text={quote(text)}"


def format_inr(value):
    """1234567.5 -> '₹12,34,567.50' (Indian digit grouping)."""
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = "-" if amount < 0 else ""
    whole, frac = f"{abs(amount):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    return f"{sign}₹{whole}" + ("" if frac == "00" else f".{frac}")
