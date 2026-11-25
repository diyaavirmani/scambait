"""Practice scam lab: every site walks to a payment request with its known answer, nothing typed is kept,
and the pay button is the only thing recorded."""
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.lab import SITES, router


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    c.post("/lab/api/reset")
    return c


def _walk_to_payment(client, site) -> str:
    page = client.get(f"/lab/{site.key}")
    assert page.status_code == 200
    for n in range(len(site.steps) - 1):
        data = {f.name: "Meena Sharma" for f in site.steps[n].fields}
        page = client.post(f"/lab/{site.key}/{n}", data=data, follow_redirects=True)
        assert page.status_code == 200
        assert f"Step {n + 2} of {len(site.steps)}" in page.text
    return page.text


@pytest.mark.parametrize("site", SITES, ids=lambda s: s.key)
def test_every_page_says_practice_site_and_has_no_outside_links(client, site):
    for n in range(len(site.steps)):
        text = client.get(f"/lab/{site.key}/{n}").text
        assert "Practice site for SCAM-BAIT testing" in text
        assert site.brand in text
        assert "http://" not in text and "https://" not in text
        assert "noindex" in text


@pytest.mark.parametrize("site", SITES, ids=lambda s: s.key)
def test_walk_ends_on_payment_request_with_the_known_answer(client, site):
    final = _walk_to_payment(client, site)
    assert site.answer.payee in final
    assert f"{site.answer.amount:,}".replace(",", "") in final.replace(",", "")
    for key in ("ifsc", "account_name"):
        if key in site.answer.extra:
            assert site.answer.extra[key] in final
    activity = client.get("/lab/api/activity").json()[site.key]
    assert activity["reached_payment_step"] is True
    assert activity["payment_attempts"] == 0


def test_typed_values_are_never_echoed_or_kept(client):
    site = SITES[0]
    final = _walk_to_payment(client, site)
    assert "Meena Sharma" not in final
    client.post(f"/lab/{site.key}/pay", data={"upi_pin": "123456"})
    activity = client.get("/lab/api/activity").json()[site.key]
    assert "123456" not in str(activity)
    assert activity["attempts"][0]["fields_filled"] == ["upi_pin"]


def test_pressing_pay_is_recorded_and_reset_clears_it(client):
    site = SITES[1]
    page = client.post(f"/lab/{site.key}/pay", data={"card_number": "", "upi_pin": ""})
    assert "Payment failed" in page.text
    assert client.get("/lab/api/activity").json()[site.key]["payment_attempts"] == 1
    client.post("/lab/api/reset")
    assert client.get("/lab/api/activity").json()[site.key]["payment_attempts"] == 0


def test_answers_are_fictional():
    for site in SITES:
        a = site.answer
        if a.payee_kind == "upi":
            assert a.payee.endswith("@demoupi")
        else:
            assert re.fullmatch(r"\d{9,18}", a.payee)
            assert a.extra["ifsc"].startswith("DEMO")
        if "phone" in a.extra:
            assert a.extra["phone"].startswith("90000")


def test_sites_api_and_index(client):
    sites = client.get("/lab/api/sites").json()["sites"]
    assert [s["key"] for s in sites] == [s.key for s in SITES]
    assert all(s["answer"]["payee"] for s in sites)
    index = client.get("/lab").text
    for s in SITES:
        assert f"/lab/{s.key}" in index


def test_unknown_site_and_step_are_404(client):
    assert client.get("/lab/nope").status_code == 404
    assert client.get("/lab/kyc/9").status_code == 404
    last = len(SITES[0].steps) - 1
    assert client.post(f"/lab/kyc/{last}").status_code == 404
