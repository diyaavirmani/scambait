---
id: K14
title: Before you pay, Kane shows who would get the money; after paying, 1930 comes first
path: /check
covers: [app/check.py, dashboard/src/pages/Check.tsx, dashboard/src/components/BeforeYouPay.tsx, dashboard/src/components/Rescue.tsx, dashboard/src/components/CopyButton.tsx, dashboard/src/lib/linkcheck.ts, dashboard/src/lib/check-types.ts]
timeout: 300
---
Click the example button "Bharat Unity Bank", then click "Check this message" and wait for the verdict.
Click the button that starts with "Check who gets the money" and wait until Kane has finished (this can take up to
90 seconds).
Verify that the page says "Do not pay", names bharatunity.kyc@demoupi as where the money would go, and shows Rs 10.
Then click "I already paid".
Verify that the first step shown is "Call 1930 now" and that a complaint draft for cybercrime.gov.in is shown below it.
