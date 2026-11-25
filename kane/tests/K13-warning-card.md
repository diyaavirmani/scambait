---
id: K13
title: The family warning card explains the scam without naming the payee
path: /console
covers: [dashboard/src/components/WarningCard.tsx, dashboard/src/pages/Cases.tsx, app/cases.py]
timeout: 300
---
Click "New chat". Click the practice scam button "Bank KYC update", then click Send.
Wait until the Kane investigations panel shows "Proven by Kane" (this can take up to 90 seconds).
Click "Cases" in the side menu and open the newest case if it is not already open.
Verify that a "Warn your family" panel is shown, that its card says "SCAM ALERT", says the link pretends to be
Bharat Unity Bank and asks for Rs 10, and says the money would go to an account ending in "oupi".
Verify that the card does not show the full UPI ID bharatunity.kyc@demoupi anywhere, and that it has a
"Copy for WhatsApp" button.
