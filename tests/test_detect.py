"""Detection: rules alone (offline), Cerebras and Decisions combined, and errors never meaning 'safe'."""
import asyncio

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


class FakeDecisions:
    def __init__(self, result=None, boom=False):
        self.result, self.boom, self.calls = result, boom, 0

    async def decisions(self, window, case_id=None):
        self.calls += 1
        if self.boom:
            raise RuntimeError("decisions down")
        return self.result


def use(brain, openai=None):
    set_runtime(Runtime(settings=Settings(offline_mode=True), store=None, bus=None, brain=brain, openai=openai))


def win(*texts):
    return [{"role": "scammer", "text": t} for t in texts]


def cer(p, kind="other", risk="high"):
    return FlagBrain({"is_scam": p >= 0.5, "p_scam": p, "scam_type": kind, "risk": risk})


def dec(p, kind=None, risk=None):
    return FakeDecisions({"p_scam": p, "scam_type": kind, "risk": risk, "tactics": {}, "usage": {}})


KYC = "Your account will be blocked today, update KYC now"
LUNCH = "Hi, are we still meeting for lunch?"


@pytest.mark.parametrize("text,label", [
    ("Your OTP for HDFC Bank login is 482913. Do not share it with anyone.", "not_scam"),
    ("Dear customer, your Bharat Unity Bank account will be blocked today. Update KYC now: http://x.example/kyc", "scam"),
    (KYC, "scam"),
    ("Your investment profit is ready, pay the tax to UPI fakeinvest.demo@okaxis now", "scam"),
    (LUNCH, "unknown"),
])
async def test_rules_alone(text, label):
    use(FlagBrain(None))
    v = await detect.judge(win(text))
    assert v.label == label, (v, rules.score(text))
    assert (v.p_cerebras, v.p_decisions, v.decisions_available) == (None, None, None)


async def test_cerebras_decides_when_sure_even_against_decisions():
    use(cer(0.92, "digital_arrest", "critical"), dec(0.1, "not_a_scam", "none"))
    v = await detect.judge(win("This is cyber police, you are under digital arrest"))
    assert (v.label, v.scam_type, v.risk, v.decided_by) == ("scam", "digital_arrest", "critical", "cerebras")
    assert (v.p_scam, v.p_cerebras, v.p_decisions, v.decisions_available) == (0.92, 0.92, 0.1, True)
    use(cer(0.1, "not_a_scam", "none"), dec(0.95, "kyc_phishing", "high"))
    v = await detect.judge(win("Pay the fee now"))
    assert (v.label, v.scam_type, v.risk, v.decided_by) == ("not_scam", "not_a_scam", "none", "cerebras")


@pytest.mark.parametrize("p_c", [0.2, 0.8])
async def test_the_cerebras_lines_are_inclusive(p_c):
    use(cer(p_c), dec(1 - p_c))
    v = await detect.judge(win("hello"))
    assert v.decided_by == "cerebras" and v.label == ("scam" if p_c == 0.8 else "not_scam")


async def test_decisions_decides_the_band():
    use(cer(0.6, "other", "low"), dec(0.7, "investment_trading", "critical"))
    v = await detect.judge(win("Members earn 30% weekly in our VIP group"))
    assert (v.label, v.scam_type, v.risk, v.decided_by, v.p_scam) == ("scam", "investment_trading", "critical",
                                                                      "decisions", 0.7)
    use(cer(0.7, "kyc_phishing"), dec(0.3))
    v = await detect.judge(win(KYC))
    assert (v.label, v.decided_by, v.p_cerebras, v.p_decisions) == ("not_scam", "decisions", 0.7, 0.3)


async def test_scam_type_falls_back_to_the_other_model_then_rules():
    use(cer(0.5, "other"), dec(0.9, "other", None))
    v = await detect.judge(win(KYC))
    assert (v.decided_by, v.scam_type, v.risk) == ("decisions", "kyc_phishing", "high")
    use(cer(0.4, "delivery_phishing", "low"), dec(0.9, None, None))
    v = await detect.judge(win(KYC))
    assert (v.scam_type, v.risk) == ("delivery_phishing", "low")


async def test_one_model_alone_decides_at_one_half():
    use(cer(0.5, "other"), None)  # no OpenAI key: Cerebras in the band decides alone
    v = await detect.judge(win(KYC))
    assert (v.label, v.decided_by, v.scam_type, v.decisions_available) == ("scam", "cerebras", "kyc_phishing", None)
    use(cer(0.45), FakeDecisions(None))  # Decisions unavailable to the key
    v = await detect.judge(win(KYC))
    assert (v.label, v.decided_by, v.decisions_available) == ("not_scam", "cerebras", False)
    use(FlagBrain(boom=True), dec(0.55, "job_task"))
    v = await detect.judge(win(LUNCH))
    assert (v.label, v.decided_by, v.scam_type, v.p_cerebras) == ("scam", "decisions", "job_task", None)
    use(FlagBrain(None), dec(0.3))
    assert (await detect.judge(win(KYC))).decided_by == "decisions"


async def test_both_models_failing_is_never_safe():
    use(FlagBrain(boom=True), FakeDecisions(boom=True))
    v = await detect.judge(win(LUNCH))
    assert (v.label, v.decided_by, v.decisions_available) == ("unknown", "none", False)
    v = await detect.judge(win(KYC))
    assert (v.label, v.decided_by) == ("scam", "rules")
    use(FlagBrain(boom=True))
    assert (await detect.judge(win("Send the money now or else"))).label in ("scam", "unknown")


async def test_bad_probabilities_are_no_opinion():
    use(FlagBrain({"p_scam": "high"}), dec(float("nan")))
    v = await detect.judge(win(LUNCH))
    assert (v.label, v.p_cerebras, v.p_decisions) == ("unknown", None, None)
    use(cer(1.7), dec(-3))
    v = await detect.judge(win(LUNCH))
    assert (v.p_cerebras, v.p_decisions) == (1.0, 0.0)


async def test_the_two_models_are_asked_at_the_same_time():
    started = asyncio.Event()

    class WaitingBrain:
        async def flag(self, window, case_id=None):
            await asyncio.wait_for(started.wait(), 2)  # only returns if Decisions is already running
            return {"p_scam": 0.5, "scam_type": "other", "risk": "low"}

    class SignallingDecisions:
        async def decisions(self, window, case_id=None):
            started.set()
            await asyncio.sleep(0)
            return {"p_scam": 0.9, "scam_type": "upi_collect", "risk": "high"}

    use(WaitingBrain(), SignallingDecisions())
    v = await detect.judge(win("Accept the collect request"), "c_000000000001")
    assert (v.label, v.decided_by, v.scam_type) == ("scam", "decisions", "upi_collect")


def test_red_flag_labels_are_plain_words():
    _, signs = rules.score("URGENT: your KYC is pending, account blocked. Pay Rs 10 at http://x.example")
    labels = {s.label for s in signs}
    assert {"Says your KYC, PAN or Aadhaar must be updated", "Pushes you to act right now", "Contains a link"} <= labels
