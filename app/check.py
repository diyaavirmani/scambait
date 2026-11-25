"""Check a message: anyone pastes a suspicious SMS or WhatsApp text and gets a verdict in plain words.

POST /api/check {"text"} -> {verdict, headline, scam_type, scam_words, risk, red_flags, intel, links,
                             links_not_opened, apks, advice}
    The same detection as the live chats runs on the text. Nothing is opened yet: `links` are the links Kane may open
    (at most three; practice-lab links always, real links only with LIVE_INVESTIGATION=1), `links_not_opened` are
    the others with the reason, and `apks` are app files, which are never opened.
POST /api/check/link {"url"} -> the queued investigation row (its `id` is the investigation id)
    The person asks Kane to open one link before paying. The link is checked again here; app files (APK) and links
    that may not be opened are refused with a reason. Kane runs in the background with no case, on channel "check":
    the page follows kane.started / kane.finished on /api/events by investigation id, or polls
    GET /api/investigations/{id}.
No case is opened for a check: only the investigations are stored.
"""
from __future__ import annotations

import asyncio
from typing import Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import detect, limits
from app.intel import extract
from app.investigate.safety import check_link
from app.models import MAX_TEXT
from app.runtime import get_runtime

router = APIRouter()

MAX_LINKS = 3
LINK_PER_MINUTE = 5  # Kane runs asked for per client per minute: each one drives a real browser
APK_FLAG = "Contains an app file (APK), a common way to take over phones"
APP_EXT = (".apk", ".xapk", ".aab", ".ipa")
APK_REFUSED = ("This link downloads an app (an APK file). Kane never opens app files: an app from a link can take "
               "over your phone. Do not install it.")
NOT_LIVE = "This server only opens practice links."
KANE_OFF = "Kane is turned off on this server, so it cannot open links right now."

KIND_WORDS = {
    "kyc_phishing": "a fake KYC update scam", "delivery_phishing": "a fake parcel or customs fee scam",
    "investment_trading": "a fake trading or investment scam", "job_task": "a fake part-time task job scam",
    "utility_bill": "a fake electricity bill scam", "digital_arrest": "a 'digital arrest' scam",
    "lottery_prize": "a fake prize or lottery scam", "upi_collect": "a UPI payment scam",
    "customer_care": "a fake customer care scam", "loan_offer": "a fake loan offer", "sextortion": "a sextortion scam",
}
ADVICE_SCAM = [
    "Do not click the link, call the number or reply.",
    "Never share an OTP, UPI PIN, card number or CVV. Banks and the government never ask for them.",
    "Report it at cybercrime.gov.in or call 1930 (free, 24x7).",
    "Already paid or shared details? Call 1930 and your bank right away: the first hour matters most.",
]
ADVICE_SAFE = [
    "No scam signs found, but never share an OTP, UPI PIN or card details with anyone.",
    "If something feels off, call the company on the number printed on its official website or card.",
]


class CheckRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_TEXT)


class LinkRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2000)


def headline(verdict: str, scam_type: str) -> str:
    if verdict == "scam":
        return f"This looks like {KIND_WORDS.get(scam_type, 'a scam')}. Do not click, pay or share any code."
    if verdict == "not_scam":
        return "No scam signs found in this message."
    return "We could not decide. Treat this message with care."


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


def is_app_link(url: str) -> bool:
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return False
    return parts.path.lower().endswith(APP_EXT) or parts.query.lower().endswith(APP_EXT)


async def refusal(url: str) -> Optional[str]:
    """None when Kane may open the link now, otherwise the reason in plain words."""
    if is_app_link(url):
        return APK_REFUSED
    s = get_runtime().settings
    # check_link may look up the host name, so it runs off the event loop
    reason = await asyncio.to_thread(check_link, url, public_base_url=s.public_base_url, live=s.live_investigation)
    if reason is not None:
        return NOT_LIVE if "LIVE_INVESTIGATION" in reason else reason
    return None if s.kane_enabled else KANE_OFF


@router.post("/api/check")
async def check_message(body: CheckRequest, request: Request) -> dict:
    if not limits.allow("check:" + _client(request)):
        raise HTTPException(status_code=429, detail="Too many checks. Wait a minute and try again.")
    text = body.text.strip()
    v = await detect.judge([{"role": "scammer", "text": text}], None)
    intel = extract(text)
    apks = list(dict.fromkeys(i.value for i in intel if i.kind == "apk" or (i.kind == "url" and is_app_link(i.value))))
    flags = list(v.red_flags) + ([APK_FLAG] if apks else [])
    links: list[str] = []
    not_opened: list[dict] = []
    for url in dict.fromkeys(i.value for i in intel if i.kind == "url" and i.value not in apks):
        if len(links) + len(not_opened) >= MAX_LINKS:
            break
        reason = await refusal(url)
        if reason is None:
            links.append(url)
        else:
            not_opened.append({"url": url, "reason": reason})
    return {
        "verdict": v.label, "headline": headline(v.label, v.scam_type), "scam_type": v.scam_type,
        "scam_words": KIND_WORDS.get(v.scam_type, "") if v.label == "scam" else "", "risk": v.risk,
        "red_flags": flags, "intel": [i.model_dump() for i in intel], "links": links, "links_not_opened": not_opened,
        "apks": apks, "advice": ADVICE_SAFE if v.label == "not_scam" else ADVICE_SCAM,
    }


@router.post("/api/check/link")
async def investigate_link(body: LinkRequest, request: Request) -> dict:
    from app.investigate import start_investigation
    from app.investigate.api import _public

    if not limits.allow("check-link:" + _client(request), LINK_PER_MINUTE):
        raise HTTPException(status_code=429, detail="Too many links checked. Wait a minute and try again.")
    url = body.url.strip()
    reason = await refusal(url)
    if reason is not None:
        raise HTTPException(status_code=503 if reason == KANE_OFF else 400, detail=reason)
    return _public(await start_investigation(url, None, "check"))
