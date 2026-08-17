# ADR 0001: Containerized Background Worker Simulation

* **Status:** Approved
* **Date:** 2026-08-16
* **Decided By:** Gemini CLI & Developer

---

## Context

The GPURent platform requires a continuous background simulation (Conceptual Workers) to generate synthetic metrics (VRAM, compute load, temperature) and evaluate pre-paid credit balances at 5-second intervals. 

Running this intensive simulation loop inside the same OS process as the Django web server (e.g., inside Gunicorn or UWSGI worker threads) introduces major architectural risks:
1. **Thread Starvation:** Simulating dozens of active GPUs can block or slow down incoming synchronous HTTP requests.
2. **Process Recycle Instability:** Web server managers (like Gunicorn) periodically recycle worker processes, which would abruptly terminate active simulation timers, leading to irregular metric tick sequences and inaccurate billing.
3. **Scaling Bottlenecks:** Web request spikes and simulation processing loads cannot be scaled independently.

---

## Decision

We will isolate the background metrics simulation and agent execution engine into a **distinct, standalone process** running in its own container. 

Both the Web API and the simulation worker will share the **same code repository and database**, but they will execute separately:

1. **The Web API Service (`web`):**
   - **Process:** Managed by a standard WSGI/ASGI server (e.g., Gunicorn/Uvicorn).
   - **Task:** Handles HTTP endpoints, input validation via Serializers, and database mutations.
2. **The Simulation Service (`worker`):**
   - **Process:** Executed as a custom, persistent Django management command (`python manage.py run_simulation`).
   - **Task:** Continually queries active leases, generates metrics, updates balances, and triggers alerts in a dedicated non-blocking thread loop.

Both services will be declared and managed as isolated containers using **Docker Compose**.

---

## Consequences

### Positive (Benefits)
* **API Resilience:** Peak workloads or thermal exceptions within the simulation loops have zero impact on the responsiveness of the HTTP API endpoints.
* **Process Stability:** The simulation worker runs as a long-lived, dedicated CLI process, eliminating interruptions from web worker recycles.
* **Granular Scalability:** Infrastructure administrators can scale the Web API horizontally (e.g., spawning more web container replicas) without duplicating background ticker processes.
* **Shared ORM Capability:** Since both containers execute the same Django codebase, the worker reads and writes directly to the shared database schema without requiring complex data synchronization REST APIs.

### Negative (Trade-offs)
* **Environment Overhead:** Running multiple services requires maintaining a `docker-compose.yml` config and slightly increases local RAM/CPU footprints.
* **Database Concurrency:** Multiple containers writing to the same database tables (`MetricSnapshot`, `UserCredit`) requires strict transactions and database-level row locking (`select_for_update()`) to prevent race conditions during billing calculations.
