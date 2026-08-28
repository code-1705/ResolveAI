# Contributing to Resolve.ai

Thank you for your interest in contributing to Resolve.ai — an enterprise-grade autonomous Accounts Receivable (AR) & Collections platform powered by FastAPI, Razorpay, Google Gemini, WhatsApp Cloud API, Supabase, and React/Vite.

To maintain production-grade reliability, security, and financial accuracy, all contributions must adhere to the standards outlined in this guide.

---

## Table of Contents

- [Code of Conduct and Core Engineering Invariants](#code-of-conduct-and-core-engineering-invariants)
- [Branching Strategy](#branching-strategy)
- [How to Report Issues](#how-to-report-issues)
  - [Bug Reports](#bug-reports)
  - [Feature Requests and RFCs](#feature-requests-and-rfcs)
  - [Security Vulnerability Disclosure](#security-vulnerability-disclosure)
- [Pull Request Lifecycle](#pull-request-lifecycle)
  - [PR Requirements and Pre-Submission Checklist](#pr-requirements-and-pre-submission-checklist)
  - [PR Title and Conventional Commits](#pr-title-and-conventional-commits)
  - [Production PR Description Template](#production-pr-description-template)
- [Local Development Setup](#local-development-setup)
- [Verification and Quality Gate](#verification-and-quality-gate)

---

## Code of Conduct and Core Engineering Invariants

All contributions must strictly uphold Resolve.ai's financial, scalability, and security invariants:

1. **Mandatory Test Script for Every New Feature**:

   - Every new feature, endpoint, or business logic addition MUST be accompanied by dedicated automated test scripts in `backend/tests/`.
   - PRs without comprehensive test coverage will be rejected.

2. **Enterprise-Grade Scalability & Reliability**:

   - All code must be designed for horizontal scalability, zero-downtime, explicit type safety, and defensive error handling.
   - Avoid hacky workarounds, hardcoded thresholds, or memory-leaking background tasks.

3. **Zero-Float Integer Paise Math**:

   - Currency values MUST NEVER be represented as floating-point numbers.
   - Always use integer paise (`1 INR = 100 paise`) with explicit integer operations (`//`, `%`, `int()`).

4. **Deterministic Guardrails Before Tool Execution**:

   - Untrusted LLM outputs must be validated by the deterministic Python guardrail firewall (`backend/services/guardrails.py`) before payment links or messages are emitted.

5. **Multi-Tenant Isolation**:

   - Every database query and API mutation must be strictly scoped by `merchant_id`. Cross-tenant data leakage is a P0 critical vulnerability.

6. **Cryptographic Webhook Idempotency**:

   - All webhook signature verifications must use timing-safe comparison (`hmac.compare_digest`).
   - Every payment capture must enforce idempotency via `UNIQUE(razorpay_payment_id)`.

---

## Branching Strategy

We follow a structured branch naming convention:

- `feat/<component>-<short-description>`: New features (e.g., `feat/frontend-dunning-chart`, `feat/payment-split-links`)
- `fix/<component>-<short-description>`: Bug fixes (e.g., `fix/guardrail-discount-cap`, `fix/sse-listener-cleanup`)
- `sec/<vulnerability-id>`: Security patches (e.g., `sec/webhook-timing-defense`)
- `refactor/<scope>`: Code refactoring without behavioral changes
- `test/<scope>`: Adding or modifying test suites

---

## How to Report Issues

### Bug Reports

Before opening a new issue, search existing issues to avoid duplicates. When filing a bug report, use the following structure:

```markdown
### Summary

A clear, concise description of the defect.

### Severity

- [ ] Critical (P0) - Data corruption, financial math drift, security leak, tenant breach
- [ ] High (P1) - Runtime crash, broken state machine, API contract mismatch
- [ ] Medium (P2) - Unhandled edge case, resource leak, network retry failure
- [ ] Low (P3) - Visual defect, minor optimization, dead code

### Affected Components

- [ ] Backend (FastAPI / Services)
- [ ] Frontend (React / Vite Dashboard)
- [ ] Guardrails & Ledger Math
- [ ] Payment Integrations (Razorpay / WhatsApp)
- [ ] Database & Supabase Auth

### Affected Files & Lines

- `backend/services/guardrails.py#L45-L60`

### Steps to Reproduce

1. Log into merchant dashboard.
2. Trigger payment link generation for invoice with 20% discount.
3. Observe guardrail rejection failure.

### Expected Behavior

Guardrail firewall should reject any discount exceeding the 15% ceiling cap.

### Actual Behavior

Link generated with unauthorized 20% discount.

### Logs & Error Traces

```text
[Paste terminal logs or error stack traces here]
```

### Proposed Remediation

Explain suggested fix or provide code snippet.
```

### Feature Requests and RFCs

For major features or architectural modifications, open an RFC (Request for Comments) issue detailing:

1. **Problem Statement**: What friction or user need does this solve?
2. **Proposed Architecture**: High-level design, data models, API contracts.
3. **Financial & Security Impact**: How will this affect ledger accuracy or tenant isolation?
4. **Alternative Solutions Considered**: Why is the proposed approach optimal?

### Security Vulnerability Disclosure

If you discover a security vulnerability or tenant isolation flaw, **DO NOT** open a public issue. Email security concerns directly to the project maintainers with reproduction details.

---

## Pull Request Lifecycle

### PR Requirements and Pre-Submission Checklist

Before submitting a Pull Request:

- [ ] All tests pass locally: `pytest backend/tests/ -v`
- [ ] Frontend builds cleanly with zero errors: `cd frontend && npm run build`
- [ ] Markdown files strictly comply with MD032 (`blanks-around-lists`)
- [ ] No hardcoded secrets, test API keys, or `.env` files are committed
- [ ] Added unit or integration tests covering the new feature or bug fix
- [ ] Linked the corresponding GitHub Issue in the PR description (`Fixes #123`)

---

### PR Title and Conventional Commits

Format PR titles using [Conventional Commits](https://www.conventionalcommits.org/):

- `feat(fintech): implement multi-bill FIFO payment distribution`
- `fix(webhooks): use timing-safe hmac compare_digest for signature check`
- `feat(frontend): add real-time SSE reconnection indicator`
- `test(auth): add tenant isolation assertions for invoice endpoints`
- `refactor(session): optimize debtor message thread summarization`

---

### Production PR Description Template

Copy this template into your Pull Request description:

```markdown
## Description

Provide a comprehensive summary of what changes are introduced and the architectural rationale.

## Related Issue

Fixes #<issue_number>

## Type of Change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that alters existing contracts)
- [ ] Security patch
- [ ] Refactoring / Performance optimization

## Financial & Security Invariants Verification

- [ ] Zero floating-point math: All currency computations use integer paise (`amount_paise`).
- [ ] Guardrails verified: Deterministic policy bounds enforced before API calls.
- [ ] Multi-tenant isolation verified: All DB queries scope by `merchant_id`.
- [ ] Cryptographic checks verified: Timing-safe HMAC-SHA256 signature verification used.

## Verification & Testing Evidence

### Automated Tests Executed

```bash
pytest backend/tests/ -v
# Output: 4 passed in 1.12s
```

### Frontend Build Verification

```bash
cd frontend && npm run build
# Output: ✓ built in 640ms
```

### Manual Test Steps & Screenshots

1. Step 1...
2. Step 2...

[Attach screenshots or recordings if UI was modified]

## Checklist

- [ ] My code follows the repository's coding standards.
- [ ] I have added tests that prove my fix is effective or that my feature works.
- [ ] New and existing unit tests pass locally with my changes.
- [ ] I have updated corresponding documentation if applicable.
```

---

## Local Development Setup

### 1. Backend Setup

```bash
# Clone the repository
git clone https://github.com/<owner>/ResolveAI.git
cd ResolveAI

# Create and activate Python virtual environment
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start FastAPI development server
uvicorn backend.main:app --reload --port 8000
```

### 2. Frontend Setup

```bash
cd frontend

# Install Node dependencies
npm install

# Start Vite dev server
npm run dev
```

---

## Verification and Quality Gate

Continuous Integration (CI) runs automatically on all Pull Requests targeting `main`.

### Local Quality Gate Commands

```bash
# 1. Run full backend test suite
pytest backend/tests/ -v

# 2. Run single test module
pytest backend/tests/test_all_scenarios.py -v

# 3. Test frontend build
cd frontend
npm run build
```

Pull Requests will only be merged once all CI checks pass and maintainer approval is obtained.
