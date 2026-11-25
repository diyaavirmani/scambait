---
id: K10
title: Kane opens a link again as a new visitor and shows that the payee changed
path: /console
# The investigator inside the app opens /lab/loan twice. With the replay investigator (the gate's default) that needs
# real recordings of both visits: kane/recordings/loan.ndjson and loan.2.ndjson, made by
# scripts/investigate.py --check-lab --record. With --inner real, Kane CLI makes both visits itself.
covers: [app/investigate/**, app/lab/**, app/meena.py, app/store.py, app/config.py, app/networks.py, app/cases.py, scripts/kane_replay.py, dashboard/src/components/KaneCard.tsx, dashboard/src/components/EvidenceBoard.tsx, dashboard/src/lib/kane.ts, dashboard/src/lib/live.ts, dashboard/src/lib/types.ts, dashboard/src/pages/Console.tsx]
timeout: 480
---
Click "New chat". Click the practice scam button "Instant loan fee", then click Send, and wait for Meena's reply.
In the Kane investigations panel, wait until a card marked "fresh-visit re-check" has finished and no card says
Kane is still opening the link (this can take up to 5 minutes, because Kane opens the link twice).
Store the UPI IDs listed under "Payee changed on a fresh visit" as seen_payees.
Then type "Did you pay the fee? Hurry up." in the message box and click Send, and wait for Meena's reply.
Verify that the Kane investigations panel shows the note "Payee changed on a fresh visit" listing two different
UPI IDs, one for Visit 1 and one for Visit 2, that both end in "@demoupi", that the re-check card is marked
"fresh-visit re-check", and that Meena's latest reply is marked "used what Kane found".
