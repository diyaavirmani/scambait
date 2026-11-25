"""Scammer networks: cases linked because they share an identifier.

Two cases are linked when they hold the same normalised identifier of a strong kind: a UPI ID, phone, bank account,
card, email or link. A payee Kane proved on a scam page counts as an identifier of its case. Amounts and IFSC codes
(a whole bank branch) are shared by unrelated people, so they never link. Links are grouped with union-find, so A-B
and B-C make one network of three cases. A network has at least two cases, and its id comes from its oldest case,
so it stays the same while the network grows.

GET /api/networks   every network, largest first

on_identifier_added(case_id) recomputes after a case gains an identifier and emits `network.updated` when the
network holding that case is new or has new members. Kane's proven payees reach it through
app.investigate.on_finding, registered when this module is imported.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter

from app.bus import emit
from app.intel import extract, normalise
from app.investigate import on_finding
from app.runtime import get_runtime

log = logging.getLogger("scambait.networks")
router = APIRouter()

LINK_KINDS = ("upi", "phone", "bank_account", "card", "email", "url")
QUIET_TYPES = {"", "unknown", "not_a_scam"}  # not listed in a network's scam_types

_known: dict[str, tuple[str, ...]] = {}  # network id -> the members last announced
_locks: list = []  # [(loop, lock)]: one recompute at a time, per event loop


class _UnionFind:
    """Groups of case ids."""

    def __init__(self) -> None:
        self.up: dict[str, str] = {}

    def root(self, x: str) -> str:
        up = self.up
        up.setdefault(x, x)
        while up[x] != x:
            up[x] = up[up[x]]  # path halving keeps chains short
            x = up[x]
        return x

    def join(self, a: str, b: str) -> None:
        ra, rb = self.root(a), self.root(b)
        if ra != rb:
            self.up[rb] = ra


def _payee_ids(payee: str, kind: str) -> list[tuple[str, str]]:
    """(kind, value) pairs for a proven payee. An unlabelled payee is read with the identifier extractor."""
    if kind in LINK_KINDS:
        return [(kind, payee)]
    return [(i.kind, i.value) for i in extract(payee) if i.kind in LINK_KINDS]


async def sightings(store) -> list[dict]:
    """Every strong identifier per case, said in chat or proven by Kane:
    {case_id, kind, value, norm, seen, created_at, scam_type}."""
    marks = ",".join("?" * len(LINK_KINDS))
    rows = await store._all(
        "SELECT i.case_id, i.kind, i.value, i.norm, i.first_seen AS seen, c.created_at, c.scam_type "
        f"FROM intel i JOIN cases c ON c.id = i.case_id WHERE i.kind IN ({marks}) AND i.norm != ''", LINK_KINDS)
    proven = await store._all(
        "SELECT v.case_id, v.payee, v.payee_kind, COALESCE(v.finished_at, v.created_at) AS seen, c.created_at, "
        "c.scam_type FROM investigations v JOIN cases c ON c.id = v.case_id "
        "WHERE v.verdict = 'payment_request_found' AND v.payee != ''")
    for p in proven:
        for kind, value in _payee_ids(p["payee"], p["payee_kind"]):
            rows.append({"case_id": p["case_id"], "kind": kind, "value": value, "norm": normalise(kind, value),
                         "seen": p["seen"], "created_at": p["created_at"], "scam_type": p["scam_type"]})
    return rows


def build_networks(rows: list[dict]) -> list[dict]:
    """Networks from identifier sightings (see sightings()). Pure, so it is easy to test."""
    holders: dict[tuple[str, str], dict[str, dict]] = {}  # (kind, norm) -> case id -> its earliest sighting
    cases: dict[str, dict] = {}
    for r in rows:
        if r["kind"] not in LINK_KINDS or not r["norm"]:
            continue
        cases[r["case_id"]] = r
        by_case = holders.setdefault((r["kind"], r["norm"]), {})
        first = by_case.get(r["case_id"])
        if first is None or (r["seen"] or "") < (first["seen"] or ""):
            by_case[r["case_id"]] = r

    shared = {key: by_case for key, by_case in holders.items() if len(by_case) > 1}
    groups = _UnionFind()
    for by_case in shared.values():
        first, *rest = by_case
        for other in rest:
            groups.join(first, other)

    links: dict[str, list] = {}  # group root -> the shared identifiers inside that group
    for key, by_case in shared.items():
        links.setdefault(groups.root(next(iter(by_case))), []).append((key, by_case))

    out = []
    for group in links.values():
        ids = sorted({cid for _, by_case in group for cid in by_case},
                     key=lambda cid: (cases[cid]["created_at"] or "", cid))
        times = [r["seen"] for _, by_case in group for r in by_case.values() if r["seen"]]
        items = [{"kind": kind, "value": min(by_case.values(), key=lambda r: r["seen"] or "")["value"], "norm": norm,
                  "case_count": len(by_case)} for (kind, norm), by_case in group]
        items.sort(key=lambda s: (-s["case_count"], s["kind"], s["norm"]))
        out.append({
            "network_id": "n_" + ids[0],
            "case_ids": ids,
            "shared": items,
            "first_seen": min(times, default=None),
            "last_seen": max(times, default=None),
            "scam_types": sorted({cases[cid]["scam_type"] or "" for cid in ids} - QUIET_TYPES),
        })
    out.sort(key=lambda n: (-len(n["case_ids"]), n["first_seen"] or "", n["network_id"]))
    return out


async def compute_networks(store=None) -> list[dict]:
    """Every network of two or more cases, largest first."""
    return build_networks(await sightings(store or get_runtime().store))


def network_for_case(networks: list[dict], case_id: str) -> Optional[dict]:
    return next((n for n in networks if case_id in n["case_ids"]), None)


def _lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    if not _locks or _locks[0][0] is not loop:
        _locks[:] = [(loop, asyncio.Lock())]
    return _locks[0][1]


def reset() -> None:
    """Tests: forget the memberships already announced."""
    _known.clear()


async def on_identifier_added(case_id: str, channel: Optional[str] = None) -> None:
    """Recompute after a case gained an identifier; emit network.updated when its network is new or changed.
    Never raises into the caller."""
    try:
        store = get_runtime().store
        async with _lock():
            net = network_for_case(await compute_networks(store), case_id)
            if net is None:
                return
            members = tuple(net["case_ids"])
            if _known.get(net["network_id"]) == members:
                return
            for nid, old in list(_known.items()):
                if set(old) & set(members):
                    del _known[nid]  # merged into this network
            _known[net["network_id"]] = members
            if channel is None:
                channel = ((await store.get_case(case_id)) or {}).get("channel") or "web"
            await emit("network.updated", {"network_id": net["network_id"], "case_ids": list(members)},
                       case_id, channel)
    except Exception:
        log.exception("network recompute failed for %s", case_id)


async def _on_kane_finding(row: dict) -> None:
    if row.get("verdict") == "payment_request_found" and row.get("case_id") and row.get("payee"):
        await on_identifier_added(row["case_id"])


on_finding(_on_kane_finding)


@router.get("/api/networks")
async def list_networks() -> dict:
    return {"networks": await compute_networks()}
