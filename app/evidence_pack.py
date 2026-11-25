"""Evidence pack for filing a complaint on cybercrime.gov.in (NCRP) or with 1930.

GET /api/cases/{id}/export.csv  one row per identifier, with the complaint fields repeated on every row
GET /api/cases/{id}/export.pdf  the complaint fields, the links Kane CLI opened (what each page pretends to be, who it
                                pays, the amount, the evidence pack SHA-256 and Kane's screenshot of the payment page),
                                the identifiers, and the full transcript
Every file is written under DATA_DIR/exports/<case id>/, its SHA-256 is recorded as case evidence and returned in the
X-SHA256 header. Times are shown in IST.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import os
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import Response

from app.cases import load_case, proven_keys
from app.intel import normalise
from app.runtime import get_runtime

router = APIRouter()

IST = timezone(timedelta(hours=5, minutes=30))
# The NCRP form rejects these characters in free text.
NCRP_BANNED = set("#$@^*`'~|!") | {"‘", "’"}
SUSPECT = [  # (column, label, identifier kinds)
    ("suspect_mobile", "Suspect mobile numbers", ("phone",)),
    ("suspect_upi", "Suspect UPI IDs", ("upi",)),
    ("suspect_bank_account", "Suspect bank accounts", ("bank_account",)),
    ("suspect_ifsc", "Suspect IFSC codes", ("ifsc",)),
    ("suspect_email", "Suspect emails", ("email",)),
    ("suspect_urls", "Suspect websites and apps", ("url", "apk")),
]
FONTS = [os.getenv("PDF_FONT_PATH", ""), "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]


def ist(ts: Optional[str]) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts).astimezone(IST).strftime("%d %b %Y, %H:%M:%S IST")
    except ValueError:
        return ts


def ncrp_text(text: str) -> str:
    return re.sub(r"\s+", " ", "".join(ch for ch in (text or "") if ch not in NCRP_BANNED)).strip()


async def build(case_id: str) -> dict:
    store = get_runtime().store
    case = await load_case(case_id)
    messages = await store.list_messages(case_id)
    intel = await store.list_intel(case_id)
    invs = await store.list_investigations(case_id)
    proven = proven_keys(invs)
    said = {(i["kind"], i["norm"]) for i in intel}
    rows = [{"kind": i["kind"], "value": i["value"], "source": "proven by Kane CLI and said in chat"
             if (i["kind"], i["norm"]) in proven else "said in chat", "first_seen": i["first_seen"]} for i in intel]
    for inv in invs:
        if inv.get("verdict") == "payment_request_found" and inv.get("payee_kind"):
            key = (inv["payee_kind"], normalise(inv["payee_kind"], inv["payee"]))
            if key not in said:
                rows.append({"kind": inv["payee_kind"], "value": inv["payee"], "source": "proven by Kane CLI only",
                             "first_seen": inv.get("finished_at")})
                said.add(key)
    first = next((m for m in messages if m["role"] == "scammer"), None)
    n_proven = sum(1 for i in invs if i.get("verdict") == "payment_request_found")
    details = ncrp_text(
        f"{case['summary'] or 'Suspected fraud.'} The suspect messaged a SCAM-BAIT decoy over {case['channel']} "
        f"(case {case['id']}). Scam type: {case['scam_type']}. Scammer messages recorded: "
        f"{sum(1 for m in messages if m['role'] == 'scammer')}. Identifiers collected: {len(rows)}. No money was paid. "
        + (f"Kane CLI opened {n_proven} link(s) sent by the suspect in a real browser, stopped before any payment, and "
           "recorded the payee shown on the scam page. " if n_proven else "")
        + "The attached evidence pack holds the full transcript and every identifier.")
    fields = {"incident_datetime_ist": ist(first["ts"]) if first else ist(case["created_at"]), "incident_details": details}
    for col, _, kinds in SUSPECT:
        fields[col] = "; ".join(r["value"] for r in rows if r["kind"] in kinds)
    transcript = "\n".join(f"[{ist(m['ts'])}] {'Scammer' if m['role'] == 'scammer' else 'Decoy (Meena)'}: {m['text']}"
                           for m in messages)
    from app.report import load_report
    report = load_report(get_runtime().settings.data_dir, case_id)
    return {"case": case, "fields": fields, "rows": rows, "investigations": invs, "transcript": transcript,
            "report": report,
            "generated": datetime.now(IST).strftime("%d %b %Y, %H:%M:%S IST"),
            "stamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}


def csv_cell(v):
    """Stop spreadsheet formula injection without mangling phone numbers: a cell starting with = or @, or with + or -
    followed by something other than digits, is prefixed with a quote."""
    if isinstance(v, str) and v and (v[0] in "=@\t\r" or (v[0] in "+-" and not re.fullmatch(r"[+-][\d ]+", v))):
        return "'" + v
    return v


def render_csv(pack: dict) -> bytes:
    buf = io.StringIO()
    out = csv.writer(buf, lineterminator="\r\n")
    cols = ["case_id", "channel", "generated_ist", "incident_datetime_ist", "incident_details"] + [c for c, _, _ in SUSPECT]
    out.writerow(cols + ["identifier_kind", "identifier", "source", "first_seen_ist"])
    c, f = pack["case"], pack["fields"]
    base = [c["id"], c["channel"], pack["generated"], f["incident_datetime_ist"], f["incident_details"]]
    base += [f[col] for col, _, _ in SUSPECT]
    for r in pack["rows"] or [None]:
        tail = ["", "", "", ""] if r is None else [r["kind"], r["value"], r["source"], ist(r["first_seen"])]
        out.writerow([csv_cell(v) for v in base + tail])
    return buf.getvalue().encode("utf-8")


def render_pdf(pack: dict, csv_sha: str) -> bytes:
    from fpdf import FPDF
    from fpdf.fonts import FontFace
    from app.investigate.evidence import read_screenshot

    pdf = FPDF(format="A4")
    pdf.set_margins(15, 15, 15)
    pdf.set_auto_page_break(True, margin=15)
    font = next((p for p in FONTS if p and os.path.isfile(p)), None)
    if font:
        pdf.add_font("U", "", font)
        family, clean = "U", (lambda s: s)
    else:
        family = "helvetica"
        clean = lambda s: "".join(ch if ord(ch) < 256 else "?" for ch in unicodedata.normalize("NFKD", s))  # noqa: E731
    pdf.add_page()

    def heading(text: str) -> None:
        pdf.ln(3)
        pdf.set_font(family, size=13)
        pdf.multi_cell(0, 7, clean(text), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(family, size=9)

    def para(text: str) -> None:
        pdf.multi_cell(0, 5, clean(text or ""), new_x="LMARGIN", new_y="NEXT")

    def table(rows: list[list[str]], widths: tuple) -> None:
        with pdf.table(col_widths=widths, text_align="LEFT", line_height=5,
                       headings_style=FontFace(emphasis="", fill_color=(230, 230, 230))) as t:
            for r in rows:
                row = t.row()
                for cell in r:
                    row.cell(clean("" if cell is None else str(cell)))

    c, f = pack["case"], pack["fields"]
    pdf.set_font(family, size=16)
    pdf.multi_cell(0, 9, clean(f"SCAM-BAIT evidence pack: case {c['id']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(family, size=9)
    para(f"Generated {pack['generated']}. For a complaint on cybercrime.gov.in (NCRP) or by calling 1930.")

    heading("Complaint fields")
    table([["Field", "Value"], ["Incident date and time", f["incident_datetime_ist"]],
           ["Incident details", f["incident_details"]]]
          + [[label, f[col] or "none collected"] for col, label, _ in SUSPECT], (45, 135))

    report = pack.get("report")
    if report:
        heading("Case report")
        para(report.get("summary", ""))
        if report.get("modus_operandi"):
            para("How the scam works: " + report["modus_operandi"])
        for point in report.get("key_points") or []:
            para("- " + point)
        if report.get("recommended_action"):
            para("Recommended action: " + report["recommended_action"])
        para(f"Risk: {report.get('risk', '')}. Written by: {report.get('generated_by', '')}, "
             f"from the transcript and validated identifiers only.")

    heading("Links opened by Kane CLI")
    if not pack["investigations"]:
        para("The suspect sent no links that were investigated.")
    for inv in pack["investigations"]:
        proven = inv.get("verdict") == "payment_request_found"
        result = "Payment request found; Kane stopped before paying" if proven else (inv.get("reason") or inv["status"])
        table([["Field", "Value"], ["Link", inv["url"]], ["Result", result[:300]],
               ["Pretends to be", inv.get("claims_to_be")], ["Money goes to", inv.get("payee")],
               ["Amount (Rs)", inv.get("amount")], ["Asked for", ", ".join(inv.get("asked_for") or [])],
               ["Kane steps", str(len(inv.get("steps") or []))], ["Checked at", ist(inv.get("finished_at"))],
               ["Evidence pack SHA-256", inv.get("evidence_sha256") or "none"]], (45, 135))
        shot = read_screenshot(inv["evidence_path"]) if proven and inv.get("evidence_path") else None
        if shot:
            para("Kane's screenshot of the page where it stopped, before paying:")
            try:
                pdf.image(io.BytesIO(shot[0]), w=90)
            except Exception:
                para("(the screenshot could not be embedded; it is inside the evidence pack)")

    heading("Identifiers")
    if pack["rows"]:
        table([["Kind", "Value", "Source", "First seen"]] +
              [[r["kind"], r["value"], r["source"], ist(r["first_seen"])] for r in pack["rows"]], (25, 60, 50, 45))
    else:
        para("No identifiers were collected.")

    heading("Transcript")
    para(pack["transcript"] or "No messages.")

    heading("Integrity")
    para(f"SHA-256 of the CSV export: {csv_sha}")
    para(f"SHA-256 of the transcript (UTF-8): {hashlib.sha256(pack['transcript'].encode()).hexdigest()}")
    para("The SHA-256 of this PDF is recorded in the case evidence log.")
    return bytes(pdf.output())


async def _save(case_id: str, kind: str, name: str, data: bytes) -> str:
    folder = Path(get_runtime().settings.data_dir) / "exports" / case_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    await get_runtime().store.add_evidence(case_id, kind, str(folder / name), digest)
    return digest


def _download(data: bytes, media: str, filename: str, digest: str) -> Response:
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"',
                                                     "X-SHA256": digest, "Cache-Control": "no-store"})


@router.get("/api/cases/{case_id}/export.csv")
async def export_csv(case_id: str) -> Response:
    pack = await build(case_id)
    data = render_csv(pack)
    name = f"{case_id}_{pack['stamp']}.csv"
    return _download(data, "text/csv; charset=utf-8", name, await _save(case_id, "csv", name, data))


@router.get("/api/cases/{case_id}/export.pdf")
async def export_pdf(case_id: str) -> Response:
    pack = await build(case_id)
    csv_data = render_csv(pack)
    csv_sha = await _save(case_id, "csv", f"{case_id}_{pack['stamp']}.csv", csv_data)
    data = await asyncio.to_thread(render_pdf, pack, csv_sha)
    name = f"{case_id}_{pack['stamp']}.pdf"
    return _download(data, "application/pdf", name, await _save(case_id, "pdf", name, data))
