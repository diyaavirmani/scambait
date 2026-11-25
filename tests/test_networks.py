"""Scammer networks: cases linked by a shared strong identifier, merged with union-find, and the live event."""
import time

import pytest
from fastapi.testclient import TestClient

from app import engine, limits, networks
from app.intel import normalise
from app.investigate import drain
from app.models import utc_now

LAB_KYC = "http://127.0.0.1:8000/lab/kyc"


@pytest.fixture(autouse=True)
def fresh_memory():
    networks.reset()
    yield
    networks.reset()


async def new_case(store, *identifiers, scam_type="unknown"):
    case = await store.new_case("web", "web:" + utc_now())
    if scam_type != "unknown":
        await store.update_case(case["id"], scam_type=scam_type)
    for kind, value in identifiers:
        await store.add_intel(case["id"], kind, value, normalise(kind, value), None)
    return case["id"]


async def proven_payee(store, case_id, payee, kind, verdict="payment_request_found"):
    inv = await store.add_investigation(case_id, "http://pay.example/" + payee)
    await store.update_investigation(inv, status="passed", verdict=verdict, payee=payee, payee_kind=kind,
                                     finished_at=utc_now())


async def updates(store):
    return [e for e in await store.events_after(0) if e.type == "network.updated"]


async def test_two_cases_sharing_a_upi_id_form_a_network(runtime):
    store = runtime.store
    a = await new_case(store, ("upi", "fake.refund@okaxis"), scam_type="kyc_phishing")
    b = await new_case(store, ("upi", "Fake.Refund@OKAXIS"), ("phone", "+919000000009"), scam_type="refund_scam")
    await new_case(store, ("upi", "someone.else@ybl"))
    (net,) = await networks.compute_networks()
    assert net["network_id"] == "n_" + a and net["case_ids"] == [a, b]
    assert net["shared"] == [{"kind": "upi", "value": "fake.refund@okaxis", "norm": "fake.refund@okaxis",
                              "case_count": 2}]
    assert net["scam_types"] == ["kyc_phishing", "refund_scam"]
    assert net["first_seen"] <= net["last_seen"]
    assert networks.network_for_case([net], b) is net and networks.network_for_case([net], "c_000000000000") is None


async def test_chains_merge_into_one_network(runtime):
    store = runtime.store
    a = await new_case(store, ("phone", "+91 90000 00011"))
    b = await new_case(store, ("phone", "9000000011"), ("bank_account", "001122334455"))
    c = await new_case(store, ("bank_account", "0011 2233 4455"), ("email", "Boss@Scam.example"))
    d = await new_case(store, ("email", "boss@scam.example"))
    (net,) = await networks.compute_networks()
    assert net["case_ids"] == [a, b, c, d] and net["network_id"] == "n_" + a
    assert {(s["kind"], s["norm"]) for s in net["shared"]} == {
        ("phone", "9000000011"), ("bank_account", "001122334455"), ("email", "boss@scam.example")}


async def test_a_payee_kane_proved_links_cases(runtime):
    store = runtime.store
    said = await new_case(store, ("upi", "bharatunity.kyc@demoupi"))
    shown = await new_case(store)
    await proven_payee(store, shown, "bharatunity.kyc@demoupi", "upi")
    unproven = await new_case(store)
    await proven_payee(store, unproven, "bharatunity.kyc@demoupi", "upi", verdict="no_payee_found")
    (net,) = await networks.compute_networks()
    assert net["case_ids"] == [said, shown]


async def test_amounts_and_ifsc_never_link(runtime):
    store = runtime.store
    await new_case(store, ("amount", "5000"), ("ifsc", "SBIN0001234"))
    await new_case(store, ("amount", "5000"), ("ifsc", "SBIN0001234"))
    assert await networks.compute_networks() == []


async def test_network_updated_is_emitted_only_on_change(runtime):
    store = runtime.store
    a = await new_case(store, ("upi", "boss@okaxis"))
    await networks.on_identifier_added(a)
    assert await updates(store) == []  # one case is not a network
    b = await new_case(store, ("upi", "boss@okaxis"))
    await networks.on_identifier_added(b)
    await networks.on_identifier_added(b)
    await networks.on_identifier_added(a)
    (first,) = await updates(store)
    assert first.data == {"network_id": "n_" + a, "case_ids": [a, b]} and first.case_id == b
    c = await new_case(store, ("upi", "boss@okaxis"))
    await networks.on_identifier_added(c)
    sent = await updates(store)
    assert len(sent) == 2 and sent[1].data["case_ids"] == [a, b, c]


async def test_a_kane_finding_announces_the_network(runtime):
    a = await runtime.store.open_case("web", "web:said")
    await engine.handle_message(a["id"], "web", "Pay Rs 10 to bharatunity.kyc@demoupi now")
    b = await runtime.store.open_case("web", "web:linked")
    await engine.handle_message(b["id"], "web", f"Your account will be blocked. Update KYC: {LAB_KYC}")
    await engine.settle()
    await drain()
    sent = await updates(runtime.store)
    assert sent and sent[-1].data["case_ids"] == [a["id"], b["id"]] and sent[-1].case_id == b["id"]


async def test_thousands_of_identifiers_stay_fast(runtime):
    store = runtime.store
    now = utc_now()
    cases = [(f"c_{i:012x}", "web", f"web:{i}", now, now) for i in range(2000)]
    await store.db.executemany("INSERT INTO cases (id, channel, external_id, created_at, updated_at) "
                               "VALUES (?,?,?,?,?)", cases)
    rows = []
    for i in range(2000):
        cid = f"c_{i:012x}"
        rows += [(cid, "upi", f"mule{i // 4}@ybl", f"mule{i // 4}@ybl", now),
                 (cid, "phone", f"+91{9000000000 + i}", str(9000000000 + i), now),
                 (cid, "amount", "5000", "5000", now)]
    await store.db.executemany("INSERT INTO intel (case_id, kind, value, norm, first_seen) VALUES (?,?,?,?,?)", rows)
    await store.db.commit()
    started = time.perf_counter()
    found = await networks.compute_networks()
    assert time.perf_counter() - started < 2.0
    assert len(found) == 500 and all(len(n["case_ids"]) == 4 for n in found)


def test_networks_api(settings):
    limits.reset()
    from app.main import create_app
    app = create_app(settings)
    if not any(getattr(r, "path", "") == "/api/networks" for r in app.routes):
        app.include_router(networks.router)
    with TestClient(app) as client:
        ids = []
        for session in ("n1", "n2"):
            r = client.post("/api/console/messages", json={"session_id": session,
                                                           "text": "Send the fee to ring.leader@okicici today"})
            ids.append(r.json()["case_id"])
        body = client.get("/api/networks").json()
    assert [n["case_ids"] for n in body["networks"]] == [ids]
    assert body["networks"][0]["shared"][0]["value"] == "ring.leader@okicici"
