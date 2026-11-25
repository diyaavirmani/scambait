"""The practice scam sites: fictional brands, fictional payees, known answers.

Each site walks a visitor through a few steps the way a real scam page does, and ends on a payment request.
`Answer` is what an investigator should come back with. Every brand, bank, UPI ID, account and phone number
here is made up: UPI IDs end in @demoupi, IFSC codes start with DEMO, phone numbers use the 90000 test range.

A site whose Answer lists `payees` rotates its mule account the way real scam pages do: each fresh visitor (a
browser without the lab's visitor cookie) is shown the next payee in that list, in its markup's {payee} slot.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str = "text"          # text | tel | date | password | checkbox
    placeholder: str = ""
    value: str = ""


@dataclass(frozen=True)
class Step:
    title: str
    html: str                   # trusted, static markup written in this file
    fields: tuple[Field, ...] = ()
    button: str = "Continue"
    pay: bool = False           # the final payment step; its form posts to /pay and is recorded


@dataclass(frozen=True)
class Answer:
    claims_to_be: str
    payee_kind: str             # upi | bank_account
    payee: str
    amount: int                 # rupees
    asked_for: tuple[str, ...]
    extra: dict[str, str] = field(default_factory=dict)
    payees: tuple[str, ...] = ()  # a rotating site: every payee it shows, one per fresh visitor in turn (payee first)

    def is_payee(self, value: str) -> bool:
        """Whether value is a payee this site shows (any of them, on a rotating site)."""
        return (value or "").strip().lower() in {p.lower() for p in (self.payees or (self.payee,))}


@dataclass(frozen=True)
class Site:
    key: str
    brand: str
    scam_type: str
    color: str
    lure: str                   # the kind of message that would carry this link
    answer: Answer
    steps: tuple[Step, ...]

    @property
    def rotates(self) -> bool:
        return len(self.answer.payees) > 1


UPI_PIN = Field("upi_pin", "UPI PIN", "password", "Enter your 4 or 6 digit UPI PIN")

SITES: tuple[Site, ...] = (
    Site(
        key="kyc",
        brand="Bharat Unity Bank",
        scam_type="kyc_update",
        color="#1d4ed8",
        lure="Dear customer, your Bharat Unity Bank account will be blocked today. Update KYC now:",
        answer=Answer(
            claims_to_be="Bharat Unity Bank KYC update",
            payee_kind="upi", payee="bharatunity.kyc@demoupi", amount=10,
            asked_for=("full name", "mobile number", "date of birth", "UPI PIN"),
        ),
        steps=(
            Step("Account blocked today",
                 "<p class='alert'>Your account will be blocked within 24 hours.</p>"
                 "<p>Under new banking rules your KYC is pending. Update it now to keep using your account, "
                 "UPI and debit card.</p>",
                 button="Update KYC now"),
            Step("Update your KYC",
                 "<p>Enter your details exactly as they appear in your passbook.</p>",
                 fields=(Field("full_name", "Full name", placeholder="As in passbook"),
                         Field("mobile", "Registered mobile number", "tel", "10 digit mobile number"),
                         Field("dob", "Date of birth", "date"))),
            Step("Activate your account",
                 "<p>Final step: pay a refundable verification fee of <b>&#8377;10</b> to activate your account.</p>"
                 "<table class='pay'><tr><th>Pay to UPI ID</th><td>bharatunity.kyc@demoupi</td></tr>"
                 "<tr><th>Amount</th><td>&#8377;10</td></tr></table>",
                 fields=(UPI_PIN,), button="Pay &#8377;10 and verify", pay=True),
        ),
    ),
    Site(
        key="parcel",
        brand="QuickParcel India",
        scam_type="parcel_customs",
        color="#b45309",
        lure="QuickParcel: your parcel QP-48213-IN is held at customs. Pay the duty to release it:",
        answer=Answer(
            claims_to_be="QuickParcel India customs duty payment",
            payee_kind="upi", payee="quickparcel.customs@demoupi", amount=49,
            asked_for=("name", "mobile number", "PIN code", "card number", "card expiry", "CVV", "UPI PIN"),
        ),
        steps=(
            Step("Parcel on hold at customs",
                 "<table class='track'><tr><th>Tracking ID</th><td>QP-48213-IN</td></tr>"
                 "<tr><th>Status</th><td class='alert'>Held at customs</td></tr>"
                 "<tr><th>Reason</th><td>Import duty not paid</td></tr></table>"
                 "<p>Pay the pending duty within 2 hours or the parcel will be returned to the sender.</p>",
                 button="Release my parcel"),
            Step("Confirm delivery details",
                 "<p>Confirm where we should deliver the parcel.</p>",
                 fields=(Field("name", "Name"),
                         Field("mobile", "Mobile number", "tel", "10 digit mobile number"),
                         Field("pincode", "PIN code", placeholder="6 digit PIN code"))),
            Step("Pay customs duty",
                 "<p>Customs duty pending: <b>&#8377;49</b>.</p>"
                 "<table class='pay'><tr><th>Pay to UPI ID</th><td>quickparcel.customs@demoupi</td></tr>"
                 "<tr><th>Amount</th><td>&#8377;49</td></tr></table>"
                 "<p>Or pay by card below.</p>",
                 fields=(Field("card_number", "Card number", placeholder="16 digit card number"),
                         Field("card_expiry", "Expiry (MM/YY)"),
                         Field("cvv", "CVV", "password"),
                         UPI_PIN),
                 button="Pay &#8377;49", pay=True),
        ),
    ),
    Site(
        key="trading",
        brand="GrowthPro Capital",
        scam_type="investment_trading",
        color="#047857",
        lure="Sir, your VIP trading profit is ready. Login and withdraw today:",
        answer=Answer(
            claims_to_be="GrowthPro Capital VIP trading desk",
            payee_kind="bank_account", payee="000987654321", amount=33210,
            asked_for=("mobile number", "payment reference number"),
            extra={"ifsc": "DEMO0001234", "account_name": "GrowthPro Ventures"},
        ),
        steps=(
            Step("VIP Trading Desk",
                 "<p>Login with your registered mobile number.</p>",
                 fields=(Field("mobile", "Mobile number", "tel", "10 digit mobile number"),),
                 button="Login"),
            Step("Your portfolio",
                 "<table class='track'><tr><th>Portfolio value</th><td>&#8377;2,34,500</td></tr>"
                 "<tr><th>Profit this week</th><td class='good'>&#8377;1,84,500 (+371%)</td></tr></table>"
                 "<p>Your profit is ready to withdraw.</p>",
                 button="Withdraw profit"),
            Step("Withdrawal on hold",
                 "<p class='alert'>Withdrawal on hold: 18% capital gains tax must be paid first.</p>"
                 "<p>Transfer <b>&#8377;33,210</b> to the account below, then enter the payment reference.</p>"
                 "<table class='pay'><tr><th>Account name</th><td>GrowthPro Ventures</td></tr>"
                 "<tr><th>Account number</th><td>000987654321</td></tr>"
                 "<tr><th>IFSC</th><td>DEMO0001234</td></tr>"
                 "<tr><th>Amount</th><td>&#8377;33,210</td></tr></table>",
                 fields=(Field("utr", "Payment reference (UTR) number"),),
                 button="Submit payment proof", pay=True),
        ),
    ),
    Site(
        key="job",
        brand="TaskEarn",
        scam_type="task_job",
        color="#7c3aed",
        lure="Part time job! Like videos from home and earn Rs 3000 per day. Start here:",
        answer=Answer(
            claims_to_be="TaskEarn part-time video liking job",
            payee_kind="upi", payee="taskearn.vip@demoupi", amount=2000,
            asked_for=("UPI PIN",),
        ),
        steps=(
            Step("Earn &#8377;3,000 a day from home",
                 "<p>Like videos, get paid instantly. No experience needed.</p>",
                 button="Start task"),
            Step("Task 1 of 1: like 3 videos",
                 "<p>Tick each video after you like it.</p>",
                 fields=(Field("v1", "Video 1: Street food tour", "checkbox"),
                         Field("v2", "Video 2: Morning yoga", "checkbox"),
                         Field("v3", "Video 3: Cricket highlights", "checkbox")),
                 button="Submit task"),
            Step("You earned &#8377;150",
                 "<p>To withdraw, upgrade to <b>VIP Tier</b>: deposit <b>&#8377;2,000</b>, returned with a 30% bonus.</p>"
                 "<table class='pay'><tr><th>Pay to UPI ID</th><td>taskearn.vip@demoupi</td></tr>"
                 "<tr><th>Amount</th><td>&#8377;2,000</td></tr></table>",
                 fields=(UPI_PIN,), button="Deposit &#8377;2,000", pay=True),
        ),
    ),
    Site(
        key="electricity",
        brand="CityLight Power",
        scam_type="utility_bill",
        color="#dc2626",
        lure="Dear consumer, your electricity will be disconnected tonight at 9:30 PM. Update your bill:",
        answer=Answer(
            claims_to_be="CityLight Power electricity bill",
            payee_kind="upi", payee="citylight.bill@demoupi", amount=1280,
            asked_for=("consumer number", "UPI PIN"),
            extra={"phone": "9000000011"},
        ),
        steps=(
            Step("Disconnection notice",
                 "<p class='alert'>Your electricity connection will be disconnected tonight at 9:30 PM.</p>"
                 "<p>Your last bill was not updated. Enter your consumer number to check.</p>",
                 fields=(Field("consumer_no", "Consumer number", placeholder="10 digit consumer number"),),
                 button="Check bill"),
            Step("Pending bill",
                 "<p>Pending amount: <b>&#8377;1,280</b>. Pay now to stop the disconnection.</p>"
                 "<table class='pay'><tr><th>Pay to UPI ID</th><td>citylight.bill@demoupi</td></tr>"
                 "<tr><th>Amount</th><td>&#8377;1,280</td></tr>"
                 "<tr><th>Help</th><td>Electricity officer: 90000 00011</td></tr></table>",
                 fields=(UPI_PIN,), button="Pay &#8377;1,280", pay=True),
        ),
    ),
    Site(
        key="loan",
        brand="SwiftRin Loans",
        scam_type="loan_offer",
        color="#0e7490",
        lure="Congratulations! Your instant loan of Rs 50,000 is approved. Pay the small processing fee today only "
             "and the money reaches your bank account in 10 minutes:",
        answer=Answer(
            claims_to_be="SwiftRin Loans instant personal loan",
            payee_kind="upi", payee="swiftrin.fee@demoupi", amount=799,
            asked_for=("full name", "mobile number", "PIN code", "UPI PIN"),
            payees=("swiftrin.fee@demoupi", "rk.traders@demoupi", "metro.mart@demoupi"),
        ),
        steps=(
            Step("Your loan is approved",
                 "<p class='good'>Congratulations! An instant personal loan of <b>&#8377;50,000</b> is approved "
                 "for you.</p><p>No documents and no credit check. The money reaches your bank account in 10 "
                 "minutes.</p>",
                 button="Get my loan"),
            Step("Confirm your details",
                 "<p>Enter your details to receive the loan.</p>",
                 fields=(Field("full_name", "Full name"),
                         Field("mobile", "Mobile number", "tel", "10 digit mobile number"),
                         Field("pincode", "PIN code", placeholder="6 digit PIN code"))),
            Step("Pay the processing fee",
                 "<p>Pay a one-time processing fee of <b>&#8377;799</b> to release &#8377;50,000 to your "
                 "account.</p>"
                 "<table class='pay'><tr><th>Pay to UPI ID</th><td>{payee}</td></tr>"
                 "<tr><th>Amount</th><td>&#8377;799</td></tr></table>",
                 fields=(UPI_PIN,), button="Pay &#8377;799 and get my loan", pay=True),
        ),
    ),
)

SITES_BY_KEY: dict[str, Site] = {s.key: s for s in SITES}
