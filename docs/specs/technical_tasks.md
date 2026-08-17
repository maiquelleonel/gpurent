# 🛠️ Technical Task Specifications & Implementation Plan: GPURent (DDD Architecture)

This document specifies the DDD-aligned, Django App-segmented technical execution plan, folder structure, and database schemas required to implement GPURent. It enforces the rules defined in `GEMINI.md` (McCabe complexity < 10, timezone awareness, thin views/fat models, strict timeouts, and 100% test coverage).

---

## 🏗️ 1. Domain-Driven Design (DDD) Bounded Contexts

To respect DDD and segment responsibilities cleanly, we separate the platform into three distinct Django applications (Bounded Contexts) surrounding the central `gpurent` configuration project:

1. **`users` App (Account & API Authentication Domain):**
   - Manages developer authentication, API access tokens, and API audit logs.
   - Enforces API rate limits and developer quotas.
2. **`billing` App (Financial, Pricing, & Payment Domain):**
   - Coordinates dynamic pricing (volume discounts, upgrade fees).
   - Manages pre-paid credit balances, ledgers, and post-paid invoices.
   - Houses the external payment mock service client (`services/billing.py`).
3. **`leases` App (GPU Inventory & Rental Orchestration Domain):**
   - Manages the real-world NVIDIA catalog (`GPUModel`, `GPUInstance`).
   - Orchestrates the lease lifecycle state machine (`RentalLease`).
   - Runs the background metrics simulations (`MetricSnapshot`) and stress agents.

```
~/gpurent/
├───gpurent/                     # Configuration Root (Settings, Core Routing)
│   ├───settings.py
│   ├───urls.py
│   ├───wsgi.py
│   ├───asgi.py
│   └───__init__.py
│
├───users/                       # Bounded Context: Account & API Token Domain
│   ├───models.py                # TokenUsage
│   ├───middleware.py            # API Token Rate Limiting Middleware
│   ├───tests/
│   └───...
│
├───billing/                     # Bounded Context: Financial & Payments Domain
│   ├───models.py                # UserCredit, Invoice
│   ├───services/                # Stripe Mock payment clients
│   │   ├───__init__.py
│   │   └───payment_gateway.py
│   ├───orchestrators/           # Billing state processors
│   │   ├───__init__.py
│   │   └───ledger.py
│   ├───tests/
│   └───...
│
└───leases/                      # Bounded Context: GPU Inventory & Rental Domain
    ├───models.py                # GPUModel, GPUInstance, RentalLease, MetricSnapshot
    ├───orchestrators/           # Lease state machine, mid-lease upgrades
    │   ├───__init__.py
    │   ├───lease_flow.py
    │   └───upgrade_flow.py
    ├───simulation/              # Worker threads & simulation loops
    │   ├───__init__.py
    │   ├───worker.py
    │   └───agent_engine.py
    ├───utils/                   # Time-scale scaling factors
    │   ├───__init__.py
    │   └───time_scale.py
    ├───tests/
    └───...
```

---

## 🗄️ 2. Domain Data Models & Relationships

### A. `users` Domain Models
#### `TokenUsage`
* `id`: UUID (Primary Key)
* `api_token`: CharField(max_length=255, db_index=True)
* `endpoint`: CharField(max_length=255)
* `request_timestamp`: DateTimeField(db_index=True)
* `response_status`: PositiveIntegerField

### B. `billing` Domain Models
#### `UserCredit`
* `id`: UUID (Primary Key)
* `user`: OneToOneField(User, on_delete=CASCADE, related_name="credit")
* `balance`: DecimalField(max_digits=10, decimal_places=2, default=0.00)
* `updated_at`: DateTimeField

#### `Invoice`
* `id`: UUID (Primary Key)
* `user`: ForeignKey(User, on_delete=CASCADE, related_name="invoices")
* `lease_id`: UUIDField(db_index=True, null=True)  # Loosely coupled ID to leases domain
* `amount`: DecimalField(max_digits=10, decimal_places=2)
* `status`: CharField(choices: UNPAID, PAID, FAILED)
* `description`: CharField(max_length=255)
* `created_at`: DateTimeField

### C. `leases` Domain Models
#### `GPUModel`
* `id`: UUID (Primary Key)
* `name`: CharField(unique=True) (e.g., "NVIDIA H100 (80GB SXM5)")
* `vram_capacity_gb`: PositiveIntegerField (e.g., 80)
* `price_per_hour`: DecimalField(max_digits=6, decimal_places=2)

#### `GPUInstance`
* `id`: UUID (Primary Key)
* `serial_number`: CharField(unique=True)
* `model`: ForeignKey(GPUModel, on_delete=PROTECT, related_name="instances")
* `status`: CharField (choices: AVAILABLE, LEASED, MAINTENANCE)
* `is_dedicated`: BooleanField(default=False)

#### `RentalLease`
* `id`: UUID (Primary Key)
* `user`: ForeignKey(User, on_delete=CASCADE, related_name="leases")
* `gpu_instance`: ForeignKey(GPUInstance, on_delete=PROTECT, related_name="leases", null=True)
* `status`: CharField (choices: PROVISIONING, ACTIVE, TERMINATING, COMPLETED, SUSPENDED_PAYMENT)
* `started_at`: DateTimeField
* `ended_at`: DateTimeField(null=True, blank=True)
* `total_billed_amount`: DecimalField(max_digits=10, decimal_places=2, default=0.00)
* `volume_discount_applied`: DecimalField(max_digits=4, decimal_places=2, default=0.00)

