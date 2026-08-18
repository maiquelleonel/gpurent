# 👥 User Stories: GPURent Conceptual Platform

This document describes the business-centric User Stories derived from the Product Requirements Document (PRD). Each story details the user value, acceptance criteria, and compliance metrics.

---

## US01: GPU Inventory Management & NVIDIA Catalog

**As a** GPU cloud customer  
**I want to** browse a highly realistic NVIDIA GPU inventory with transparent on-demand hourly pricing  
**So that** I can rent the specific GPU model suited for my AI, LLM, or compute workload.

### Acceptance Criteria
1. **Catalog Integrity:** The platform must seed and offer the following exact catalog models:
   - **NVIDIA H100 (80GB SXM5):** $4.76 / hour
   - **NVIDIA A100 (80GB PCIe):** $1.88 / hour
   - **NVIDIA A100 (40GB PCIe):** $1.21 / hour
   - **NVIDIA L4 (24GB PCIe):** $0.55 / hour
   - **NVIDIA RTX 4090 (24GB):** $0.44 / hour
2. **Instance States:** Individual physical GPU instances (`GPUInstance`) must track their `serial_number`, `is_dedicated` boolean, and status (`AVAILABLE`, `LEASED`, `MAINTENANCE`).
3. **Lease Lifecycle:** The lease state machine must transition through:
   `PROVISIONING` ➔ `ACTIVE` ➔ `TERMINATING` ➔ `COMPLETED` or `SUSPENDED_PAYMENT`.

### Compliance Metrics
* **Django Guardian Compliance:** All DB operations use timezone-aware timestamps (`django.utils.timezone.now()`). No N+1 queries during catalog listing.

---

## US02: Background GPU Consumption Simulation (Conceptual Workers)

**As a** platform administrator  
**I want to** automatically simulate live GPU utilization metrics (VRAM, compute, temperature) for leased instances in background worker threads  
**So that** we can monitor active utilization and trigger thermal flags without requiring physical hardware connections.

### Acceptance Criteria
1. **Periodic Metrics Generation:** A background worker must tick every 5 seconds for active leases.
2. **Realistic Fluctuations:** Metrics must fall within realistic ranges based on the specific GPU Model:
   - **VRAM Usage:** 40% to 95% of model capacity.
   - **Compute Load:** 0% to 100%.
   - **Temperature:** 65°C to 85°C.
3. **Historical Snapshots:** Every tick must persist a `MetricSnapshot` including `gpu_instance_id`, `vram_used`, `compute_load`, `temperature`, and `timestamp`.
4. **Thermal Watchdog:** If any instance temperature exceeds 90°C, the system must trigger an immediate thermal alert (flagged on the snapshot/log).

### Compliance Metrics
* **No Blocked Threads:** Worker execution must run on non-blocking background threads or scheduled tasks.

---

## US03: Mid-Lease Upgrades & Dynamic Scaling

**As a** developer renting a GPU  
**I want to** upgrade my active lease to a more powerful GPU model or scale up VRAM mid-lease  
**So that** I can scale resources dynamically without manually destroying and rebuilding my development environments.

### Acceptance Criteria
1. **Upgrade Orchestration:** Swapping GPU tiers mid-lease must:
   - Lock the current lease transactionally.
   - Safely terminate the running background worker/simulation for the old GPU.
   - Calculate and invoice the accrued billing amount for the time spent on the old GPU.
   - Allocate the new GPU model instance and update the lease target.
   - Boot the background worker/simulation representing the new GPU's capacity.
2. **Upgrade Fees:** Apply flat upgrade charges dynamically:
   - **Mid-lease tier swaps (e.g., L4 ➔ A100):** $15.00 flat fee.
   - **VRAM scaling increments (e.g., A100 40GB ➔ A100 80GB):** $5.00 flat fee.

