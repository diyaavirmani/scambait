---
id: K12
title: Live Chats shows the conversation and why it was called a scam
path: /console
covers: [dashboard/src/pages/LiveChats.tsx, dashboard/src/components/DetectionLog.tsx, app/detect.py, app/rules.py]
timeout: 240
---
Click "New chat". Type "Dear customer your SIM will be blocked in 2 hours, complete KYC now on this number 9000000001"
and click Send, then wait for the reply.
Click "Live Chats" in the side menu and open the newest chat if it is not already open.
Verify that the conversation shows the scammer's message and a reply from Meena, that the chat is marked as a scam,
and that the Detection panel lists at least one red flag.
