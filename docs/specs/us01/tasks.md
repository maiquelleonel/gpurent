# 📋 [x] Implementation Tasks: US01 (GPU Inventory & NVIDIA Catalog)

This document contains the physical, actionable development tasks required to complete User Story 01.

---

## 🛠️ [x] Task 1.1: Django Project & Apps Scaffolding
* **Description:** Initialize the Django 6.1 project structure and the `leases` domain app.
* **Steps:**
  - [x] 1. Initialize standard Django project named `gpurent` inside `~/gpurent`.
  - [x] 2. Create a custom folder configuration structure to rename/keep settings clean.
  - [x] 3. Create the `leases` app via `manage.py startapp leases`.
  - [x] 4. Register `django_guardian` and `leases` in `INSTALLED_APPS` inside settings.
  - [x] 5. Register `users` and `billing` apps in `INSTALLED_APPS`.
  - [x] 6. Create folder structure: `billing/services/`, `billing/orchestrators/`, `leases/orchestrators/`, `leases/simulation/`, `leases/utils/`, `leases/management/commands/`.
  - [x] 7. Configure `.gemini/settings.json` with MCP `django-ai-boost`.
  - [x] 8. Add `TIME_SCALE_FACTOR = 120` to settings.
* **Verification:** Run `uv run  manage.py check` to ensure imports and system checks pass successfully.

---

## 🛠️ [x] Task 1.2: Schema Implementation (`leases/models.py`)
* **Description:** Implement the database models representing the NVIDIA inventory.
* **Steps:**
  - [x] 1. Define model `GPUModel` with `name` (unique CharField), `vram_capacity_gb` (PositiveIntegerField), and `price_per_hour` (DecimalField).
  - [x] 2. Define model `GPUInstance` with `serial_number` (unique CharField), `model` (ForeignKey to GPUModel), `status` (choices: AVAILABLE, LEASED, MAINTENANCE), and `is_dedicated` (BooleanField).
  - [x] 3. Define model `RentalLease` with `user` (ForeignKey to Django User), `gpu_instance` (ForeignKey to GPUInstance, null=True), `status` (choices: PROVISIONING, ACTIVE, TERMINATING, COMPLETED, SUSPENDED_PAYMENT), `started_at` (DateTimeField), `ended_at` (DateTimeField, null=True), and `total_billed_amount` (DecimalField).
  - [x] 4. Ensure all models use UUIDs as primary keys.
  - [x] 5. Add `MetricSnapshot` model with VRAM, compute, temperature, thermal alert flag, and timestamp.
  - [x] 6. Use TextChoices for status enums (`GPUInstanceStatus`, `RentalLeaseStatus`).
  - [x] 7. Add database indexes for common query patterns.
  - [x] 8. Register all models in Django Admin (`admin.py` for leases, billing, and users apps) with proper filters, search fields, and optimized `select_related` on querysets to prevent N+1 performance issues.
* **Verification:** Run `uv run  manage.py check` to confirm admin registrations and models compile without error.

---

## 🛠️ [x] Task 1.3: Seeding Management Command (`leases/management/commands/seed_catalog.py`)
* **Description:** Build a management command to seed catalog models and test instances.
* **Steps:**
  - [x] 1. Create a custom Django management command file at `leases/management/commands/seed_catalog.py`.
  - [x] 2. Write logic to populate `GPUModel` with exact PRD parameters (H100, A100 80GB, A100 40GB, L4, RTX 4090).
  - [x] 3. Pre-create at least 3 physical `GPUInstance` records per model for testing.
* **Verification:** Run `uv run  manage.py seed_catalog` and query database to confirm records exist.

---

## 🛠️ [x] Task 1.4: Base Catalog Unit Testing
* **Description:** Write initial unit tests verifying database mapping and seeding.
* **Steps:**
  - [x] 1. Create `leases/tests/test_catalog.py`.
  - [x] 2. Assert catalog records are populated correctly with exact rates.
  - [x] 3. Verify that model relation constraints (like `on_delete=PROTECT` on `GPUInstance.model`) prevent orphan database structures.
* **Verification:** Run `uv run  manage.py test leases.tests.test_catalog` and ensure all assertions pass.
