# Implementation Plan - Submodule 5: Merchant Dashboard & WhatsApp Simulator UI

## Overview
Submodule 5 delivers a visually stunning, high-impact web interface built with React and Vite. It provides a dual-panel experience combining a live **Merchant Operations Dashboard** with an interactive **WhatsApp Client Simulator** featuring typing animation polish, an **Agent Reasoning Trace Drawer**, and an **Authentic Razorpay Payment Modal**.

---

## Technical Specifications & Architecture

### 1. Design System & Styling (`frontend/src/index.css`)
- Sleek dark fintech color palette:
  - Deep Charcoal Canvas: `#0B0F19`
  - Glassmorphic Cards: `#111827` / `#1F2937` with `#374151` borders
  - Vibrant TPV Recovered Green: `#10B981`
  - Razorpay Brand Blue: `#0052FF` & `#0C2340`
  - Typography: Google Inter font family

### 2. UI Component Architecture (`frontend/src/components/`)
- **`Navbar.jsx`**: Branding header, live connection indicator, and live TPV ticker.
- **`MerchantDashboard.jsx`**:
  - Live TPV Metrics Cards (Total Overdue TPV, Recovered TPV, Conversion Rate %).
  - Guardrail Control Panel with interactive sliders for `Min Partial Payment %` (10%-90%), `Max Extension Days` (1-30), and Auto-Waiver %.
  - Master Invoices Table with visual balance reduction progress bars and status badges.
- **`WhatsAppSimulator.jsx`**:
  - iOS/Android style mobile chat view.
  - Animated three-dot *"Resolve.ai is typing..."* indicator during request processing.
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
2. **Configure Guardrails**: Change minimum partial payment slider to 40%.
3. **Simulate Chat**: Trigger *"Cash crunch 40%"* scenario, verify typing indicator appears, observe generated payment link.
4. **Inspect AI Brain**: Open Agent Trace Panel, check green PASS status and currency math (`2000000 paise`).
5. **Complete Checkout**: Click Payment Link, complete mock checkout in Razorpay Modal, observe immediate dashboard update to `PARTIALLY_PAID` with updated TPV metrics.
