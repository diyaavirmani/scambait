"""Identifier extraction: the right kinds, no false UPI IDs, no phone counted twice, no regex freeze."""
import time

import pytest

from app.intel import extract, normalise


def kinds(text):
    return [(i.kind, i.value) for i in extract(text)]


@pytest.mark.parametrize("text,want", [
    ("Pay to UPI fakeinvest.demo@okaxis and send screenshot.", [("upi", "fakeinvest.demo@okaxis")]),
    ("If UPI not working, call me on +91 90000 00001.", [("phone", "+919000000001")]),
    ("Call me at 5pm if any doubt.", []),
    ("Or do bank transfer: account 000123456789, IFSC ABCD0001234, name StockPro Ventures.",
     [("bank_account", "000123456789"), ("ifsc", "ABCD0001234")]),
    ("Download link: https://stockpro-demo.example/StockPro.apk",
     [("url", "https://stockpro-demo.example/StockPro.apk"), ("apk", "https://stockpro-demo.example/StockPro.apk")]),
    ("Mail your PAN to help.desk@kyc-support.example", [("email", "help.desk@kyc-support.example")]),
    ("Minimum investment only 10,000 rupees", [("amount", "10000")]),
    ("Pending amount: Rs 1,280. Pay now", [("amount", "1280")]),
    ("Card 4111 1111 1111 1111 expiry 12/29", [("card", "4111111111111111")]),
    ("Your OTP for HDFC Bank login is 482913. Do not share it with anyone.", []),
])
def test_extract(text, want):
    assert kinds(text) == want


def test_upi_needs_letters_after_the_at_sign():
    assert kinds("ping me@5pm or x@123") == []
    assert kinds("send to bharatunity.kyc@demoupi") == [("upi", "bharatunity.kyc@demoupi")]


def test_a_phone_is_never_also_a_bank_account():
    assert kinds("Call 9000000001 or 919000000001") == [("phone", "+919000000001")]


def test_links_keep_their_digits_and_handles_to_themselves():
    got = kinds("Update KYC: http://127.0.0.1:8000/lab/kyc?ref=9876543210")
    assert got == [("url", "http://127.0.0.1:8000/lab/kyc?ref=9876543210")]


def test_long_hostile_text_is_fast():
    start = time.monotonic()
    extract("1 " * 3000 + "a@" * 2000 + "http://" + "x" * 3000)
    assert time.monotonic() - start < 1.0


def test_normalise():
    assert normalise("phone", "+91 90000-00001") == "9000000001"
    assert normalise("upi", "X@DemoUPI") == "x@demoupi"
    assert normalise("url", "HTTPS://Evil.example/Pay/") == "evil.example/pay"
