# 📱 FRIDAY Multi-Modal Interface & Mobile Companion Manual

This document details the mobile companion dashboard, dual push notification bridge (VAPID/FCM), conversational voice repair and emotion adaptation, and vision-powered screen sharing mode in the **FRIDAY Operating System**.

---

## 🏛️ Multi-Modal Interface Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Human Operator Tier                      │
│     • Mobile Dashboard (Bottom Tabs: Home/Trade/Forge/Nexus)│
│     • Rich Push Notifications (Interactive Buttons)         │
│     • Live Screen Sharing Diagnostics & Voice Interruption  │
└──────────────────────────────▲──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│        FRIDAY Multi-Modal & Mobile Companion Core           │
├──────────────────────────────┬──────────────────────────────┤
│  MobileDashboardInterface    │  NotificationBridge          │
│  • Single-Column Responsive  │  • VAPID Web Push (Browser)  │
│  • Double-Tap Panic Security │  • FCM Mobile Push (iOS/And) │
│  • Offline Cache & Sync Flag │  • Deep Links & Action Btns  │
├──────────────────────────────┼──────────────────────────────┤
│  ConversationalVoiceInterface│  ScreenSharingSession        │
│  • Multi-Turn Context Thread │  • Visual Chart/Error Engine │
│  • Confidence Repair Tiers   │  • Zero-Recording Privacy    │
│  • Speech Interruption Trap  │  • 5-Min Idle Auto-Timeout   │
└──────────────────────────────┴──────────────────────────────┘
```

---

## 📱 1. Mobile Companion Dashboard

- **Single-Column Responsive View**: Tailored for mobile viewports with fast card rendering.
- **Bottom Navigation**: Five primary tabs (`Home`, `Trading`, `Forge`, `Nexus`, `Alerts`).
- **Double-Tap Emergency Guard**: High-risk actions (`EMERGENCY_HALT_TRADING`, `LIQUIDATE_ALL`) require two distinct taps within 3.0 seconds to prevent accidental execution.
- **Offline Cache**: Displays last synchronized state with clear offline visual indicators.

---

## 🔔 2. Notification Bridge (Web & Mobile Push)

- **Web Push**: VAPID-compliant notifications with Service Worker background listeners.
- **Mobile Push**: Firebase Cloud Messaging (FCM) formatted payloads.
- **Rich Action Buttons**:
  - *Trading Alerts*: `[⏸️ Pause Trading]` + `[📊 View Positions]`
  - *Nexus Approvals*: `[✅ Approve]` + `[❌ Reject]`
- **Deep Linking**: Directly opens relevant section (e.g. `friday://trading/positions`, `friday://nexus/leads`).

---

## 🎙️ 3. Conversational Voice Interface & Repair

| Confidence Tier | Voice Engine Response Behavior |
| :--- | :--- |
| **$< 0.70$ (Low)** | **Repair (Repeat)**: *"I didn't catch that clearly. Could you please repeat that?"* |
| **$0.70 \le c < 0.85$ (Medium)** | **Repair (Confirm)**: *"Did you mean: '{transcript}'? Please confirm to execute."* |
| **$\ge 0.85$ (High)** | **Execute Directly**: Processes command with contextual thread awareness. |

- **Mid-Speech Interruption**: User speaking mid-sentence immediately terminates TTS playback and shifts FRIDAY to listening mode.
- **Emotion & Stress Detection**: Elevated stress automatically condenses verbose explanations into concise bullet points.

---

## 👁️ 4. Vision Screen Sharing Mode

- **Chart & Error Diagnostics**: Combines visual screen frame context with user questions (*"What's wrong with this chart?" $\to$ detects RSI divergence and resistance levels*).
- **Privacy Sandbox**: Frames are processed purely in-memory; zero disk recording.
- **Auto-Termination**: Session closes automatically after **5 minutes of inactivity**.
