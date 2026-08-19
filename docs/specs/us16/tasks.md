# 📋 Implementation Tasks: US16 & Dashboard Polish (3-Column Layout, Scroll Preservation, Continuous Simulation & Billing Alerts)

This document specifies the concrete technical tasks to resolve dashboard layout, scroll snapping, continuous simulation balance decrements, and billing alerts.

---

## 🛠️ Task 1: 3-Column Side-by-Side Admin Dashboard Layout (`templates/admin/index.html`)
* **Description:** Restructure the Django admin home page into a clean 3-column desktop layout.
* **Layout Structure:**
  - **Column 1 (Left - ~25%):** `[Tabela de Entidades / App List]` (`#content-main`, app list).
  - **Column 2 (Middle - ~25%):** `[Últimas Modificações]` (`#content-related`, recent actions log).
  - **Column 3 (Right - ~50%):** `[Painel de Monitoramento]` (Live Telemetry, Balances & Cycles).
* **Responsive Behavior:** Stacks vertically on screens below 1200px.

---

## 🛠️ Task 2: HTMX Scroll Preservation & Targeted Updates (`templates/admin/live_dashboard_fragment.html`)
* **Description:** Prevent horizontal table scrolling from resetting to `0` on every 3-second HTMX tick.
* **Steps:**
  - 1. Add `data-preserve-scroll="true"` on all scrollable `overflow-x: auto` table wrappers.
  - 2. Implement `htmx:beforeSwap` and `htmx:afterSwap` event listeners in `index.html` to save and restore `scrollLeft` positions across HTMX polling updates.
  - 3. Add explicit `white-space: nowrap !important;` and `word-break: normal !important;` to table cells and headers.

---

## 🛠️ Task 3: Continuous Simulation Loop & Live Balance Decrement (`leases/simulation/agent_engine.py` & `leases/management/commands/run_simulation.py`)
* **Description:** Ensure running simulations keep active leases running continuously so credits decrement and usage accumulates in real-time.
* **Steps:**
  - 1. Refactor `run_simulation` command: When `--run-agents` or simulator starts, ensure active tenant leases (e.g. `happypath_agent`, `promopackage_agent`) are left in `ACTIVE` state so background ticks continuously process them.
  - 2. Verify `record_fractional_usage()` properly decrements `credit.balance`, updates `ClientUsageCycle.hours_consumed` and `total_consumption`, and persists all rows via `save(update_fields=...)`.

---

## 🛠️ Task 4: Real-Time Billing & Hardware `SystemAlert` Triggers (`billing/services/ledger.py` & `leases/simulation/worker.py`)
* **Description:** Generate `SystemAlert` records for all critical billing and telemetry events to render real-time toast alerts in Django Admin.
* **Steps:**
  - 1. In `_check_and_trigger_low_credit_warning(credit)`: Create `SystemAlert(alert_type="billing", message="...")` when credit balance drops below 20% of starting balance.
  - 2. In `MetricsSimulatorWorker.tick()`: Create `SystemAlert(alert_type="billing", message="...")` when a prepaid lease is suspended upon credit depletion.
  - 3. In `MetricsSimulatorWorker.generate_metrics()`: Create `SystemAlert(alert_type="billing", message="...")` when a GPU thermal anomaly exceeds 90°C.
  - 4. In `record_fractional_usage()`: Create `SystemAlert(alert_type="billing", message="...")` when a 30-day postpaid billing cycle closes and emits an invoice.

---

## 🛠️ Task 5: Comprehensive Unit & Integration Tests
* **Steps:**
  - 1. Add tests for `SystemAlert` generation on low-credit warning, lease depletion suspension, and thermal anomalies.
  - 2. Add test verifying continuous multi-tick balance decrement and cycle accumulation.
  - 3. Verify all 55+ test cases pass cleanly.
