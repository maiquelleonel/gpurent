# 📑 Product Requirements Document (PRD)
## Project: GPURent — Conceptual GPU Rental Platform

---

## 1. Executive Summary

**GPURent** is a high-performance conceptual platform for renting cloud GPU instances. Users can request GPU instances, and the platform orchestrates the lease state machine (Provisioning -> Active -> Terminating -> Billed). 

To avoid the overhead of physical hardware monitoring, the application implements **Conceptual Workers** (simulated clients) that generate synthetic GPU utilization metrics in background threads. To validate billing resilience and platform transparency, the project integrates a **Local Payment Mock Server**, paired with **Simulated Client Agents** that mimic life-like user behavior (upgrades, credit depletion). It also implements a robust **GPU Fleet Monitoring & Token Usage Analytics** system to track concurrency, dedicated vs. shared resources, and API token quota consumption under heavy loads.

---

## 2. Core Architectural Mandates (The Django Guardian SLA & DDD)

This project must be designed from the ground up to comply with **django-guardian**'s core principles and a strict **Domain-Driven Design (DDD)** bounded context model:

1. **Modular Django Apps (DDD Bounded Contexts):**
   - **`users` (Authentication & Security Domain):** Handles API key management, request logging, and rate limiting (`TokenUsage`).
   - **`billing` (Financial & Payment Domain):** Manages pre-paid credits (`UserCredit`), invoicing (`Invoice`), volume discounts, upgrade charges, and external payment gateway clients.
   - **`leases` (Inventory & Rental Domain):** Manages the physical NVIDIA catalog (`GPUModel`, `GPUInstance`), rental lease state machines (`RentalLease`), and metric collection (`MetricSnapshot`).
2. **Thin Views & Lean Models (Anti-God Object):**
   - Views handle only HTTP, serialization, and schema validation.
   - Models store only data structures, internal invariants, and lean properties. No domain-crossing queries or external API communications are allowed in the Model layer.
3. **Services vs. Orchestrators Separation (SOLID):**
   - `services/` (external integration logic) handles third-party APIs (e.g., interfacing with local Stripe payment mocks, simulated notifications) with strict timeout boundaries.
   - `orchestrators/` (internal business orchestration) manages state-machine transitions, multi-app collaborations, dynamic pricing applications, and mid-lease upgrades.
4. **No Naive Datetimes:** Every timestamp uses `django.utils.timezone.now()`.
5. **No Blocked Threads:** All external client/HTTP communications (including payments mock calls) have strict `timeout` configurations to satisfy `guardian.W006`.
6. **No Signal Windmills:** Senders and receivers are protected from infinite save recursion.
7. **Strict Context Boundaries:** Domain apps must interact with each other via explicit, decoupled service calls or interface bridges, never via deep foreign-key traversals or direct database modifications of other contexts.

---

## 3. Detailed Feature Specifications

### Feature 1: GPU Inventory & Real-world NVIDIA Catalog
The inventory represents a highly realistic cloud GPU fleet based on actual market pricing (on-demand rates):
* **NVIDIA Models & Rates:**
  * **NVIDIA H100 (80GB SXM5):** $4.76 / hour — Designed for LLM training and heavy AI workloads.
  * **NVIDIA A100 (80GB PCIe):** $1.88 / hour — Designed for generic deep learning and inference.
  * **NVIDIA A100 (40GB PCIe):** $1.21 / hour — Cost-effective deep learning inference.
  * **NVIDIA L4 (24GB PCIe):** $0.55 / hour — Specialized for video processing and light inference.
  * **NVIDIA RTX 4090 (24GB):** $0.44 / hour — High-end consumer GPU for budget developer workloads.
