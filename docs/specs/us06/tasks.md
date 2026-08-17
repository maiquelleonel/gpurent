# 📋 [x] Implementation Tasks: US06 (Time-Scaled Workload Execution)

This document contains the physical, actionable development tasks required to complete User Story 06.

---

## 🛠️ [x] Task 6.1: Time Scale Configuration & settings
* **Description:** Implement accelerated timeline multiplier inside Django settings.
* **Steps:**
  - [x] 1. Add `TIME_SCALE_FACTOR = 120` to `gpurent/settings.py`.
  - [x] 2. Expose settings parameter inside a utility wrapper.
* **Verification:** Ensure the setting is loaded correctly in uv run  interactive shells.

---

## 🛠️ [x] Task 6.2: Duration Acceleration Calculator (`leases/utils/time_scale.py`)
* **Description:** Multiply real-world elapsed time by the time scale factor.
* **Steps:**
  - [x] 1. Create module `leases/utils/time_scale.py`.
  - [x] 2. Define `get_simulated_duration(started_at, ended_at)`:
     - Compute real elapsed seconds: `(ended_at - started_at).total_seconds()`.
     - Multiply by `settings.TIME_SCALE_FACTOR`.
     - Return simulated duration (e.g., converting physical minutes to simulated hours).
* **Verification:** Check math on sample intervals (e.g., 30 physical seconds * 120 factor = 3600 simulated seconds = 1 simulated hour).

---

## 🛠️ [x] Task 6.3: Billing Engine Time Integration
* **Description:** Integrate the simulated duration calculator into billing ledger evaluations.
* **Steps:**
  - [x] 1. Replace any raw real-world elapsed duration computations inside the billing orchestrators with `get_simulated_duration`.
  - [x] 2. Ensure background thread ticking consumption updates pre-paid balance credits using the scaled rate.
* **Verification:** Verify that 1 minute of physical worker execution on an RTX 4090 ($0.44/hr) with factor 120 bills the user for exactly 2 hours ($0.88).

---

## 🛠️ [x] Task 6.4: Time Scale Unit Testing
* **Description:** Assert that time scale multiplications operate deterministically.
* **Steps:**
  - [x] 1. Create `leases/tests/test_time_scale.py`.
  - [x] 2. Mock `started_at` to be 1 physical minute in the past and assert the simulated billing calculations reflect 2 simulated hours.
  - [x] 3. Validate balance deduction routines execute correctly against the accelerated timeframe.
* **Verification:** Run `uv run  manage.py test leases.tests.test_time_scale`.