### Compliance Metrics
* **McCabe Complexity:** The upgrade flow orchestrator must keep its cyclomatic complexity < 10.
* **Race Condition Prevention:** The swap must run inside a strict database transaction (`transaction.atomic()`).

---

## US04: Complex Billing & Payment Tier Rules

**As a** cloud platform administrator  
**I want to** enforce automated billing tiers, payment limits, and bulk discounts  
**So that** the platform protects revenue, minimizes bad debt, and incentivizes bulk purchases.

### Acceptance Criteria
1. **Pre-Paid Credit Tier (RTX 4090 & L4):**
   - Users consume a pre-loaded balance.
   - Checked at every metric tick.
   - If credits hit $0, the instance is immediately shut down and marked as `SUSPENDED_PAYMENT`.
2. **Post-Paid Invoiced Tier (A100 & H100):**
   - Users accumulate usage on a monthly deferred invoice model.
3. **Dedicated Upfront Payment (Is Dedicated = True):**
   - Requires upfront processing and receipt validation via mock payment before transitioning to `LEASED`.
4. **Volume Discounts:**
   - Any customer renting **more than 5 instances of the exact same GPU model** simultaneously receives a **10% discount** on the hourly rate for all active instances of that model.

### Compliance Metrics
* **No Signal Windmills:** Balance depletion and suspension logic must not trigger recursive save loops.

---

## US05: Local Payment Mock Integration

**As a** system developer  
**I want to** integrate the billing service with a local mock payment server (Stripe mock or Mockoon)  
**So that** we can execute and validate payment gateways, credit cards, and invoicing flows deterministically offline.

### Acceptance Criteria
1. **Mock Service:** Build a service client (`services/billing.py`) pointing to a local mock container (Stripe mock on `http://localhost:12111` or Mockoon on `http://localhost:8081`).
2. **Transaction Scenarios:** Support simulating successful transactions, card declines, refunds, and invoice processing.
3. **Timeout Protection:** Every outgoing HTTP request to the local mock must enforce strict connection and read timeout values (maximum 5 seconds) to avoid hanging worker threads.

### Compliance Metrics
* **Django Guardian SLA:** All external integrations live in `services/`, keeping orchestrators and views thin. Strictly enforces `timeout` to pass `guardian.W006` rule.

---

## US06: Time-Scaled Workload Execution

**As a** QA / Test Engineer  
**I want to** accelerate simulated time with a high scale factor (e.g., 1 real-world minute = 2 simulated hours)  
**So that** we can test multi-day lease cycles, account credit depletion, and long-term invoices within minutes of execution.

### Acceptance Criteria
1. **Configurable Time Scale:** Implement `TIME_SCALE_FACTOR` (default = 120).
2. **Simulated Time Calculations:** When calculating lease elapsed time and outstanding balances, multiply real elapsed time by `TIME_SCALE_FACTOR`.
3. **Background Sync:** The metric snapshots and worker billing checks must calculate billing accrual rates based on the accelerated timeline.

### Compliance Metrics
* **Unit Test Coverage:** Fully verified with tests mocking time offsets to guarantee deterministic calculations.

---

## US07: GPU Fleet Dashboard & Concurrency Tracker

**As an** infrastructure manager  
**I want to** view real-time concurrency metrics, isolation levels, and aggregated fleet statistics  
**So that** I can track physical capacity utilization and audit virtual instances.

### Acceptance Criteria
1. **Real-time Concurrency Metrics:** Tracks:
   - Total active clients.
   - Total active concurrent leases.
   - Total available vs. leased GPUs.
2. **Isolation Auditor:**
   - **Dedicated Instances:** Restrict to exactly 1 active lease/tenant per physical card.
   - **Shared Instances:** Allow up to 4 tenants/leases per card, distributing resources appropriately.
3. **Aggregated capacity metrics:** Show real-time VRAM allocation sum and current average thermals per model type.

