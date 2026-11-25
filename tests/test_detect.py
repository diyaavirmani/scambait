"""Detection: rules alone (offline), model plus rules, and errors never meaning 'safe'."""
import pytest

from app import detect, rules
from app.config import Settings
from app.runtime import Runtime, set_runtime


class FlagBrain:
    def __init__(self, result=None, boom=False):
        self.result, self.boom = result, boom

    async def flag(self, window, case_id=None):
        if self.boom:
            raise RuntimeError("model down")
        return self.result


def use(brain):
    set_runtime(Runtime(settings=Settings(offline_mode=True), store=None, bus=None, brain=brain))


def win(*texts):
    return [{"role": "scammer", "text": t} for t in texts]


@pytest.mark.parametrize("text,label", [
    ("Your OTP for HDFC Bank login is 482913. Do not share it with anyone.", "not_scam"),
    ("Dear customer, your Bharat Unity Bank account will be blocked today. Update KYC now: http://x.example/kyc", "scam"),
    ("Your account will be blocked today, update KYC now", "scam"),
    ("Your investment profit is ready, pay the tax to UPI fakeinvest.demo@okaxis now", "scam"),
    ("Hi, are we still meeting for lunch?", "unknown"),
])
async def test_rules_alone(text, label):
    use(FlagBrain(None))
    v = await detect.judge(win(text))
    assert v.label == label, (v, rules.score(text))


async def test_model_decides_when_confident_and_rules_break_ties():
    use(FlagBrain({"is_scam": True, "p_scam": 0.92, "scam_type": "digital_arrest", "risk": "critical"}))
    v = await detect.judge(win("This is cyber police, you are under digital arrest"))
    assert (v.label, v.scam_type, v.decided_by) == ("scam", "digital_arrest", "model")
    use(FlagBrain({"is_scam": False, "p_scam": 0.1, "scam_type": "not_a_scam", "risk": "none"}))
    assert (await detect.judge(win("Pay the fee now"))).label == "not_scam"
    use(FlagBrain({"is_scam": True, "p_scam": 0.5, "scam_type": "other", "risk": "low"}))
    v = await detect.judge(win("Your account will be blocked today, update KYC now"))
    assert (v.label, v.decided_by, v.scam_type) == ("scam", "rules", "kyc_phishing")


async def test_a_model_error_is_never_safe():
    use(FlagBrain(boom=True))
    v = await detect.judge(win("Send the money now or else"))
    assert v.label in ("scam", "unknown")


def test_red_flag_labels_are_plain_words():
    _, signs = rules.score("URGENT: your KYC is pending, account blocked. Pay Rs 10 at http://x.example")
    labels = {s.label for s in signs}
    assert {"Says your KYC, PAN or Aadhaar must be updated", "Pushes you to act right now", "Contains a link"} <= labels
