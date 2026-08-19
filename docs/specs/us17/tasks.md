# 📋 Implementation Tasks: US17 — Dynamic Continuous Simulation, Auto-Provisioning & Postpaid Settlement Lifecycle

This document specifies the technical tasks for implementing dynamic continuous simulation, automatic GPU provisioning with toast alerts, postpaid 30-day settlement, and active cycle dashboard filtering.

---

## 🛠️ Task 1: Dashboard Active-Only Cycles Filter & Provisioning Toast Styling (`leases/views.py`)
* **Description:** Filter dashboard usage cycles to display only active cycles (`is_active=True`), removing settled/inactive cycles. Add visual support for `provisioning` alert toasts in `admin_live_alerts_endpoint`.
* **Steps:**
  - 1. In `admin_live_dashboard_endpoint`: Change `usage_cycles` query to `ClientUsageCycle.objects.filter(is_active=True).select_related("client").order_by("-created_at")[:25]`.
  - 2. In `admin_live_alerts_endpoint`: Add condition for `alert_type in ["provisioning", "hardware"]` with 🚀 icon, title `HARDWARE READY` / `FLEET PROVISIONED`, border `#2563eb` (blue-600) and background `#dbeafe` (blue-100).

---

## 🛠️ Task 2: Postpaid Invoice Settlement Service & Cycle Invalidation (`billing/services/ledger.py`)
* **Description:** Implement clean service functions to settle postpaid invoices and manage cycle status upon payment.
* **Steps:**
  - 1. In `billing/services/ledger.py`, implement `settle_postpaid_invoice(invoice_id, payment_method="mock_gateway")`:
    - Validates invoice is `UNPAID`.
    - Dispatches payment to mock gateway.
    - Transitions `invoice.status = InvoiceStatus.PAID` and sets `settled_at = timezone.now()`.
    - Creates a `SystemAlert(alert_type="billing", message="💵 Postpaid invoice of ${amount} paid successfully by customer {username}!")`.
    - Dispatches transactional payment confirmation email.
  - 2. Ensure closed cycles (`is_active=False`) remain closed once invoiced/settled.

---

## 🛠️ Task 3: Hardware Auto-Provisioning with Real-Time Alerts (`leases/services/fleet_provisioning.py` or `leases/orchestrators/lease_flow.py`)
* **Description:** Provide helper function to provision new physical GPU instances into the catalog and notify admins via toast alert.
* **Steps:**
  - 1. Implement `auto_provision_gpu(model_name=None, is_dedicated=False) -> GPUInstance`:
    - Picks a GPU model (or specified model).
    - Creates a new `GPUInstance` with a generated serial number (e.g. `GPU-{MODEL_TAG}-{RANDOM}`).
    - Emits a `SystemAlert(alert_type="provisioning", message="🚀 New GPU provisioned and ready for lease: {model.name} (Serial: {serial_number})")`.

---

## 🛠️ Task 4: Dynamic Continuous Simulation Engine (`leases/simulation/agent_engine.py` & `leases/simulation/worker.py`)
* **Description:** Enhance simulation engine to run dynamic lifecycle events on ongoing simulation ticks.
* **Steps:**
  - 1. In `spawn_persistent_demo_leases()`:
    - Initialize `enterprise_postpaid` with an active cycle having `hours_consumed = Decimal("719.5000")` (approaching 30 simulated days / 720h) so that on the 1st/2nd tick the cycle closes, generates an invoice, alerts the admin, and opens a new cycle.
  - 2. In `MetricsSimulatorWorker.tick()`:
    - Add dynamic event step `_process_dynamic_simulation_events()` (every N ticks or probabilistically):
      - **Postpaid Auto-Settlement:** Check for `UNPAID` postpaid invoices older than 1-2 ticks and auto-pay them via `settle_postpaid_invoice`.
      - **New Client Inflow:** Periodically spawn a new dynamic client (e.g. `client_alpha`, `client_beta`), credit wallet or assign postpaid, and rent an available GPU.
      - **Auto-Provisioning:** If available instances of a model fall to 0 or on scheduled interval, auto-provision a new GPU instance with toast alert.
      - **Upgrades / Churn:** Occasionally trigger a mid-lease upgrade or complete a lease.

---

## 🛠️ Task 5: Simulation Runner CLI Updates (`leases/management/commands/run_simulation.py`)
* **Description:** Ensure CLI output reflects dynamic events, auto-provisioned GPUs, closed cycles, and paid invoices in real-time.

---

## 🛠️ Task 6: Comprehensive Unit & Integration Tests (`leases/tests/test_simulation.py` & `leases/tests/test_live_alerts.py`)
* **Description:** Add test cases for all new flows:
  - 1. Test active-only usage cycles filtering in dashboard.
  - 2. Test auto-provisioning GPU creation and `SystemAlert` generation.
  - 3. Test postpaid invoice settlement service and billing alert toast.
  - 4. Test dynamic simulation tick executing postpaid cycle closure and subsequent settlement.
  - 5. Verify all tests pass with 100% success.
