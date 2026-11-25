"""Find identifiers in a scammer's message: UPI IDs, phones, bank accounts, IFSC codes, links, APKs, emails, cards
and amounts. Every pattern is linear (no nested repetition) and runs on text capped at MAX_TEXT, so a long or hostile
message cannot freeze the server. Each candidate is validated before it is returned:

- a UPI handle has letters only after the @ (so "call me at 5pm" or "x@5pm" is never a UPI ID), and an address with
  a dotted domain is an email instead;
- a 10-digit number starting 6 to 9 (with or without +91) is a phone; any other 9 to 18 digit number is a bank
  account, unless it is a card number (13 to 19 digits that pass the Luhn check) or the digits of a phone already
  found in the same message;
- a link ending in .apk is also reported as an APK.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from app.models import MAX_TEXT, Intel

URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s<>\"'()]+", re.IGNORECASE)
HANDLE_RE = re.compile(r"(?<![\w.@-])([a-z0-9][a-z0-9._-]{1,63})@([a-z0-9-]{2,32}(?:\.[a-z0-9-]{2,32})*)(?![\w@-])",
                       re.IGNORECASE)
PHONE_RE = re.compile(r"(?<![\d+])(?:\+?91[\s-]?|0)?([6-9]\d{4})[\s-]?(\d{5})(?!\d)")
DIGITS_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){8,22}(?!\d)")
IFSC_RE = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")
AMOUNT_RE = re.compile(r"(?:(?:rs\.?|inr|₹)\s?(\d[\d,]*(?:\.\d{1,2})?))|(?:(\d[\d,]*)\s?(?:rupees|rs\b|/-))",
                       re.IGNORECASE)
TRAILING = ".,;:!?)]}'\""


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def _clean_url(raw: str) -> str:
    url = raw.rstrip(TRAILING)
    return "http://" + url if url.lower().startswith("www.") else url


def extract(text: str) -> list[Intel]:
    """Validated identifiers in one message, each once, in the order they appear."""
    text = (text or "")[:MAX_TEXT]
    found: list[tuple[int, Intel]] = []
    taken: list[tuple[int, int]] = []  # spans already used by a link or handle, so their digits are not re-read

    def add(pos: int, kind: str, value: str) -> None:
        found.append((pos, Intel(kind=kind, value=value)))

    for m in URL_RE.finditer(text):
        url = _clean_url(m.group(0))
        if urlsplit(url).hostname:
            add(m.start(), "url", url)
            if urlsplit(url).path.lower().endswith(".apk"):
                add(m.start(), "apk", url)
            taken.append(m.span())

    for m in HANDLE_RE.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        user, domain = m.group(1), m.group(2)
        if "." in domain:
            add(m.start(), "email", f"{user}@{domain}".lower())
        elif domain.isalpha():
            add(m.start(), "upi", f"{user}@{domain}".lower())
        taken.append(m.span())

    phones = set()
    for m in PHONE_RE.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        number = m.group(1) + m.group(2)
        phones.add(number)
        add(m.start(), "phone", "+91" + number)
        taken.append(m.span())

    for m in DIGITS_RE.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        digits = re.sub(r"\D", "", m.group(0))
        if digits[-10:] in phones and len(digits) <= 12:
            continue
        if 13 <= len(digits) <= 19 and _luhn(digits):
            add(m.start(), "card", digits)
        elif 9 <= len(digits) <= 18:
            add(m.start(), "bank_account", digits)

    for m in IFSC_RE.finditer(text.upper()):
        add(m.start(), "ifsc", m.group(1))

    for m in AMOUNT_RE.finditer(text):
        raw = (m.group(1) or m.group(2) or "").replace(",", "")
        if raw and float(raw) > 0:
            add(m.start(), "amount", raw.rstrip("0").rstrip(".") if "." in raw else raw)

    out, seen = [], set()
    for _, item in sorted(found, key=lambda x: x[0]):
        key = (item.kind, item.value)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def normalise(kind: str, value: str) -> str:
    """The form used to match the same identifier across cases."""
    v = (value or "").strip()
    if kind in ("upi", "email"):
        return v.lower()
    if kind == "phone":
        return re.sub(r"\D", "", v)[-10:]
    if kind in ("bank_account", "card", "amount"):
        return re.sub(r"\D", "", v)
    if kind in ("url", "apk"):
        parts = urlsplit(v.lower())
        return (parts.hostname or "") + parts.path.rstrip("/")
    return v.lower()
