# 🏛️ GPURent Architecture & Development Guidelines

Welcome, Developer or AI Agent! This document maps out the system architecture, Domain-Driven Design (DDD) boundaries, and engineering mandates of the GPURent Conceptual Platform. 

**ALL developers and active AI Agents MUST read this file, the active specifications in `docs/specs/`, and the Architectural Decision Records (ADRs) in `docs/adrs/` before proposing changes, generating code, or modifying files.**

---

## 🗺️ 1. Domain-Driven Design (DDD) & Bounded Contexts

GPURent is structured as three highly isolated, decoupled Django applications (contexts) surrounding the core `gpurent` Django settings project:

### 👤 A. `users` (Account & API Authentication Context)
* **Responsibility:** Manages developer accounts, secure API keys, token usage audits, and request rate-limiting.
* **Core Models:** `TokenUsage`.
* **Key Interceptors:** `users/middleware.py` (enforces the maximum 60 requests/minute quota limit per token, returning standard HTTP 429).

### 💳 B. `billing` (Financial & Payment Context)
* **Responsibility:** Handles user balance credits ledger, monthly deferred invoicing, dynamic bulk discounts, and flat tier upgrade pricing.
* **Core Models:** `UserCredit`, `Invoice`.
* **External Clients (`services/`):** `billing/services/payment_gateway.py` (interfaces with the local Mockoon / Stripe Mock server using strict connection and read timeouts of 5.0 seconds).
* **Isolation rule:** Leases or inventory contexts cannot directly alter balances. All adjustments must go through the dedicated ledger services in `billing/orchestrators/ledger.py`.

### 🚀 C. `leases` (GPU Inventory & Rental Context)
* **Responsibility:** Governs the live NVIDIA catalog, physical card instances, lease lifecycles, and metric collection.
* **Core Models:** `GPUModel`, `GPUInstance`, `RentalLease`, `MetricSnapshot`.
* **Background Tasks (`simulation/`):** Ticks every 5 seconds per active lease, gathering VRAM, load, and temperature data, and raising thermal alerts above 90°C.

---

## 🐳 2. Process Separation & Containerization (ADR 0001)

Following **ADR 0001**, the background simulation loop is completely decoupled from the Web API process:
* **API Service (`web` Container):** Runs the Gunicorn WSGI process to handle fast, synchronous REST requests.
* **Simulation Service (`worker` Container):** Boots as a standalone command process (`python manage.py run_simulation`), executing the metrics loops and simulated customer agents.
* Both services run on separate containers but share the same codebase and database schema via Docker Compose.

---

## 📋 3. Operational Mandates for Developers and AI Agents

To maintain perfect alignment with the **Django Guardian SLA**, ensure compliance with these rules during any modification:

1. **Thin Views & Fat Models:** Views handle only HTTP routing, serialization, and input validation via Serializers. Models contain only data structures and invariants. Multi-model workflows must reside in `orchestrators/`.
2. **Strict Timeouts:** Every external HTTP request MUST declare a `timeout` parameter (max 5.0 seconds) to satisfy rule `guardian.W006`.
3. **No Naive Datetimes:** Every timestamp must use the timezone-aware `django.utils.timezone.now()`.
4. **Windmill Protection:** Signal receivers that invoke `.save()` must declare strict escape conditions to prevent infinite execution loops.
5. **McCabe Complexity:** Keep all orchestrator and business functions under a cyclomatic complexity of 10.
6. **No-Storytelling Rule:** Block comments must not exceed 3 lines, individual lines of comments must not exceed 120 characters, and redundant explanatory storytelling is prohibited.

---

## 🗂️ 4. Essential References

Please refer to the following local specifications before writing any lines of code:
* **Core Requirements:** `GPU_RENTAL_PRD.md`
* **User Stories:** `docs/specs/user_stories.md`
* **Technical Task Plan:** `docs/specs/technical_tasks.md`
* **Architecture Decisions:** `docs/adrs/`
* **Harness & Boot Directives:** `GEMINI.md`