* **Models:**
  * `GPUModel`: Name, VRAM capacity, and price per hour.
  * `GPUInstance`: A specific GPU card in the inventory (with fields like `serial_number`, `status: [AVAILABLE, LEASED, MAINTENANCE]`, `is_dedicated`).
  * `RentalLease`: Tracks customer renting of a GPU, including:
    * `status: [PROVISIONING, ACTIVE, TERMINATING, COMPLETED, SUSPENDED_PAYMENT]`
    * `started_at`, `ended_at`, `total_billed_amount`.

### Feature 2: Background Consumption Simulation (Conceptual Workers)
* **Concept:** Background task workers (using standard threads or Celery tasks) simulate GPU consumption.
* **Worker Behavior:**
  * Runs a tick loop every 5 seconds.
  * Generates random but realistic metrics based on the GPU Model's capacity: VRAM (fluctuating 40% - 95%), Compute Load (up to 100%), and Temperature (65°C - 85°C).
  * Stores metric snapshots in `MetricSnapshot` model for analytics.
  * Automatically flags thermal alerts if Temperature > 90°C.

### Feature 3: Mid-Lease Upgrades & Dynamic Scaling
To simulate cloud elastic computing, users can request GPU tier upgrades or VRAM increments mid-lease:
* **The Orchestration Flow (`orchestrators/upgrade_flow.py`):**
  * When a user requests an upgrade (e.g., upgrading from RTX 4090 to A100 mid-lease), the orchestrator must:
    1. Lock the active `RentalLease` inside a transaction.
    2. Gracefully terminate the running conceptual simulation worker of the old instance.
    3. Calculate the accrued fee for the period spent on the old GPU and invoice it.
    4. Allocate the new GPU model instance, update `RentalLease` relationship, and boot the new simulation worker with updated capacity.
    5. Dynamically apply **Upgrades Fees** (e.g., $15.00 flat fee for mid-lease tier swaps, or $5.00 fee for VRAM scaling increments).

### Feature 4: Complex Billing & Payment Tier Rules
The orchestrator must enforce highly specific enterprise billing strategies:
* **Billing Tiers:**
  * **Pre-Paid Credit Tier (RTX 4090 & L4):** Users consume pre-loaded balance credits. The orchestrator checks credits at every tick. If credits hit $0, the instance is automatically shut down and marked `SUSPENDED_PAYMENT`.
  * **Post-Paid Invoiced Tier (A100 & H100):** Users are billed at the end of the month via deferred invoices.
  * **Dedicated Instances Tier (Is Dedicated = True):** Requires **upfront payment** (pre-paid invoice processed and confirmed via mock billing before the GPUInstance transitions to `LEASED`).
* **Volume Discounts:**
  * Customers alugando **mais de 5 instâncias de GPU do mesmo modelo** recebem um desconto de volume de **10%** sob a tarifa horária daquele modelo.

### Feature 5: Local Payment Mock Integration
To enable offline development and deterministic payment flow testing, the platform integrates with a local payment mock server.
* **Implementation Options:**
  * **`stripe-mock` (Official):** A lightweight container running the official Stripe mock server.
    ```bash
    docker run --rm -it -p 12111-12112:12111-12112 stripe/stripe-mock
    ```
    *Usage in Service:* Point the Stripe API base URL locally: `stripe.api_base = "http://localhost:12111"`.
  * **Mockoon:** A declarative HTTP mock server (running locally at `http://localhost:8081`) to simulate custom payment gateway responses (success, failed transactions, refunds).
* **Billing Service (`services/billing.py`):**
  * Interfaces with the mock server.
  * Ensures all HTTP requests use strict timeout arguments to avoid hanging threads.

### Feature 6: Time-Scaled Workload Simulator
* **The Problem:** Waiting 1 real-world hour to test 1 hour of GPU billing is inefficient.
* **The Solution:** A time-scaling simulator setting (e.g. `TIME_SCALE_FACTOR = 120`, making **1 real-world minute = 2 simulated hours**).
* **Behavior:**
  * Background worker ticks represent accelerated simulated periods.
  * Billing and lease duration calculations multiply real-world time elapsed by `TIME_SCALE_FACTOR` to simulate days and weeks of billing, account delinquencies, and automatic credit depletion quickly.