### Compliance Metrics
* **Optimized Queries:** Dashboard query logic must use `select_related`, `prefetch_related`, and database-level annotations (`Sum`, `Count`, `Avg`) to prevent N+1 performance bottlenecks.

---

## US08: Developer API Token & Rate-Limiting Audit

**As an** API security specialist  
**I want to** log all incoming API token requests and rate-limit client accounts  
**So that** the platform is protected against DDoS attempts, scraping, and service degradation.

### Acceptance Criteria
1. **API Audit Logs:** Model `TokenUsage` must log:
   - `api_token_id`
   - `endpoint`
   - `request_timestamp`
   - `response_status`
2. **Quota Rate-Limiter:** Enforce a limit of 60 requests per minute per developer token.
3. **Graceful Rejection:** If a token exceeds the limit, return a standard `429 Too Many Requests` response.
4. **Volume Logs:** Expose aggregated counts per hour to analyze load spikes.

### Compliance Metrics
* **Performance:** Ensure rate-limiting lookup utilizes indexes on the token and timestamp.

---

## US09: Simulated Client Agents (Stress Test Engine)

**As a** QA Automation Lead  
**I want to** execute automated simulated agents mimicking diverse client profiles (Happy-Path, Delinquent, Upgrade-Seeker, Abusive) in the background  
**So that** the entire ecosystem undergoes continuous, realistic stress testing and billing verification.

### Acceptance Criteria
1. **Agent Engine:** A background runner that boots multiple independent agents:
   - **Happy-Path Customer:** Rents, runs standard ticks, completes lease, pays invoice successfully.
   - **Delinquent Customer:** Rents L4/RTX 4090, allows balance to deplete, verifies auto-suspension and instance shutdown.
   - **Upgrade Seeker:** Rents L4, triggers upgrade to H100 mid-lease, verifies transition, upgrade fees, and revised hourly rates.
   - **Abusive Customer:** Spins up multi-shared leases and flood-requests the API, verifying rate-limiting triggers `429` responses.

### Compliance Metrics
* **Execution Logs:** Generates distinct, trackable audit reports proving correct state validation across all scenarios.

---

## US10: Unified Prepaid/Postpaid Billing Adjustments

**As a** platform product owner  
**I want to** implement cohesive prepaid balance depletion alerts, plan transitions with frozen credit deductions, flat-fee deductions, and postpaid late-payment grace periods with unfreeze fees  
**So that** our business models are robust, safe, and protect both the customer experience and infrastructure revenue.

### Acceptance Criteria
1. **Pre-Paid 80% Alert:** In the prepaid tier, when a user's consumption reaches 80% of their starting credits, the system automatically sends a low-credit warning email.
2. **Pre-Paid Freeze:** Once the prepaid balance reaches `$0.00` or below, the account enters a "Freezing/Suspension" state, the lease is immediately suspended, an email alert is sent, and the physical GPU is freed back to the catalog.
3. **Plan Transitions (Upgrade Pre -> Post):** On upgrade from a prepaid GPU (RTX/L4) to a postpaid GPU (A100/H100), the user's available prepaid credit balance is **frozen**. At the end of the billing period, this frozen credit is deducted from their final postpaid invoice.
4. **Flat-Fee Deductions:** Any flat fees (like the `$15.00` tier swap fee) are instantly paid and deducted from the user's prepaid credits if they have positive balance.
5. **Post-Paid 5-Day Grace Period:** Postpaid invoices must be paid within **5 days** of consumption.
6. **Post-Paid Late Payment Freeze & Unfreeze Fee:** If a postpaid invoice remains unpaid for more than 5 days, the account is frozen/suspended, the active lease is terminated, and a standard unfreeze fee is added to their outstanding bill.

### Compliance Metrics
* **DRY Architecture:** Standardizes processing across the `BaseOrchestrator` clean-architecture layer.
* **100% Code Coverage:** Fully tested with unit tests mocking time offsets to guarantee deterministic calculations.
