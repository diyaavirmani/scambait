"""Practice scam lab: fictional scam sites with known answers, served at /lab.

Why it exists: real scam pages vanish within hours and block bots, so the Kane investigator and its tests need
targets that behave like scam pages, never change, and have a known right answer. Judges can run every
investigation against them without touching a real criminal site.

Safety: every page carries a banner saying it is a practice site, every brand and payee is fictional, and
form posts are thrown away. The only thing kept is a count of visits per step and of presses on the final
pay button (field names only, never values), so a test can prove an investigator reached the payment step
and never paid.

Rotating payee: a site whose answer lists several payees (/lab/loan) gives each fresh visitor the next one. A
visitor is a browser holding the site's random `lab_visitor` cookie; a browser without it (or with one from before
a reset) is a new visitor. The activity log records which payee each visitor was shown on the payment step, so a
probe that opens the link twice can be checked against what the lab really showed.

Routes:
  GET  /lab                     list of sites with their known answers
  GET  /lab/{site}              step 0;  GET /lab/{site}/{n} step n
  POST /lab/{site}/{n}          go to step n + 1 (submitted values are discarded)
  POST /lab/{site}/pay          a payment attempt: recorded, then shown as failed
  GET  /lab/api/sites           sites and answers as JSON
  GET  /lab/api/activity        visits and payment attempts per site (and payees shown, on a rotating site)
  POST /lab/api/reset           clear the activity counters and start every rotation again at its first payee
"""
from __future__ import annotations

import html
import secrets
import threading
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from app.lab.sites import SITES, SITES_BY_KEY, Site, Step

router = APIRouter(prefix="/lab")

_lock = threading.Lock()
_visits: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
_attempts: dict[str, list[dict]] = defaultdict(list)
_visitors: dict[str, dict[str, int]] = defaultdict(dict)   # rotating site -> visitor cookie -> visitor number (0..)
_shown: dict[str, list[dict]] = defaultdict(list)          # rotating site -> payee each visitor saw on the pay step
VISITOR_COOKIE = "lab_visitor"

BANNER = ("Practice site for SCAM-BAIT testing. {brand} is fictional and so is everything on this page. "
          "Never enter real details.")

