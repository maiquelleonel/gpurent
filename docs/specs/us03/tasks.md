# 📋 [x] Implementation Tasks: US03 (Mid-Lease Upgrades & Dynamic Scaling)

This document contains the physical, actionable development tasks required to complete User Story 03.

---

## 🛠️ [x] Task 3.1: Upgrade Flow Orchestrator (`leases/orchestrators/upgrade_flow.py`)
* **Description:** Implement the mid-lease tier swap workflow.
* **Steps:**
  - [x] 1. Create module `leases/orchestrators/upgrade_flow.py`.
  - [x] 2. Define function `upgrade_lease_tier(lease_id, target_model_id)`.
  - [x] 3. Wrap the execution block inside `transaction.atomic()`.
* **Verification:** Check that imports and basic function signatures compile correctly.

---

## 🛠️ [x] Task 3.2: Accrued Settlement & Old Decommissioning
* **Description:** Halt the old GPU simulation and settle billing accrued up to the current millisecond.
* **Steps:**
  - [x] 1. Obtain a lock on the `RentalLease` row (`select_for_update()`).
  - [x] 2. Calculate the exact elapsed duration on the old GPU model.
  - [x] 3. Invoke `billing` ledger service to invoice the accrued amount based on the previous rate.
  - [x] 4. Release the old `GPUInstance` (mark status as `AVAILABLE`).
* **Verification:** Ensure that old metric generation processes for this instance are terminated gracefully.

---

## 🛠️ [x] Task 3.3: Assess Flat Upgrade Fees
* **Description:** Apply the dynamic pricing fee structure depending on the upgrade type.
* **Steps:**
  - [x] 1. Compare the old GPU Model specs to the new target GPU Model specs.
  - [x] 2. Determine the fee type:
     - **Mid-lease Tier Swap (different model family, e.g., L4 ➔ A100):** Add a flat $15.00 fee.
     - **VRAM scaling increment (same model family, e.g., A100 40GB ➔ A100 80GB):** Add a flat $5.00 fee.
  - [x] 3. Invoice this flat upgrade fee directly through the `billing` ledger service.
* **Verification:** Check that invoices created inside DB contain correct amounts and labels.

---

## 🛠️ [x] Task 3.4: Target Allocation & Simulator Initiation
* **Description:** Claim the new physical instance and start its background simulation thread.
* **Steps:**
  - [x] 1. Query `GPUInstance` for available targets of the new model. Raise an exception if inventory is exhausted.
  - [x] 2. Set instance status to `LEASED`.
  - [x] 3. Re-assign the lease's target instance and reset `started_at` to the current time.
  - [x] 4. Re-launch metric ticks representing the new model's capacity.
* **Verification:** Confirm the lease updates successfully in the DB and background worker telemetry immediately adopts the new GPU's footprint.

---

## 🛠️ [x] Task 3.5: Upgrade Unit Testing
* **Description:** Write comprehensive test cases for mid-lease upgrades.
* **Steps:**
  - [x] 1. Create `leases/tests/test_upgrades.py`.
  - [x] 2. Test a tier swap (RTX 4090 ➔ H100) and verify that a $15.00 flat fee and accrued cost are charged.
  - [x] 3. Test VRAM scaling (A100 40GB ➔ A100 80GB) and verify a $5.00 fee.
  - [x] 4. Verify transaction rollback (assert no fees or instance state changes happen if physical allocation fails).
* **Verification:** Run `uv run  manage.py test leases.tests.test_upgrades` and achieve 100% test coverage.
