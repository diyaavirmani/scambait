"""Store: cases, messages, intel, events, investigations."""
import asyncio

from app.bus import Bus, sse
from app.models import Event


async def test_cases_and_messages(store):
    a = await store.open_case("web", "web:s1")
    assert (await store.open_case("web", "web:s1"))["id"] == a["id"]
    await store.update_case(a["id"], status="closed", verdict="scam")
    b = await store.open_case("web", "web:s1")
    assert b["id"] != a["id"]  # a closed case is never reopened
    await store.add_message(b["id"], "scammer", "hello")
    await store.add_message(b["id"], "persona", "who is this?")
    assert await store.count_messages(b["id"], "scammer") == 1
    assert [m["role"] for m in await store.list_messages(b["id"])] == ["scammer", "persona"]
    assert [c["turns"] for c in await store.list_cases() if c["id"] == b["id"]] == [1]


async def test_intel_is_unique_and_shared_across_cases(store):
    a = (await store.new_case("web", "a"))["id"]
    b = (await store.new_case("web", "b"))["id"]
    assert await store.add_intel(a, "upi", "x@demoupi", "x@demoupi", None) is True
    assert await store.add_intel(a, "upi", "x@demoupi", "x@demoupi", None) is False
    await store.add_intel(b, "upi", "X@DemoUPI", "x@demoupi", None)
    assert [r["case_id"] for r in await store.cases_sharing(a)] == [b]


async def test_investigations_round_trip_json_and_findings(store):
    cid = (await store.new_case("web", "c"))["id"]
    inv = await store.add_investigation(cid, "http://127.0.0.1/lab/kyc")
    await store.update_investigation(inv, verdict="payment_request_found", payee="a@demoupi",
                                     asked_for=["UPI PIN"], final_state={"payee": "a@demoupi"})
    row = await store.find_investigation(cid, "http://127.0.0.1/lab/kyc")
    assert row["asked_for"] == ["UPI PIN"] and row["final_state"] == {"payee": "a@demoupi"}
    assert await store.find_investigation(None, "http://127.0.0.1/lab/kyc") is None
    assert [f["id"] for f in await store.unused_findings(cid)] == [inv]
    await store.update_investigation(inv, used_at="now")
    assert await store.unused_findings(cid) == []


async def test_bus_stores_then_fans_out(store):
    bus = Bus(store)
    q = bus.subscribe()
    ev = await bus.emit(Event(type="case.updated", data={"status": "open"}, case_id=None))
    assert ev.id and (await q.get()).id == ev.id
    assert [e.id for e in await store.events_after(0)] == [ev.id]
    assert sse(ev).startswith(f"id: {ev.id}\nevent: case.updated\n")


async def test_a_stream_that_falls_behind_is_dropped(store, monkeypatch):
    import app.bus as busmod
    monkeypatch.setattr(busmod, "QUEUE_SIZE", 1)
    bus = Bus(store)
    q = bus.subscribe()
    await bus.emit(Event(type="case.updated"))
    await bus.emit(Event(type="case.updated"))
    assert q in bus.dropped
    bus.unsubscribe(q)
    assert q not in bus.dropped
    await asyncio.sleep(0)
