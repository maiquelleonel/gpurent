# ⚡ GPURent — Django-Warden Exemplary Reference Architecture

> "This repo is a django-warden example powered by a good PRD, deriving ADRs, specs, and tasks. Just copy the PRD and try it!" 🚀

Welcome to **GPURent**, a high-performance conceptual platform for renting cloud GPU instances. This repository serves as the **gold-standard exemplary reference project** for utilizing [**django-warden**](https://github.com/hernandis/django-warden) to design, build, audit, and deliver production-grade Django and Django REST Framework (DRF) applications.

The entire project's design and implementation are derived programmatically from a structured business and technical methodology:
```text
  [Product Requirements (PRD)] 
             │
             ▼
  [Architectural Decision Records (ADRs)] 
             │
             ▼
  [Technical Specifications (Specs)] 
             │
             ▼
  [Actionable Task Boards (Tasks)] ➔ [100% Verified Implementation]
```

---

## 🛠️ Tech Stack & Key Architectural Highlights

This repository showcases the absolute state-of-the-art Python and Django 6.0+ ecosystem:

* **DDD Bounded Contexts:** Modular folder architecture cleanly decoupling Business Domains: Users & Account Lifecycles (`users`), Financials & Webhooks (`billing`), and Inventory, Telemetry, & Upgrades (`leases`).
* **PostgreSQL-backed Async Queues (`steady_queue`):** High-priority async workers pool (billing, emails, account_lifecycle) utilizing PostgreSQL transactional concurrency, completely bypassing Redis/Celery.
* **Official DRF Cryptographic Token Auth (`rest_framework.authtoken`):** Enterprise-grade security with an intelligent "dual-mode" authentication backend supporting mock fallback (`dev_token_<username>`) for local environments.
* **Time-Scaled Acceleration Ticker:** A background worker running accelerated time simulation (default: `TIME_SCALE_FACTOR = 120`), making 1 physical minute equal to 2 simulated hours for instant billing and credit-depletion testing.
* **Dedicated GPU Isolation & Shared Concurrency (Max 4):** A custom inventory allocator limiting shared GPUs to exactly 4 concurrent active leases, and dedicated GPUs to strict single-tenant lease isolation.
* **API Shielding Middleware:** Intercepts and rejects requests with HTTP `403 Forbidden` if the user's account is currently frozen or soft-deleted.
* **Stripe Webhook Integration:** Verified Stripe-Signature endpoints offloading charge refunds and failed payment suspensions asynchronously to the queue.
* **Live Admin HTMX Toasts:** Overridden base admin templates using **HTMX Polling** to push stackable, self-fading Bootstrap toast notifications (signups, billing, deleted accounts) in the bottom right corner in real-time.
* **Mailpit SMTP Mail Capture:** Deployable local capture engine showcasing beautiful transactional email templates (welcomes, faturas, freeze notices, and account closures).

---

## 📦 The Golden Architectural Chain

Explore the documents that drove the implementation of this codebase:

1. **`GPU_RENTAL_PRD.md`**: The absolute single source of truth for product and business requirements.
2. **`docs/adrs/`**: Architectural Decision Records documenting core design decisions (e.g. Postgres DB migrations, containerized worker simulators, and task queues).
3. **`docs/specs/`**: Actionable development plans, technical task lists, and verification conditions separated by user story (US01 to US15).

---

## 🚀 Getting Started & Local Development

### Prerequisites
Make sure you have [**uv**](https://github.com/astral-sh/uv) and **Docker** installed on your machine.

### 1. Fast Local Unit Testing (SQLite in Memory - Blazing Fast TDD)
We have configured a completely silent, warning-free, and colorful test suite utilizing **pytest-django**. It uses a fallback SQLite in-memory database and an `ImmediateBackend` for tasks so that tests run in milliseconds:

```bash
# Run all 43 test cases (completely silent, with green dots and colored outputs)
just test

# Fail-fast testing (stops on the first error)
just test -x
```

### 2. Local Development Workflow (Hybrid: Docker Companion Containers + Local Dev)

Para uma experiência fluida de desenvolvimento com hot-reload, fila assíncrona ativa e visualização de emails em tempo real:

#### Passo 1: Subir os Containers de Apoio (PostgreSQL, Mailpit e Stripe Mock)
```bash
# Sobe banco de dados, Mailpit SMTP e Stripe Mock em background
docker compose up -d db stripe-mock mailpit
```

#### Passo 2: Preparar Banco de Dados e Catálogo de GPUs
```bash
# Aplica migrations e popula o catálogo de GPUs (15 instâncias)
just migrate
just seed
```

#### Passo 3: Iniciar o Servidor Web e o Worker de Filas (`steady_queue`)
O comando `just dev` utiliza o **Honcho** para rodar simultaneamente o servidor web Django (`runserver`) e o consumidor da fila de tarefas assíncronas (`steady_queue`):
```bash
just dev
```

#### Passo 4: Em outro terminal, Iniciar o Motor de Simulação com Agentes
```bash
# Executa os agentes automatizados (HappyPath, Delinquent, Upgrade, etc.) e mantém a simulação contínua
just run_simulation
```

### 3. Docker Compose (Cluster 100% Containerizado)
Se preferir rodar toda a stack dentro de containers Docker:
```bash
docker compose up --build -d
docker compose logs -f
```

### 🌐 Painéis e Portas Locais:
* **Django Admin & Live Dashboard:** [`http://localhost:8000/admin/`](http://localhost:8000/admin/) *(Dashboard HTMX em tempo real com suporte a Dark Mode!)*
* **Mailpit Web Mailbox:** [`http://localhost:8025`](http://localhost:8025) *(Inspecione todos os emails transacionais gerados pelo pipeline!)*
* **Django REST API:** `http://localhost:8000/api/`
* **Stripe Webhook Mock Gateway:** `http://localhost:12111`
* **PostgreSQL Database:** `localhost:54322` (ou porta interna `5432`)

---

## 🤖 The Programmatic Client Agent Stress Engine

The system includes a brilliant programmatic stress simulator at `leases/simulation/agent_engine.py` representing four customer behaviors that run against the API:
1. **HappyPathAgent:** Starts a shared RTX 4090 lease, ticks billing, generates faturas, and gracefully terminates the contract.
2. **DelinquentAgent:** Spawns a prepaid lease with $1.00 credit, lets the ticker deplete it, and verifies that the system automatically suspends the lease and frees up the physical GPU.
3. **UpgradeSeekerAgent:** Starts an L4 lease, triggers a mid-lease Tier Swap upgrade to H100 dedicated, and validates pro-rated weekly reservation fees.
4. **AbusiveAgent:** Floods request endpoints with api tokens to trigger the APITokenRateLimitMiddleware and verify the HTTP `429 Too Many Requests` quota block.

To run this agentic stress test against your live running container server on demand, run:
```bash
docker compose exec web uv run manage.py run_simulation --run-agents
```
And check the live logs dynamically reacting inside the terminal!

---

## 🛡️ Auditing & Compliance with Django-Warden

To ensure that the codebase respects all idiomatic django guidelines, zero N+1 query patterns, and low cyclomatic complexities, run the warden linter:

```bash
just guardian_audit
```
Keep your editor clean, your test suites green, and have fun building the cloud GPU platform of tomorrow! 💻⚡
