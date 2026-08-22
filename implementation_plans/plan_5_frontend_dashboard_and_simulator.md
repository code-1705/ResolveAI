# Implementation Plan - Submodule 5: Merchant Dashboard & WhatsApp Simulator UI

## Overview
Submodule 5 delivers a visually stunning, high-impact web interface built with React and Vite. It provides a dual-panel experience combining a live **Merchant Operations Dashboard** (connected via **Server-Sent Events (SSE)** for real-time updates) with an interactive **WhatsApp Client Simulator** featuring typing animation polish, an **Agent Reasoning Trace Drawer**, and an **Authentic Razorpay Payment Modal**.

---

## Technical Specifications & Architecture

### 1. Real-Time State Synchronization via SSE (`frontend/src/App.jsx`)
- Connects to backend `EventSource('/api/events')`.
- Listens for `payment_captured` and `invoice_updated` events.
- Automatically refreshes Master Invoice ledger state, remaining balance progress bars, and TPV Recovered metrics instantaneously when webhooks execute—**no manual page refresh needed**.

---

### 2. Component Breakdown (`frontend/src/components/`)
- **`Navbar.jsx`**: Branding header, live SSE connection status indicator, and live TPV ticker.
- **`MerchantDashboard.jsx`**:
  - Live TPV Metrics Cards (Total Overdue TPV, Recovered TPV, Recovery Rate %).
  - Guardrail Control Panel with interactive sliders for `Min Partial Payment %` (10%-90%), `Max Extension Days` (1-30), and Auto-Waiver %.
  - Master Invoices Table with visual balance reduction progress bars and status badges (`UNPAID`, `NEGOTIATING`, `PARTIALLY_PAID`, `PAID`).
- **`WhatsAppSimulator.jsx`**:
  - iOS/Android style mobile chat view.
  - Animated three-dot *"Resolve.ai is typing..."* bubble active while backend LLM processes messages.
  - Quick test scenario launcher buttons ("Cash crunch 40%", "Lowball 10%", "Date extension 14d").
  - Dynamic Payment Link card with instant payment launcher.
- **`AgentTracePanel.jsx`**:
  - Real-time slide-over inspection drawer detailing AI thoughts, Guardrail Pass/Fail status badges, Currency math (`INR -> Paise`), and Tool JSON payloads.
- **`RazorpayModal.jsx`**:
  - Authentic Razorpay Payment Gateway popup simulation (UPI, Netbanking, Cards) triggering background `payment.captured` webhooks upon payment.

---

## Verification Plan

### Manual Verification
1. **Launch App**: Verify styling, dark mode, typography, and responsive layout.
2. **SSE Connection**: Verify Navbar displays green "Live SSE Connected" indicator.
3. **Simulate Chat**: Trigger *"Cash crunch 40%"* scenario, verify typing indicator appears, observe generated payment link.
4. **Inspect AI Brain**: Open Agent Trace Panel, check green PASS status and currency math (`2000000 paise`).
5. **Complete Checkout & Verify Real-Time SSE Update**: Click Payment Link, complete mock checkout in Razorpay Modal. Verify that the Merchant Dashboard immediately updates invoice balance and TPV metrics via SSE broadcast without refreshing the page!
