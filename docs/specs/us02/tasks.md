# 📋 [x] Implementation Tasks: US02 (Background Consumption Simulation)

This document contains the physical, actionable development tasks required to complete User Story 02.

---

## 🛠️ [x] Task 2.1: Metric Snapshot Schema (`leases/models.py`)
* **Description:** Implement the model logging telemetry from leased instances.
* **Steps:**
  - [x] 1. Define model `MetricSnapshot` in `leases/models.py` with fields:
     - `id`: UUID (Primary Key)
     - `gpu_instance`: ForeignKey to `GPUInstance` with `related_name="snapshots"`
     - `vram_used_gb`: DecimalField
     - `compute_load_pct`: DecimalField
     - `temperature_c`: DecimalField
     - `is_thermal_alert`: BooleanField (default=False)
     - `timestamp`: DateTimeField (default=timezone.now)
* **Verification:** Create and apply migrations. Run database verification commands.

---

## 🛠️ [x] Task 2.2: Simulation Worker Implementation (`leases/simulation/worker.py`)
* **Description:** Build the thread-based metrics simulation loop representing conceptual server workloads.
* **Steps:**
  - [x] 1. Create module `leases/simulation/worker.py`.
  - [x] 2. Implement `MetricsSimulatorWorker` as a thread-safe singleton or long-lived process loop.
  - [x] 3. Run tick loops at a configurable interval (default: 5 seconds).
  - [x] 4. Query database for leases with status `ACTIVE`.
* **Verification:** Verify that starting and stopping the simulator doesn't hang main processes or leak memory.

---

## 🛠️ [x] Task 2.3: Telemetry Ranges & Watchdog (`leases/simulation/worker.py`)
* **Description:** Calculate realistic metric fluctuations and trigger thermal flags.
* **Steps:**
  - [x] 1. For each active lease's GPU instance:
     - Calculate random `vram_used_gb` within 40% to 95% of its Model's max capacity.
     - Calculate random `compute_load_pct` between 0.0% and 100.0%.
     - Calculate random `temperature_c` between 65°C and 85°C.
  - [x] 2. If simulated temperature exceeds 90°C:
     - Log a warning with the serial number.
     - Set `is_thermal_alert=True` in the metric record.
  - [x] 3. Save the snapshot to the database.
* **Verification:** Verify snapshots generated in the DB reflect these ranges and flags correctly.

---

## 🛠️ [x] Task 2.4: Simulation Unit Testing
* **Description:** Thoroughly test the metrics generation loop.
* **Steps:**
  - [x] 1. Create `leases/tests/test_simulation.py`.
  - [x] 2. Start worker and trigger a single manual simulation tick.
  - [x] 3. Assert `MetricSnapshot` is created and links correctly to the target active GPU instance.
  - [x] 4. Force a simulated high-temperature reading and assert `is_thermal_alert` is set to `True`.
* **Verification:** Run `uv run  manage.py test leases.tests.test_simulation` and secure 100% test coverage.
