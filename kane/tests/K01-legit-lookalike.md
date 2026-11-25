---
id: K01
title: A real bank OTP message is not treated as a scam
path: /console
covers: [app/detect.py, app/rules.py, app/brain.py, app/engine.py, app/console.py, dashboard/src/pages/Console.tsx]
timeout: 180
---
Click "New chat". Type "Your OTP for HDFC Bank login is 482913. Do not share it with anyone." in the
message box and click Send. Wait for Meena's reply to appear in the conversation.
Verify that the Case panel does not show a SCAM badge, and that Meena's reply does not ask for money,
a UPI ID or a bank account.
