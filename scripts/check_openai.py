"""Check the OpenAI features against the real API, through the app's own client and voice protocol code.

    .venv/bin/python scripts/check_openai.py                    # Decisions, moderation, the report, a live voice session
    .venv/bin/python scripts/check_openai.py --caller call.wav  # also send a recorded caller (mu-law 8 kHz WAV)

Reads OPENAI_API_KEY (and DECISIONS_MODEL, LIVE_MODEL) from the environment or .env, like the app; never prints it.
Make a caller recording on a Mac with:
    say "Your KYC is pending, pay ten rupees today" -o caller.aiff && afconvert -f WAVE -d ulaw@8000 -c 1 caller.aiff call.wav
Costs a few cents of OpenAI usage. Exits 1 if any check fails.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import openai_client as oc  # noqa: E402
from app.brain import REPORT_PROMPT, REPORT_SCHEMA, report_input  # noqa: E402
from app.config import Settings  # noqa: E402
from app.voice import live, persona  # noqa: E402


async def _quiet_emit(*_args, **_kwargs) -> None:
    return None


oc.emit = _quiet_emit  # no event bus here

SCAM = [{"role": "scammer", "text": "Dear customer, your account will be blocked today. Pay Rs 10 to update KYC now."}]
FAMILY = [{"role": "scammer", "text": "Hi aunty, it's Riya. Mom says dinner is at 8 tonight, can you bring the dessert?"}]
REPORT_CASE = {
    "case": {"id": "c_000000000001", "channel": "web", "status": "closed", "verdict": "scam",
             "scam_type": "kyc_phishing", "summary": "", "opened_at": "2026-11-25T08:00:00Z", "messages_from_suspect": 1},
    "transcript": [{"role": "suspect", "text": SCAM[0]["text"], "ts": "2026-11-25T08:00:00Z"}],
    "validated_identifiers": [{"kind": "upi", "value": "bharatunity.kyc@demoupi", "source": "proven by Kane"}],
    "proven_payees": [],
}


def mulaw_frames(path: str) -> list[bytes]:
    raw = Path(path).read_bytes()
    start = raw.find(b"data") + 8
    return [raw[i:i + 160] for i in range(start, len(raw), 160)]  # 20 ms at 8 kHz


async def check_live(s: Settings, caller: str | None) -> dict:
    out = {"events": {}, "meena": "", "caller": "", "audio_s": 0.0, "started_s": None}
    ws = await live.connect(s.openai_api_key)
    t0 = time.monotonic()
    await ws.send(json.dumps(live.start(s.live_model, persona.phone_instructions())))

    async def read() -> None:
        audio = 0
        async for msg in ws:
            ev = json.loads(msg)
            kind = ev.get("type", "?")
            out["events"][kind] = out["events"].get(kind, 0) + 1
            if kind == live.STARTED:
                out["started_s"] = round(time.monotonic() - t0, 1)
                await ws.send(json.dumps(live.commentary(persona.PICK_UP)))
            elif kind == live.AUDIO_OUT:
                audio += len(base64.b64decode(ev.get("delta", "")))
                out["audio_s"] = round(audio / 8000, 1)
            elif kind == live.MEENA_TEXT:
                out["meena"] += ev.get("delta", "")
            elif kind == live.CALLER_TEXT:
                out["caller"] += ev.get("delta", "")
            elif kind in (live.ERROR, live.CLOSED):
                return

    reader = asyncio.create_task(read())
    await asyncio.sleep(8)
    if caller:
        for frame in mulaw_frames(caller):
            await ws.send(json.dumps(live.audio(base64.b64encode(frame).decode())))
            await asyncio.sleep(0.02)
        silence = base64.b64encode(b"\xff" * 160).decode()
        for _ in range(100):
            await ws.send(json.dumps(live.audio(silence)))
            await asyncio.sleep(0.02)
        await asyncio.sleep(10)
    await ws.send(json.dumps(live.close()))
    try:
        await asyncio.wait_for(reader, 15)
    except asyncio.TimeoutError:
        reader.cancel()
    await ws.close()
    return out


async def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--caller", help="a mu-law 8 kHz WAV of a caller to send into the live session")
    args = ap.parse_args(argv)
    s = Settings()
    if not s.openai_api_key:
        print("OPENAI_API_KEY is not set")
        return 1
    c = oc.OpenAIClient(s)
    ok = True

    def report(name: str, good: bool, detail: str) -> None:
        nonlocal ok
        ok = ok and good
        print(("OK   " if good else "FAIL ") + name + ": " + detail)

    try:
        scam, family = await c.decisions(SCAM), await c.decisions(FAMILY)
        report("Decisions", bool(scam and family and scam["p_scam"] > family["p_scam"]),
               f"scam message p={scam and scam['p_scam']} ({scam and scam['scam_type']}), "
               f"family message p={family and family['p_scam']} ({family and family['scam_type']})")
        threat = await c.moderate("If you don't pay today, police will arrest you and your family will suffer.")
        plain = await c.moderate("Please pay the electricity bill by Friday.")
        report("Moderation", threat["flagged"] and not plain["flagged"],
               f"threat flagged {threat['categories']}, plain message flagged={plain['flagged']}")
        rep = await c.responses_json(REPORT_PROMPT, report_input(REPORT_CASE), REPORT_SCHEMA, "case_report", step="report")
        report("Responses (case report)", set(REPORT_SCHEMA["required"]) <= set(rep),
               f"identifiers named: {rep.get('suspect_identifiers')}")
    finally:
        await c.close()
    v = await check_live(s, args.caller)
    heard = bool(v["caller"]) if args.caller else True
    report("Live voice", bool(v["started_s"] is not None and v["meena"] and v["audio_s"] > 0 and heard),
           f"started in {v['started_s']} s, Meena spoke {v['audio_s']} s: \"{v['meena'][:160]}\""
           + (f"; caller transcribed: \"{v['caller'][:120]}\"" if args.caller else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