#### `MetricSnapshot`
* `id`: UUID (Primary Key)
* `gpu_instance`: ForeignKey(GPUInstance, on_delete=CASCADE, related_name="snapshots")
* `vram_used_gb`: DecimalField(max_digits=5, decimal_places=2)
* `compute_load_pct`: DecimalField(max_digits=5, decimal_places=2)
* `temperature_c`: DecimalField(max_digits=5, decimal_places=2)
* `is_thermal_alert`: BooleanField(default=False)
* `timestamp`: DateTimeField

---

## 🏃‍♂️ 3. Physical Implementation Plan (Phase-by-Phase)

### Phase 1: Environment Setup & DDD Project Scaffolding
1. Create a Django project structure in `~/gpurent`.
2. Generate three Django applications inside the root folder: `users`, `billing`, and `leases`.
3. Configure `gpurent/settings.py` to register `"django_guardian"` and our custom apps: `"users"`, `"billing"`, and `"leases"` in `INSTALLED_APPS`.
4. Apply standard database migrations.
5. Implement `seed_catalog` management command within the `leases` app to populate the catalog with the exact NVIDIA rates and models, creating sample available physical instances.

### Phase 2: Domain Logic Isolation & Interface Bridges
To maintain DDD integrity, communications between Bounded Contexts are isolated:
1. **Billing Interface Bridge:** The `billing` app exposes pricing, balance checks, and invoice processing.
2. **Lease Lifecycle Actions:** The `leases` app queries the `billing` interface before transitioning to `ACTIVE` (checking if pre-paid clients have credit or dedicated instances have upfront validation).
3. **Credit Decrement Rules:** The background metric simulation worker in the `leases` app triggers billing balance checks and decrements via the `billing` ledger service on every simulation tick.

### Phase 3: Background Worker & Time-Scaled Math (`leases/simulation/worker.py`)
1. Implement background thread-pool that queries active leases periodically (every 5 seconds).
2. Generate random, realistic telemetry parameters based on `GPUModel` limits, storing them in `MetricSnapshot`.
3. Implement `TIME_SCALE_FACTOR` inside settings. Multiply actual elapsed time by the factor to calculate accelerated billing usage rates.
4. If a pre-paid user's credits hit $0 during a billing deduction, the background worker communicates with the `leases` orchestrator to shut down the instance and mark the lease as `SUSPENDED_PAYMENT`.

### Phase 4: Financial Transactions & Mock Payment (`billing/services/payment_gateway.py`)
1. Define the Stripe payment service client in `billing/services/payment_gateway.py`.
2. Enforce strict HTTP connection and read timeouts of 5.0 seconds.
3. Configure URLs to use the local containerized gateway (`http://localhost:12111`) or fallback safe mock routines.

### Phase 5: Lease Orchestrator (`leases/orchestrators/lease_flow.py`)
1. Implement state-machine actions (`start_lease`, `terminate_lease`) in `leases`.
2. Apply the Volume Discount Rule:
   - Identify active concurrent leases for the same model type. If count > 5, apply a 10% discount to calculated hourly rates across those models.
3. Enforce instance-sharing and isolation logic:
   - Dedicated instances strictly map 1 lease per card.
   - Shared instances allow up to 4 concurrent client simulation threads.

### Phase 6: Mid-Lease Upgrades (`leases/orchestrators/upgrade_flow.py`)
1. Create `upgrade_lease_tier(lease, target_model)` inside an atomic transaction block:
   - Terminate old instance simulation metrics loop.
   - Settle outstanding accrued charges on the previous model up to the exact millisecond of termination.
   - Assess dynamic flat fees: $15.00 for tier swaps (L4 ➔ H100) or $5.00 for VRAM scaling (A100 40GB ➔ A100 80GB).
   - Claim and assign the new physical instance, initiating the new simulation worker.

### Phase 7: Middleware Rate-Limiting (`users/middleware.py`)
1. Parse `X-API-Token` header.
2. Log entry to `TokenUsage`.
3. Check frequency (limit 60 requests/min).
4. Return `429 Too Many Requests` on exceeding quota.

### Phase 8: Multi-Agent Stress Simulator (`leases/simulation/agent_engine.py`)
1. Build independent test agents mimicking real customer personas:
   - **HappyPathAgent:** Starts lease, runs standard ticks, completes lease, verifies payment.
   - **DelinquentAgent:** Initiates lease with minimal credits ($1.00), validates auto-suspension upon credit depletion.
   - **UpgradeSeekerAgent:** Upgrades mid-lease and verifies correct dynamic rate calculation and flat fee application.
   - **AbusiveAgent:** Floods endpoints to verify rate-limiter returns HTTP 429.

### Phase 9: Verification & Quality Audit
1. Implement a complete suite of unit tests for all domain contexts.
2. Target 100% code coverage across billing rules, upgrade orchestrators, state transitions, and middleware.
3. Audit the final implementation using `django-guardian`'s system checks.