CSS = """
*{box-sizing:border-box}body{margin:0;font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:#f4f5f7;color:#1b1d22}.banner{background:#111827;color:#fde68a;font-size:13px;padding:8px 16px;
text-align:center}header{background:var(--brand);color:#fff;padding:14px 16px;font-weight:700;font-size:18px}
main{max-width:520px;margin:20px auto;padding:0 16px}.card{background:#fff;border-radius:10px;padding:20px;
box-shadow:0 1px 3px rgba(0,0,0,.12)}h1{font-size:21px;margin:0 0 12px}.alert{color:#b91c1c;font-weight:600}
.good{color:#047857;font-weight:600}table{width:100%;border-collapse:collapse;margin:12px 0}
th,td{text-align:left;padding:8px;border-bottom:1px solid #e5e7eb;vertical-align:top}th{width:45%;color:#4b5563;
font-weight:500}.pay{background:#f9fafb}label{display:block;margin:12px 0 4px;font-weight:500}
input[type=text],input[type=tel],input[type=date],input[type=password]{width:100%;padding:10px;font-size:16px;
border:1px solid #cbd5e1;border-radius:6px}.check{display:flex;gap:8px;align-items:center;margin:10px 0}
.check label{margin:0;font-weight:400}button{margin-top:18px;width:100%;padding:12px;font-size:16px;
font-weight:600;color:#fff;background:var(--brand);border:0;border-radius:6px;cursor:pointer}
.steps{color:#6b7280;font-size:13px;margin-bottom:6px}.list a{display:block;padding:14px;margin:10px 0;
background:#fff;border-radius:8px;color:#1b1d22;text-decoration:none;border-left:6px solid var(--c)}
.list small{color:#6b7280}code{background:#eef2f7;padding:1px 4px;border-radius:4px;word-break:break-all}
td{word-break:break-word}
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _page(title: str, brand: str, color: str, body: str, banner: str | None = None) -> HTMLResponse:
    banner = banner or BANNER.format(brand=brand)
    doc = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='robots' content='noindex,nofollow'>"
        f"<title>{html.escape(title)} | {html.escape(brand)}</title>"
        f"<style>:root{{--brand:{color}}}{CSS}</style></head><body>"
        f"<div class='banner' role='note'>{html.escape(banner)}</div>"
        f"<header>{html.escape(brand)}</header><main>{body}</main></body></html>"
    )
    return HTMLResponse(doc, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"})


def _field_html(f) -> str:
    fid = f"f_{f.name}"
    if f.kind == "checkbox":
        return (f"<div class='check'><input type='checkbox' id='{fid}' name='{f.name}' value='1'>"
                f"<label for='{fid}'>{html.escape(f.label)}</label></div>")
    ph = f" placeholder='{html.escape(f.placeholder)}'" if f.placeholder else ""
    return (f"<label for='{fid}'>{html.escape(f.label)}</label>"
            f"<input type='{f.kind}' id='{fid}' name='{f.name}'{ph} autocomplete='off'>")


def _step_page(site: Site, n: int, payee: str = "") -> HTMLResponse:
    step: Step = site.steps[n]
    action = f"/lab/{site.key}/pay" if step.pay else f"/lab/{site.key}/{n}"
    fields = "".join(_field_html(f) for f in step.fields)
    markup = step.html.replace("{payee}", html.escape(payee)) if site.rotates else step.html
    body = (
        f"<div class='card'><div class='steps'>Step {n + 1} of {len(site.steps)}</div>"
        f"<h1>{step.title}</h1>{markup}"
        f"<form method='post' action='{action}'>{fields}<button type='submit'>{step.button}</button></form></div>"
    )
    return _page(step.title, site.brand, site.color, body)


def _visitor(site: Site, request: Request) -> tuple[str, int, bool]:
    """(cookie, visitor number, new) on a rotating site. Must be called with _lock held."""
    known = _visitors[site.key]
    token = request.cookies.get(VISITOR_COOKIE, "")
    if token in known:
        return token, known[token], False
    token = secrets.token_hex(8)
    known[token] = len(known)
    return token, known[token], True


def _site(key: str) -> Site:
    site = SITES_BY_KEY.get(key)
    if site is None:
        raise HTTPException(status_code=404, detail="No such practice site.")
    return site


def _answer_dict(site: Site) -> dict:
    return {"key": site.key, "brand": site.brand, "scam_type": site.scam_type, "path": f"/lab/{site.key}",
            "steps": len(site.steps), "lure": site.lure, "answer": asdict(site.answer)}


@router.get("", include_in_schema=False)
async def lab_index() -> HTMLResponse:
    items = []
    for s in SITES:
        a = s.answer
        payee = a.payee + (f" (IFSC {a.extra['ifsc']})" if "ifsc" in a.extra else "")
        pays = f"<code>{html.escape(payee)}</code>"
        if s.rotates:
            pays = ("one of " + ", ".join(f"<code>{html.escape(p)}</code>" for p in a.payees)
                    + " (the payee changes for each fresh visitor)")
        items.append(
            f"<a href='/lab/{s.key}' style='--c:{s.color}'><b>{html.escape(s.brand)}</b>"
            f" <small>{html.escape(s.scam_type)}</small><br><small>Known answer: pays "
            f"{pays}, &#8377;{a.amount:,}</small></a>"
        )
    body = ("<div class='card'><h1>Practice scam lab</h1><p>Fictional scam sites with known answers, used by the "
            "Kane investigator and its tests. Nothing here is real and nothing typed here is stored.</p>"
            f"<div class='list'>{''.join(items)}</div></div>")
    return _page("Practice scam lab", "SCAM-BAIT", "#111827", body,
                 banner="Practice scam lab for SCAM-BAIT testing. Every brand and payee here is fictional.")


@router.get("/api/sites")
async def lab_sites() -> JSONResponse:
    return JSONResponse({"sites": [_answer_dict(s) for s in SITES]})


@router.get("/api/activity")
async def lab_activity() -> JSONResponse:
    with _lock:
        out = {
            s.key: {
                "visits": {str(n): _visits[s.key][n] for n in range(len(s.steps)) if _visits[s.key][n]},
                "reached_payment_step": _visits[s.key][len(s.steps) - 1] > 0,
                "payment_attempts": len(_attempts[s.key]),
                "attempts": list(_attempts[s.key]),
            }
            for s in SITES
        }
        for s in SITES:
            if s.rotates:
                out[s.key]["visitors"] = len(_visitors[s.key])
                out[s.key]["payees_shown"] = [dict(x) for x in _shown[s.key]]
    return JSONResponse(out)


@router.post("/api/reset")
async def lab_reset() -> JSONResponse:
    with _lock:
        _visits.clear()
        _attempts.clear()
        _visitors.clear()
        _shown.clear()
    return JSONResponse({"ok": True})


@router.get("/{key}", include_in_schema=False)
async def site_start(key: str, request: Request) -> Response:
    return await site_step(key, 0, request)


@router.get("/{key}/{n:int}", include_in_schema=False)
async def site_step(key: str, n: int, request: Request) -> Response:
    site = _site(key)
    if not 0 <= n < len(site.steps):
        raise HTTPException(status_code=404, detail="No such step.")
    token, new = "", False
    payee = ""
    with _lock:
        _visits[site.key][n] += 1
        if site.rotates:
            token, number, new = _visitor(site, request)
            payee = site.answer.payees[number % len(site.answer.payees)]
            if site.steps[n].pay and not any(x["visitor"] == number + 1 for x in _shown[site.key]):
                _shown[site.key].append({"visitor": number + 1, "payee": payee, "ts": _now()})
    page = _step_page(site, n, payee)
    if new:
        page.set_cookie(VISITOR_COOKIE, token, path=f"/lab/{site.key}", httponly=True, samesite="lax")
    return page


@router.post("/{key}/pay", include_in_schema=False)
async def site_pay(key: str, request: Request) -> HTMLResponse:
    site = _site(key)
    form = await request.form()
    filled = sorted(k for k, v in form.items() if str(v).strip())
    with _lock:
        _attempts[site.key].append({"ts": _now(), "fields_filled": filled})
    body = ("<div class='card'><h1>Payment failed</h1><p class='alert'>Bank server busy. Please try again.</p>"
            f"<p><a href='/lab/{site.key}/{len(site.steps) - 1}'>Try again</a></p></div>")
    return _page("Payment failed", site.brand, site.color, body)


@router.post("/{key}/{n:int}", include_in_schema=False)
async def site_next(key: str, n: int) -> RedirectResponse:
    site = _site(key)
    if not 0 <= n < len(site.steps) - 1:
        raise HTTPException(status_code=404, detail="No such step.")
    return RedirectResponse(f"/lab/{site.key}/{n + 1}", status_code=303)


__all__ = ["router", "SITES", "SITES_BY_KEY"]
