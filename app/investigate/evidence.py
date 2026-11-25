"""Read step screenshots out of a Kane evidence pack.

A Kane CLI evidence pack is a zip with one folder per step:
tests/<test-slug>/steps/<n>-<agent>-<k>/screenshot.jpg (and annotated.png for some steps). The last step is the
page Kane stopped on, which for an investigation is the payment or PIN request.
"""
from __future__ import annotations

import re
import zipfile
from typing import Optional

STEP_RE = re.compile(r"(?:^|/)steps/(\d+)-[^/]*/screenshot\.(?:jpg|jpeg|png)$")
MAX_BYTES = 5 * 1024 * 1024


def screenshot_steps(pack: str) -> list[tuple[int, str]]:
    """(step number, member name) for every step screenshot, in step order. Empty if the pack is unreadable."""
    try:
        with zipfile.ZipFile(pack) as z:
            found = {}
            for name in z.namelist():
                m = STEP_RE.search(name)
                if m:
                    found.setdefault(int(m.group(1)), name)
    except (OSError, zipfile.BadZipFile):
        return []
    return sorted(found.items())


def read_screenshot(pack: str, step: Optional[int] = None) -> Optional[tuple[bytes, str]]:
    """(bytes, media type) of one step's screenshot; step=None gives the last step. None if missing."""
    steps = screenshot_steps(pack)
    if not steps:
        return None
    if step is None:
        member = steps[-1][1]
    else:
        member = dict(steps).get(step)
        if member is None:
            return None
    try:
        with zipfile.ZipFile(pack) as z:
            info = z.getinfo(member)
            if info.file_size > MAX_BYTES:
                return None
            data = z.read(member)
    except (OSError, KeyError, zipfile.BadZipFile):
        return None
    return data, ("image/png" if member.endswith(".png") else "image/jpeg")
