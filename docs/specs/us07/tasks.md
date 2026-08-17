# 📋 [x] Implementation Tasks: US07 (GPU Fleet Dashboard & Concurrency Tracker)

This document contains the physical, actionable development tasks required to complete User Story 07.

---

## 🛠️ [x] Task 7.1: Real-Time Fleet Analytics Queries
* **Description:** Implement database-optimized aggregations for real-time dashboard stats.
* **Steps:**
  - [x] 1. Build view or database query managers in `leases` to fetch current fleet snapshot:
     - Count total active leases.
     - Count active concurrent clients.
     - Count available vs. leased physical GPU cards.
  - [x] 2. Calculate total allocated VRAM: Sum of VRAM capacity from active lease instances.
  - [x] 3. Calculate average temperature per model type.
* **Verification:** Optimize queries using `select_related()` and Django database annotations to prevent N+1 issues.

---

## 🛠️ [x] Task 7.2: Dedicated Isolation Auditor
* **Description:** Enforce strict single-tenant allocation on dedicated GPU models.
* **Steps:**
  - [x] 1. When provisioning a lease for a physical instance where `is_dedicated=True`:
     - Assert that the instance has zero active concurrent leases in the database.
     - Fail allocation if another lease is already active on the same physical card.
* **Verification:** Verify that trying to allocate a leased dedicated card triggers a resource conflict exception.

---

## 🛠️ [x] Task 7.3: Shared Concurrency Auditor
* **Description:** Limit shared physical cards to a maximum of 4 active tenants.
* **Steps:**
  - [x] 1. When provisioning a lease for a physical instance where `is_dedicated=False`:
     - Count the number of active leases currently assigned to this specific `gpu_instance_id`.
     - If count >= 4: block the lease process and look for another available physical instance.
* **Verification:** Verify that a shared instance successfully accepts up to 4 concurrent leases, but blocks a 5th.

---

## 🛠️ [x] Task 7.4: Concurrency & Auditor Unit Testing
* **Description:** Write automated test cases verifying concurrency limits and optimized DB operations.
* **Steps:**
  - [x] 1. Create `leases/tests/test_concurrency.py`.
  - [x] 2. Write test attempting to rent a single dedicated GPU model twice concurrently and assert the second attempt fails.
  - [x] 3. Write test spawning 5 concurrent leases on a single shared GPU instance and assert the 5th lease is blocked or routed to another card.
  - [x] 4. Run `django.test.utils.CaptureQueriesContext` to audit queries, verifying that dashboard analytics run with zero N+1 queries.
* **Verification:** Run `uv run  manage.py test leases.tests.test_concurrency`.