### Feature 7: GPU Fleet Monitoring & Concurrency Tracker
To maintain high infrastructure availability, the platform tracks fleet allocation and client concurrency:
* **Fleet Dashboard & Analytics:**
  * **Concurrency Metrics:** Tracks total active clients, active concurrent leases, and available vs. leased GPUs in real-time.
  * **Isolation Auditor:** Distinguishes between **Dedicated Instances** ( strictly 1 tenant/lease per physical card) and **Shared Instances** (allowing multiple client worker workloads to share the same GPU resources, scaling up to a concurrency limit of 4 tenants per card).
  * **Model Capacity Tracking:** Aggregates real-time allocated VRAM and thermal states across the fleet.

### Feature 8: API Token Usage & Quota Audit
To secure API access and monitor tenant usage volume, the application tracks requests made via developer tokens:
* **Token Usage Analytics:**
  * **Model:** `TokenUsage` tracks `api_token_id`, `endpoint`, `request_timestamp`, and `response_status`.
  * **Rate Limiting & Quota:** Limits requests per token (e.g., maximum 60 requests per minute). If a client agent exceeds the quota, the system returns a `429 Too Many Requests`.
  * **Volume Logs:** Logs aggregated requests per hour to calculate load metrics and identify potential DDoS or abusive scrapers.

### Feature 9: Simulated Client Agents (Stress Test Engine)
* **Concept:** A background simulator (The Agent Engine) simulates realistic customer behaviors:
  * **Happy-Path Customers:** Rent a GPU, run workload ticks, terminate lease, pay invoice successfully.
  * **Delinquent Customers:** Simulate credit card declines or credit depletion on RTX/L4, checking if the orchestrator suspends the lease and terminates the simulated GPU.
  * **Upgrade Seekers:** Initiate lease on L4, request mid-lease upgrade to H100 after 2 minutes (simulated 4 hours), verifying upgrade fees and dynamic rate recalculations.
  * **Abusive Clients:** Spin up multiple shared leases on RTX/L4, bombarding the API to trigger `429 Too Many Requests` rate limiting.

---

## 4. Technical Stack & Dependencies

- **Runtime:** Python >= 3.13 (and fully compatible with Python 3.14)
- **Framework:** Django 6.1 (with DRF or Django Ninja)
- **Quality Watchdog:** `django-guardian` (pre-installed as a startup check)
- **AI Tooling:** `django-ai-boost` and `codebase-memory-mcp` (active in session)

---

## 5. Bootstrap Checklist for the Next Agent / Developer

When starting the implementation:

1. **Setup Environment:**
   * Create a new Django project in `/home/maiquel/gpurent`.
   * Install `django-guardian` and add `"django_guardian"` to `INSTALLED_APPS`.
2. **First Run (`guardian_audit`):**
   * Run `python manage.py check` to verify that `django-guardian` checks pass and recommend packages.
   * Run `python manage.py guardian_audit` to see the initial architectural compliance score.
3. **Database Seed (NVIDIA Catalog):**
   * Write a migration or seed command to populate `GPUModel` with H100, A100, L4, and RTX 4090 specs and pricing.
4. **Local Mock Spin Up:**
   * Run the `stripe-mock` docker container or start the Mockoon mock server locally.
5. **Implement the Orchestrators & Agents:**
   * Create `gpurent/orchestrators/lease_flow.py` for lease transitions and concurrency audits.
   * Create `gpurent/orchestrators/upgrade_flow.py` to handle mid-lease GPU swaps and dynamic fees.
   * Implement the Time-Scaled simulator logic to rapidly test credit depletion and post-paid invoices.
   * Add the API Token Rate-Limiting middleware or decorator to capture token usage and reject overloaded requests.
6. **Verify and Audit:**
   * Keep running `python manage.py guardian_audit` during development to ensure zero architectural degradation.
