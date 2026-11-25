"""Scam signs that can be read straight off the text, with a plain-language label for each.

score() is the first opinion on every message: microseconds, no model, word-boundary matching on capped text. The
labels are what "Check a message" shows people as the reasons for its verdict. The model (app.brain) gives the
second opinion; app.detect combines them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import MAX_TEXT


@dataclass(frozen=True)
class Sign:
    key: str
    label: str
    weight: float
    pattern: re.Pattern


def _p(*words: str) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)


SIGNS: tuple[Sign, ...] = (
    Sign("pay", "Asks you to pay money", 0.2,
         _p(r"pay", r"payment", r"transfer", r"deposit", r"fee", r"fees", r"charges?", r"fine", r"tax", r"refundable")),
    Sign("secret", "Asks for your OTP, PIN or password", 0.35,
         _p(r"(?:share|send|tell|give|enter)\s+(?:the\s+|your\s+)?(?:otp|pin|password|cvv|mpin)", r"otp\s+(?:batao|bhejo)")),
    Sign("kyc", "Says your KYC, PAN or Aadhaar must be updated", 0.25,
         _p(r"kyc", r"re-?kyc", r"pan\s+(?:card\s+)?update", r"aadhaa?r\s+update", r"update\s+(?:your\s+)?(?:pan|kyc)")),
    Sign("blocked", "Says your account, card or connection will be blocked", 0.25,
         _p(r"(?:will\s+be\s+|is\s+|been\s+)?(?:blocked|suspended|deactivated|disconnected|frozen)", r"disconnection")),
    Sign("urgent", "Pushes you to act right now", 0.15,
         _p(r"urgent(?:ly)?", r"immediately", r"hurry", r"asap", r"today\s+only", r"within\s+\d+\s+(?:hours?|minutes?)",
            r"last\s+chance", r"tonight", r"jaldi", r"turant", r"warna")),
    Sign("threat", "Threatens arrest, police or legal action", 0.3,
         _p(r"arrest(?:ed)?", r"warrant", r"jail", r"money\s+laundering", r"cyber\s+police", r"legal\s+action", r"fir")),
    Sign("returns", "Promises guaranteed profit or returns", 0.25,
         _p(r"guaranteed?", r"assured\s+returns?", r"\d+\s?%\s+(?:daily|weekly|monthly|returns?|profit)",
            r"double\s+your\s+money", r"profit\s+(?:is\s+)?ready")),
    Sign("invest", "Pitches trading, crypto or stocks", 0.1,
         _p(r"trading", r"stocks?", r"crypto", r"bitcoin", r"usdt", r"forex", r"ipo", r"vip\s+group")),
    Sign("install", "Asks you to install or download an app", 0.2,
         _p(r"install", r"download", r"apk", r"anydesk", r"teamviewer", r"quicksupport", r"screen\s+shar(?:e|ing)")),
    Sign("pretend", "Claims to be a bank, courier, police or a government body", 0.15,
         _p(r"bank", r"rbi", r"sebi", r"customs", r"courier", r"income\s+tax", r"trai", r"npci", r"uidai",
            r"electricity\s+(?:board|department|officer)", r"customer\s+care")),
    Sign("prize", "Says you won a prize, cashback or reward", 0.2,
         _p(r"lottery", r"jackpot", r"winner", r"you\s+(?:have\s+)?won", r"prize", r"cashback", r"lucky\s+draw")),
    Sign("job", "Offers easy money for simple online tasks", 0.2,
         _p(r"part[\s-]?time\s+job", r"work\s+from\s+home", r"like\s+videos", r"simple\s+tasks?", r"earn\s+(?:rs\.?\s?)?\d+")),
    Sign("link", "Contains a link", 0.1, re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)),
    Sign("upi", "Contains a UPI ID to pay to", 0.1, re.compile(r"\b[\w.-]{2,}@[a-z]{2,}\b(?!\.)", re.IGNORECASE)),
)

# Real banks and services say these; on their own they point away from a scam.
SAFE_CUES = _p(r"do\s+not\s+share", r"don'?t\s+share", r"never\s+share", r"never\s+asks?\s+for")

SCAM_TYPES = (
    ("kyc_phishing", _p(r"kyc", r"pan\s+card", r"aadhaa?r", r"account\s+will\s+be\s+blocked")),
    ("delivery_phishing", _p(r"parcel", r"customs", r"courier", r"delivery\s+failed", r"held\s+at", r"shipment")),
    ("investment_trading", _p(r"trading", r"profit", r"returns?", r"sebi", r"stocks?", r"invest(?:ment)?", r"withdraw")),
    ("job_task", _p(r"part[\s-]?time", r"like\s+videos", r"tasks?", r"work\s+from\s+home")),
    ("utility_bill", _p(r"electricity", r"disconnect(?:ion|ed)?", r"power\s+cut", r"consumer\s+number", r"bill")),
    ("digital_arrest", _p(r"cyber\s+police", r"money\s+laundering", r"arrest", r"cbi", r"narcotics", r"warrant")),
    ("lottery_prize", _p(r"lottery", r"prize", r"winner", r"lucky\s+draw", r"jackpot")),
    ("upi_collect", _p(r"upi", r"collect\s+request", r"scan\s+(?:this|the)\s+qr")),
)


def score(text: str) -> tuple[float, list[Sign]]:
    """(0 to 1, the signs found). Safe cues lower the score when nothing asks for money or a secret."""
    text = (text or "")[:MAX_TEXT]
    hits = [s for s in SIGNS if s.pattern.search(text)]
    value = sum(s.weight for s in hits)
    keys = {s.key for s in hits}
    if SAFE_CUES.search(text) and not keys & {"pay", "secret", "link", "upi", "install"}:
        value -= 0.5
    return max(0.0, min(1.0, round(value, 2))), hits


def scam_type(text: str) -> str:
    for name, pattern in SCAM_TYPES:
        if pattern.search(text or ""):
            return name
    return "other"


def looks_safe(text: str) -> bool:
    return bool(SAFE_CUES.search(text or ""))
