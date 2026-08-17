# 📋 [x] Implementation Tasks: US09 (Simulated Client Agents / Stress Engine)

This document contains the physical, actionable development tasks required to complete User Story 09.

---

## 🛠️ [x] Task 9.1: Simulation Runner Command (`leases/management/commands/run_simulation.py`)
* **Description:** Implement the standalone CLI command booting the simulation container.
* **Steps:**
  - [x] 1. Create management command `leases/management/commands/run_simulation.py`.
  - [x] 2. Initialize the background thread workers pool (`MetricsSimulatorWorker`).
  - [x] 3. Initialize the Simulated Client Agent Engine.
* **Verification:** Run `uv run  manage.py run_simulation` to verify persistent background execution.

---

## 🛠️ [x] Task 9.2: Agent Persona Behaviors (`leases/simulation/agent_engine.py`)
* **Description:** Implement programmatic client behavior scripts.
* **Steps:**
  - [x] 1. Create module `leases/simulation/agent_engine.py`.
  - [x] 2. Implement four distinct customer agent profile threads or routines:
     - [x] **HappyPathAgent:** Triggers lease start, runs standard workload ticks, terminates lease, and settles payment invoice.
     - [x] **DelinquentAgent:** Spawns lease with low credits ($1.00), lets simulation deplete credits, and asserts auto-shutdown works.
     - [x] **UpgradeSeekerAgent:** Initiates L4 lease, triggers dynamic swap to H100 after 2 ticks, and validates updated dynamic billing rate and flat fees.
     - [x] **AbusiveAgent:** Floods request endpoints with API tokens to trigger rate-limiting HTTP 429 response codes.
* **Verification:** Verify that starting the simulation engine runs these agents concurrently in the background.

---

## 🛠️ [x] Task 9.3: Compliance Audit Reporting
* **Description:** Output clear audit logs detailing stress engine scenarios.
* **Steps:**
  - [x] 1. Write detailed logging metrics reporting agent steps and results.
  - [x] 2. Ensure the engine logs warnings if any agent fails to encounter their expected outcome (e.g., if a delinquent lease is not suspended).
* **Verification:** Verify logs clearly prove system compliance across all scenarios.

---

## 🛠️ [x] Task 9.4: Stress Engine Integration Testing
* **Description:** Execute and assert correct end-to-end integration flows.
* **Steps:**
  - [x] 1. Create `leases/tests/test_agent_engine.py`.
  - [x] 2. Write an integration test that runs the `AgentEngine` in a mock/accelerated mode and asserts all customer scenarios resolve successfully.
* **Verification:** Run `uv run  manage.py test leases.tests.test_agent_engine`.
