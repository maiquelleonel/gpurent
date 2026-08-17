# 📋 [x] Implementation Tasks: US04 (Complex Billing & Payment Tier Rules)

This document contains the physical, actionable development tasks required to complete User Story 04.

---

## 🛠️ [x] Task 4.1: Pre-Paid Credit Check & Depletion Ticker
* **Description:** Enforce automatic lease suspension when prepaid balance is exhausted.
* **Steps:**
  - [x] 1. Implement credit deduction checks inside the background simulation tick logic (for RTX 4090 & L4 leases).
  - [x] 2. On every tick, fetch the user's `UserCredit` and lock the row using `select_for_update()`.
  - [x] 3. Calculate usage balance consumption for the simulated period.
  - [x] 4. If `balance <= 0.00`:
     - Update lease status to `SUSPENDED_PAYMENT`.
     - Update physical `GPUInstance` status to `AVAILABLE`.
     - Gracefully decommission active telemetry thread.
* **Verification:** Test credit depletion triggers safe state transition and card release.

---

## 🛠️ [x] Task 4.2: Volume Discount Enforcement
* **Description:** Apply a 10% discount on hourly rates when a single user rents multiple concurrent cards of the same model.
* **Steps:**
  - [x] 1. Inside the pricing engine/calculator, count the active concurrent leases for the target user and model type.
  - [x] 2. If active lease count > 5:
     - Apply a 10% discount multiplier to the model's standard hourly fee.
     - Store the calculated `volume_discount_applied` on the `RentalLease` model.
* **Verification:** Verify that users renting 6 instances of RTX 4090 are billed at $0.396/hr instead of $0.44/hr.

---

## 🛠️ [x] Task 4.3: Dedicated Upfront Payment Verification
* **Description:** Restrict dedicated GPU allocations until upfront payment is confirmed via mock billing.
* **Steps:**
  - [x] 1. When a user requests a lease for a dedicated instance (`is_dedicated=True`):
     - Put lease status into `PROVISIONING`.
     - Generate a pre-paid Invoice inside `billing/models.py`.
     - Call the `charge_prepaid_card` service to process payment against the local Mock server.
     - If payment is confirmed: transition lease status to `ACTIVE`.
     - If payment fails: fail transition, release card to inventory.
* **Verification:** Verify that dedicated instances cannot start active metric ticks without successful gateway confirmations.

---

## 🛠️ [x] Task 4.4: Complex Billing Unit Testing
* **Description:** Write comprehensive test suites for billing tiers, volume discounts, and pre-paid limits.
* **Steps:**
  - [x] 1. Create `billing/tests/test_billing_rules.py`.
  - [x] 2. Write a test where a pre-paid user starts an RTX 4090 lease with $1.00 credit and verify it auto-suspends on depletion.
  - [x] 3. Write a test registering 6 concurrent RTX 4090 leases for a user and verify the 10% discount is correctly calculated.
  - [x] 4. Write a test asserting that attempting to lease a dedicated H100 with a declined payment gateway fails the orchestration process.
* **Verification:** Run `python manage.py test billing.tests.test_billing_rules` and ensure all tests pass.
