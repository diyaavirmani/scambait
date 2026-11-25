"""Check a message: anyone pastes a suspicious SMS or WhatsApp text and gets a verdict in plain words.

POST /api/check {"text"} -> {verdict, headline, scam_type, risk, red_flags, intel, investigations, advice}
The same detection as the live chats runs on the text, and up to three links in it go to the Kane investigator
(practice-lab links always, real links only with LIVE_INVESTIGATION=1). APK links are listed, never opened.
Investigations run in the background; the page polls GET /api/investigations/{id} for what Kane proved.
No case is opened for a check: only the investigations are stored.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import detect, limits
from app.intel import extract
from app.models import MAX_TEXT

router = APIRouter()

MAX_LINKS = 3
APK_FLAG = "Contains an app file (APK), a common way to take over phones"

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


def headline(verdict: str, scam_type: str) -> str:
    if verdict == "scam":
        return f"This looks like {KIND_WORDS.get(scam_type, 'a scam')}. Do not click, pay or share any code."
    if verdict == "not_scam":
        return "No scam signs found in this message."
    return "We could not decide. Treat this message with care."


@router.post("/api/check")
async def check_message(body: CheckRequest, request: Request) -> dict:
    from app.investigate import start_investigation
    from app.investigate.api import _public

    if not limits.allow("check:" + (request.client.host if request.client else "?")):
        raise HTTPException(status_code=429, detail="Too many checks. Wait a minute and try again.")
    text = body.text.strip()
    v = await detect.judge([{"role": "scammer", "text": text}], None)
    intel = extract(text)
    apks = {i.value for i in intel if i.kind == "apk"}
    flags = list(v.red_flags) + ([APK_FLAG] if apks else [])
    links = [i.value for i in intel if i.kind == "url" and i.value not in apks]
    investigations = [_public(await start_investigation(url, None, "web")) for url in links[:MAX_LINKS]]
    return {
        "verdict": v.label, "headline": headline(v.label, v.scam_type), "scam_type": v.scam_type, "risk": v.risk,
        "red_flags": flags, "intel": [i.model_dump() for i in intel], "investigations": investigations,
        "advice": ADVICE_SAFE if v.label == "not_scam" else ADVICE_SCAM,
    }
