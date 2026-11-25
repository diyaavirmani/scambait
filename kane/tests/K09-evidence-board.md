---
id: K09
title: The evidence board lists what the scammer said, once each, with no false UPI IDs
path: /console
covers: [app/intel.py, app/engine.py, dashboard/src/components/EvidenceBoard.tsx, dashboard/src/pages/Console.tsx]
timeout: 240
---
Click "New chat". Type "Your investment profit is ready, pay the tax to UPI fakeinvest.demo@okaxis now" and
click Send, then wait for the reply. Type "Call me at 5pm if any doubt, or on 9000000001" and click Send,
then wait for the reply.
Verify that the Evidence board shows the UPI ID fakeinvest.demo@okaxis marked "Said in chat", shows a phone
number ending in 0001, and does not show any UPI ID containing "5pm".
