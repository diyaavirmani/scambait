"""Twilio over HTTP: the webhook signature, the TwiML Meena answers with, and the token that ties a media stream to
its case.

Signature (X-Twilio-Signature): base64 of HMAC-SHA1, keyed with the auth token, over the full URL Twilio requested
followed by every POST parameter name and value, sorted by name. Checked with a constant-time compare.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Iterable
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

SAY_VOICE = "Polly.Aditi"   # Amazon Polly voice for Indian English (and Hindi)
SAY_RATE = "85%"            # Meena talks slowly
LISTEN_LANGUAGE = "en-IN"   # speech recognition for Indian English callers
LISTEN_TIMEOUT_S = "6"      # seconds of silence before Gather gives up and falls through to the next verb


# ---------- webhook signature ----------
def signature(auth_token: str, url: str, params: Iterable[tuple[str, str]]) -> str:
    payload = url + "".join(name + value for name, value in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def signature_ok(auth_token: str, url: str, params: Iterable[tuple[str, str]], given: str) -> bool:
    if not auth_token or not given:
        return False
    return hmac.compare_digest(signature(auth_token, url, params).encode(), given.encode())


# ---------- media stream token ----------
def stream_token(secret: str, case_id: str) -> str:
    """Proof, passed as a stream <Parameter>, that a media stream was started by our own TwiML for this case."""
    return hmac.new(secret.encode(), b"voice-stream:" + case_id.encode(), hashlib.sha256).hexdigest()[:32]


def stream_token_ok(secret: str, case_id: str, token: str) -> bool:
    if not secret or not case_id or not token:
        return False
    return hmac.compare_digest(stream_token(secret, case_id).encode(), token.encode())


def stream_url(public_base_url: str) -> str:
    """The websocket address Twilio streams to: wss:// for an https base (ws:// for a plain http one)."""
    parts = urlsplit(public_base_url)
    scheme = "ws" if parts.scheme == "http" else "wss"
    return f"{scheme}://{parts.netloc}{parts.path.rstrip('/')}/voice/stream"


# ---------- TwiML ----------
def _document(root: ET.Element) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>' + ET.tostring(root, encoding="unicode")


def _say(parent: ET.Element, text: str) -> None:
    say = ET.SubElement(parent, "Say", voice=SAY_VOICE)
    ET.SubElement(say, "prosody", rate=SAY_RATE).text = text


def _redirect(parent: ET.Element, url: str) -> None:
    ET.SubElement(parent, "Redirect", method="POST").text = url


def listen(text: str, action: str, fallback: str) -> str:
    """Say a line, then listen for the caller's speech and post it to action. Silence goes to fallback."""
    root = ET.Element("Response")
    gather = ET.SubElement(root, "Gather", input="speech", action=action, method="POST", language=LISTEN_LANGUAGE,
                           speechTimeout="auto", timeout=LISTEN_TIMEOUT_S)
    _say(gather, text)
    _redirect(root, fallback)
    return _document(root)


def hold(text: str, redirect: str) -> str:
    """Say a line without listening, then come straight back (used while Meena's reply is still being made)."""
    root = ET.Element("Response")
    _say(root, text)
    _redirect(root, redirect)
    return _document(root)


def hang_up(text: str) -> str:
    root = ET.Element("Response")
    _say(root, text)
    ET.SubElement(root, "Hangup")
    return _document(root)


def connect_stream(url: str, params: dict[str, str], fallback: str) -> str:
    """Bridge the call to our websocket. If the stream ends while the call is still up, Twilio goes on to fallback."""
    root = ET.Element("Response")
    stream = ET.SubElement(ET.SubElement(root, "Connect"), "Stream", url=url)
    for name, value in params.items():
        ET.SubElement(stream, "Parameter", name=name, value=value)
    _redirect(root, fallback)
    return _document(root)
