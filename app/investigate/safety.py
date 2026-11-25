"""Which links the Kane investigator may open.

Practice-lab links (/lab/... on this app) are always allowed. Everything else is a real, possibly dangerous page,
so it is opened only when LIVE_INVESTIGATION=1, and never when it is a file download, has credentials in it,
uses an odd port, or points at a private or internal address.
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Optional
from urllib.parse import urlsplit

DOWNLOAD_EXT = (".apk", ".xapk", ".aab", ".ipa", ".exe", ".msi", ".dmg", ".pkg", ".bat", ".cmd", ".scr", ".jar",
                ".zip", ".rar", ".7z", ".tar", ".gz", ".iso", ".bin", ".sh", ".ps1", ".vbs", ".js")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def lab_hosts(public_base_url: str = "") -> set[str]:
    hosts = set(LOCAL_HOSTS)
    if public_base_url:
        host = urlsplit(public_base_url).hostname
        if host:
            hosts.add(host.lower())
    return hosts


def is_lab_link(url: str, public_base_url: str = "") -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return parts.scheme in ("http", "https") and host in lab_hosts(public_base_url) and (
        parts.path == "/lab" or parts.path.startswith("/lab/"))


def _is_public_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def _resolves_public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    addrs = {info[4][0] for info in infos}
    return bool(addrs) and all(_is_public_ip(a) for a in addrs)


def check_link(url: str, *, public_base_url: str = "", live: bool = False, resolve: bool = True) -> Optional[str]:
    """None when Kane may open the link, otherwise the reason it may not (shown to the user)."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return "Not a valid link."
    if parts.scheme not in ("http", "https"):
        return "Only http and https links are opened."
    if not parts.hostname:
        return "The link has no host."
    if parts.username or parts.password:
        return "Links with a username or password in them are not opened."
    if parts.path.lower().endswith(DOWNLOAD_EXT):
        return "This link downloads a file (for example an APK). It is recorded as evidence but never opened."
    if is_lab_link(url, public_base_url):
        return None
    if not live:
        return "Real links are not opened in this mode. Set LIVE_INVESTIGATION=1 to allow it."
    if parts.port not in (None, 80, 443):
        return "Links on unusual ports are not opened."
    host = parts.hostname.lower()
    if host in LOCAL_HOSTS or host.endswith((".local", ".internal", ".localhost")):
        return "Links to this machine or a private network are not opened."
    try:
        ipaddress.ip_address(host)
        if not _is_public_ip(host):
            return "Links to private or reserved addresses are not opened."
    except ValueError:
        if resolve and not _resolves_public(host):
            return "The link's host does not resolve to a public address."
    return None
