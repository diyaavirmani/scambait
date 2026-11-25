"""House style: no em dashes or emojis in tracked text files (the vendored Kane CLI skill is kept verbatim)."""
import subprocess

BANNED = r"\x{2014}|[\x{1F300}-\x{1FAFF}\x{2600}-\x{27BF}\x{1F000}-\x{1F2FF}\x{FE0F}]"


def test_no_em_dash_or_emoji_in_tracked_files():
    out = subprocess.run(["git", "grep", "-InP", BANNED, "--", ".", ":!.claude/skills", ":!app/web/dist"],
                         capture_output=True, text=True).stdout
    assert out == ""
