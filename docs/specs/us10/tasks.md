# 📋 US10: Unified Prepaid/Postpaid Billing Adjustments — Implementation Tasks

This document contains the physical, actionable development tasks required to implement the US10 Billing Adjustments in the next session.

---

## 🛠️ Task 1: Database Model Extensions (`billing/models.py` & `users/models.py`)
* **Description:** Extend database schemas to support frozen prepaid balances and tracking for postpaid grace periods.
* **Steps:**
  1. Add a `frozen_prepaid_balance` field (`DecimalField`, default=`Decimal("0.00")`, `max_digits=10`, `decimal_places=2`) to the `UserCredit` model in `billing/models.py`. This will store frozen pre-paid credits during Pre->Post plan migrations.
  2. Create and apply database migrations:
     ```bash
     uv run manage.py makemigrations billing
     uv run manage.py migrate
     ```

---

## 🛠️ Task 2: Standardize Flat-Fee Deductions from Available Credits (`billing/services/ledger.py`)
* **Description:** Ensure flat-fees (such as the `$15.00` tier swap fee) are instantly paid and deducted from available pre-paid credits if the user has a positive balance, regardless of target tier.
* **Steps:**
  1. Update `invoice_flat_fee` inside `billing/services/ledger.py` to:
     - Check if the user has an active `UserCredit` record with `balance > 0`.
     - If so, instantly deduct the fee amount from `UserCredit.balance` and mark the generated `Invoice` as `PAID`.
     - Otherwise, if no pre-paid credit exists, generate the `Invoice` as `UNPAID` (which is the default behavior for postpaid targets).

---

## 🛠️ Task 3: Implement Pre-paid 80% Depletion Warning Email (`billing/tasks.py`)
* **Description:** Implement an alert system that warns prepaid users when they have consumed 80% of their starting credits.
* **Steps:**
  1. Add a `starting_balance` field to `UserCredit` (or compute consumption based on the last deposit amount) to track starting balance.
  2. In `billing/services/ledger.py` or the simulator `tick()`:
     - When a credit deduction occurs, check if the remaining `balance` is `<= 20%` of `starting_balance` (representing `>= 80%` consumption).
     - If this threshold is crossed and no alert has been sent for this cycle, trigger the asynchronous task `send_low_credit_warning_email(user_id)` to Mailpit via `steady_queue`.

---

## 🛠️ Task 4: Plan Transition Credit Freeze & Invoice Abatement (`leases/orchestrators/upgrade_flow.py`)
* **Description:** Freeze available prepaid credit during a Pre->Post plan upgrade and deduct it from the final postpaid invoice total.
* **Steps:**
  1. Update the `_assess_and_invoice_fees` or `_finalize_upgrade` steps inside `LeaseUpgradeOrchestrator` in `leases/orchestrators/upgrade_flow.py`:
     - When upgrading from a prepaid model (RTX/L4) to a postpaid model (A100/H100), obtain the user's `UserCredit` row-level lock.
     - Store the current positive balance into `UserCredit.frozen_prepaid_balance = UserCredit.balance`.
     - Set the active balance to zero: `UserCredit.balance = Decimal("0.00")` (this freezes the credit, preventing it from being spent elsewhere).
     - Save the `UserCredit` record.
  2. Update the monthly invoicing / final invoice generation logic inside `billing/services/ledger.py`:
     - When creating the final postpaid invoice for the billing period or lease closure, check if the user has `UserCredit.frozen_prepaid_balance > 0`.
     - If so, subtract the frozen balance from the invoice's final total: `Final Invoice Amount = Max(0, Postpaid Accrued Cost - UserCredit.frozen_prepaid_balance)`.
     - Reduce or reset `UserCredit.frozen_prepaid_balance` by the abated amount and save.

---

## 🛠️ Task 5: Postpaid 5-Day Grace Period, Auto-Freeze & Unfreeze Fees
* **Description:** Enforce a 5-day payment grace period for postpaid invoices, triggering account freeze and an unfreeze penalty fee if unpaid.
* **Steps:**
  1. Update `MetricsSimulatorWorker.tick()` or create a background command/task (e.g. `check_postpaid_arrears`):
     - Query all `UNPAID` postpaid invoices (`status=InvoiceStatus.UNPAID` where the model is H100 or A100).
     - Calculate the simulated elapsed duration since the invoice's `created_at` using `get_simulated_duration(created_at, now)`.
     - If the unpaid invoice is older than **5 simulated days** (`5 * 24 = 120 simulated hours`):
       - Trigger `freeze_tenant_account(user.id, keep_dedicated_gpus=False)`.
       - Generate a standard **Unfreeze Fee** invoice of `$25.00` marked as `UNPAID`.
       - Send a freeze notification email asynchronously via `steady_queue` to Mailpit.

---

## 🛠️ Task 6: Comprehensive Verification Unit Tests (`billing/tests.py`)
* **Description:** Write automated tests to verify all aspects of the US10 Billing Adjustments.
* **Steps:**
  1. Write a test case `test_prepaid_eighty_percent_warning` asserting that when credits fall to 20% or less of the starting balance, a low-credit warning email is enqueued.
  2. Write a test case `test_pre_to_post_upgrade_freezes_credit_and_abates_final_invoice` asserting:
     - Upgrading a lease from L4 to H100 freezes the current `UserCredit.balance` in `frozen_prepaid_balance` and sets `balance` to `0`.
     - The subsequent postpaid invoice is abated by the frozen amount.
  3. Write a test case `test_flat_fees_instantly_paid_by_prepaid_balance` asserting that the `$15.00` upgrade fee is instantly deducted from the prepaid credit balance, leaving the fee invoice as `PAID`.
  4. Write a test case `test_postpaid_grace_period_enforcement` asserting:
     - A postpaid unpaid invoice older than 5 simulated days triggers account freeze.
     - Active leases are terminated and physical GPUs are returned to the catalog.
     - A flat `$25.00` unfreeze fee invoice is successfully billed to the user.
