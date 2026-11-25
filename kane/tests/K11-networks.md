---
id: K11
title: Two chats that reuse one UPI ID show up as one scam network
path: /console
covers: [app/networks.py, app/cases.py, dashboard/src/pages/Networks.tsx, dashboard/src/pages/Intelligence.tsx, dashboard/src/components/LiveBits.tsx, dashboard/src/lib/extra-types.ts]
timeout: 300
---
Click "New chat". Type "Your KYC is pending, pay Rs 10 to UPI ringone.kyc@demoupi today or your account is blocked"
and click Send, then wait for the reply. Click "New chat" again. Type "Sir this is the bank KYC team, send Rs 10 to
ringone.kyc@demoupi now" and click Send, then wait for the reply.
Click "Networks" in the side menu. Verify that a network is shown that links 2 cases and lists a shared UPI ID
ending in "oupi".
Click "Intelligence" in the side menu. Verify that ringone.kyc@demoupi is listed and marked as seen in 2 cases.
