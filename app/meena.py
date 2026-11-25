"""Meena: a slow, worried, 60-something woman who keeps scammers talking and never gives them anything real.

This module holds what Meena knows and how she must behave; app.brain turns that into a reply (with a model, or
from a script in offline mode). Whatever produced the reply, guard() runs on it before anyone sees it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_REPLY = 350
DEFLECT = "Bot? Beta, I am just slow with this phone. What were you saying?"
EMPTY = "Sorry, I did not understand. Can you say that again slowly?"

# Which detail Meena should try to draw out next, in this order.
WANTED = ("upi", "phone", "bank_account", "url")
ASK_FOR = {
    "upi": "the UPI ID to pay to (ask them to spell it slowly)",
    "phone": "a number to call them back on",
    "bank_account": "a bank account and IFSC, in case UPI does not work",
    "url": "the website (say the link will not open and ask them to type it again)",
}

HINGLISH = re.compile(r"\b(?:hai|hain|kya|nahi|nahin|aap|aapka|karo|karna|bhejo|batao|jaldi|abhi|paisa|paise|"
                      r"beta|ji|mera|meri|apna|kijiye|warna|haan|theek)\b", re.IGNORECASE)
DEVANAGARI = re.compile(r"[ऀ-ॿ]")


@dataclass
class Context:
    """Everything Meena may use for one reply."""
    history: list[dict]                 # [{"role": "scammer"|"persona", "text": ...}], oldest first
    mode: str = "bait"                  # bait | neutral | wrap_up
    facts: list[str] = field(default_factory=list)       # things the scammer said that she can recall
    findings: list[dict] = field(default_factory=list)   # payment pages Kane proved, not yet talked about
    missing: list[str] = field(default_factory=list)     # identifiers not collected yet (keys of ASK_FOR)
    language: str = "en"                # en | hinglish | hi

    @property
    def last(self) -> str:
        return next((m["text"] for m in reversed(self.history) if m["role"] == "scammer"), "")

    @property
    def said(self) -> set[str]:
        return {m["text"] for m in self.history if m["role"] == "persona"}


def language_of(text: str) -> str:
    if DEVANAGARI.search(text or ""):
        return "hi"
    return "hinglish" if len(HINGLISH.findall(text or "")) >= 2 else "en"


def finding_sentence(inv: dict) -> str:
    """What Kane saw on a scam page, in plain words, for Meena's next reply."""
    bits = []
    if inv.get("claims_to_be"):
        bits.append(f"the page says it is {inv['claims_to_be']}")
    if inv.get("amount"):
        bits.append(f"it asks to pay Rs {inv['amount']}")
    if inv.get("payee"):
        kind = "account" if inv.get("payee_kind") == "bank_account" else "UPI ID"
        bits.append(f"the money goes to the {kind} {inv['payee']}")
    asked = [a for a in (inv.get("asked_for") or []) if a]
    if asked:
        bits.append("it asked for " + ", ".join(asked))
    return "; ".join(bits) or "it opens a payment page"


# ---------- the guard ----------
EM_DASH = chr(0x2014)
EMOJI = re.compile("[" + "".join(chr(a) + "-" + chr(b) for a, b in ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0x2300, 0x23FF), (0xFE0F, 0xFE0F), (0x200D, 0x200D))) + "]")  # pictographs, built from code points
LEAK = re.compile(
    r"\b(?:i\s*(?:am|'m)\s+(?:an?\s+)?(?:ai|a\.i\.|bot|chat\s*bot|robot|language\s+model|assistant|program|computer)\b"
    r"|as\s+an?\s+(?:ai|language\s+model|assistant)\b|language\s+model|\bllm\b|system\s+prompt|my\s+(?:instructions|"
    r"prompt|programming|rules)|honey\s*pot|scam\s*-?\s*bait|cerebras|openai|chatgpt|\bgpt\b|gpt-|qwen|anthropic|"
    r"claude|kane|artificial\s+intelligence|i\s+was\s+(?:instructed|programmed|told\s+to\s+pretend))",
    re.IGNORECASE)
URL = re.compile(r"(?:https?://|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|in|net|org|co|io|app|xyz|info|"
                 r"example)\b\S*", re.IGNORECASE)
HANDLE = re.compile(r"\b[\w.-]+@[\w.-]+\b")
NUMBER = re.compile(r"\d(?:[\s-]?\d){5,}")
PLACEHOLDER = re.compile(r"\s*\[[^\]]{0,40}\]")


def guard(text: str) -> tuple[str, list[str]]:
    """Make a reply safe to send: no AI admission or prompt leak, no real-looking number, UPI ID or link, no em
    dashes, emojis or bracket placeholders, at most MAX_REPLY characters. Returns (text, what was changed)."""
    flags: list[str] = []
    text = (text or "").strip()
    if EM_DASH in text or EMOJI.search(text):
        flags.append("style")
        text = EMOJI.sub("", text.replace(f" {EM_DASH} ", ", ").replace(EM_DASH, ", "))
    if LEAK.search(text):
        return DEFLECT, flags + ["leak"]
    masked = URL.sub("that link thing, my grandson does those", text)
    masked = HANDLE.sub("that thing with the at sign, I cannot read it", masked)
    masked = NUMBER.sub("nine eight... wait, my glasses", masked)
    if masked != text:
        flags.append("masked")
        text = masked
    if PLACEHOLDER.search(text):
        flags.append("placeholder")
        text = PLACEHOLDER.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    if len(text) > MAX_REPLY:
        flags.append("cut")
        cut = text[:MAX_REPLY]
        end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
        text = cut[: end + 1] if end > 80 else cut.rsplit(" ", 1)[0] + "..."
    return (text or EMPTY), flags


# ---------- lines used when no model answers (offline mode, or the model failed) ----------
STALL = [
    "Oh dear, wait, I am putting on my glasses. Who is this again?",
    "My phone is very slow today. Can you tell me once more, slowly?",
    "Someone is at the door, one minute. What should I do first?",
    "I am not good with these things. Is it safe, beta?",
    "My grandson usually helps me with this. Can you explain it simply?",
    "Sorry, the screen went dark. What were you saying about the money?",
    "I wrote it down but I cannot read my own writing. Can you repeat?",
    "Wait, my tea is boiling over. You said it is urgent?",
    "My son told me never to do bank things on the phone. Are you sure this is the bank?",
    "The phone is showing some warning in red. Is that normal?",
    "Which button do I press now? There are so many.",
    "I only have my pension account. Will that work?",
    "Hold on, the power went off for a second. Are you still there?",
    "Can I do this tomorrow at the branch instead?",
]
ASK = {
    "upi": "Which UPI should I pay to? Please spell it, my eyes are weak.",
    "phone": "If it does not work, which number should I call you on? Say it slowly please.",
    "bank_account": "Can I do a bank transfer instead? Which account, and how many digits?",
    "url": "Which website is it? The link is not opening, can you type the name again?",
}
GOODBYE = "My grandson has come home and the battery is dying, I have to go now. Bye."
NEUTRAL = "Okay, thank you. I will see."
CONFUSED = "I do not understand these computer words. Should I go to the bank branch instead?"
