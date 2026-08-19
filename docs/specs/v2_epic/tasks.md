# 📋 Phase 2 (V2 Epic) Implementation Tasks

This document contains the physical, actionable development tasks required to complete the GPURent Phase 2 Epic (US10 - US15).

---

## 🛠️ [x] Task 10: Tenant Profile & Soft-Delete (`users/models.py`)
* **Description:** Implement OCP-compliant `TenantProfile` and soft-delete business constraints.
* **Steps:**
  - [x] 1. Define model `TenantProfile` in `users/models.py` with:
     - `id`: UUID (Primary Key)
     - `user`: OneToOneField to standard `User` model, `related_name="profile"`
     - `freezed_at`: DateTimeField (null=True, blank=True)
     - `deleted_at`: DateTimeField (null=True, blank=True, represents soft-delete)
  - [x] 2. Implement signal receiver `create_tenant_profile` that automatically spawns a `TenantProfile` whenever a new `User` is created.
  - [x] 3. Write a validation method on `TenantProfile` (e.g. `can_delete()`) that returns `False` if the tenant has outstanding unpaid invoices (`Invoice.objects.filter(user=user, status=InvoiceStatus.UNPAID)`) or if their `UserCredit.balance` is negative.
  - [x] 4. Write an orchestration function `soft_delete_tenant(user_id)` which:
     - Fetches and locks the tenant's profile row (`select_for_update()`).
     - Invokes `can_delete()`. Raises `ValueError` if ineligible.
     - Releases all active GPU leases of the user back to inventory.
     - Sets `deleted_at = timezone.now()`, and disables core login (`user.is_active = False`).
* **Verification:** Write unit tests making sure soft-delete is blocked by unpaid debts and terminates active leases upon successful trigger.

---

## 🛠️ [x] Task 11: Account Freezing Lifecycle
* **Description:** Implement freezing business rules, 10% preservation fees, and the 30-day expiry loop.
* **Steps:**
  - [x] 1. Write function `freeze_tenant_account(user_id, keep_dedicated_gpus: bool)`:
     - Set `freezed_at = timezone.now()`.
     - For **Shared GPUs** (`is_dedicated=False`): Settle accrued usage and terminate all leases immediately, releasing physical slots.
     - For **Dedicated GPUs** (`is_dedicated=True`):
       - If `keep_dedicated_gpus` is `True`: Keep the physical instance's status as `LEASED` (retained exclusively).
       - If `keep_dedicated_gpus` is `False`: Settle accrued usage, terminate leases, and release instances to `AVAILABLE`.
  - [x] 2. Write function `unfreeze_tenant_account(user_id)`:
     - Fetch the user's `TenantProfile` and calculate duration elapsed since `freezed_at`.
     - If they opted to retain dedicated GPUs, calculate the preservation fee: **10% of the standard hourly rate per week (scaled)** for the period they were frozen.
     - Generate a pre-paid `Invoice` for this fee. Deduct the fee from `UserCredit` (or require upfront billing before unlocking).
     - Set `freezed_at = None`, restoring API access.
  - [x] 3. Modify API Middleware to intercept requests from users where `profile.freezed_at` or `profile.deleted_at` is populated. Return an HTTP `403 Forbidden` response with a clear message: `"Account is frozen. Please reactivate to proceed."`
* **Verification:** Write unit tests asserting that frozen accounts are blocked from accessing APIs and that the 10% dedicated GPU holding fee is calculated and billed correctly on re-activation.

---

## 🛠️ [x] Task 12: Mailpit & Async Queue (`steady_queue` Integration)
* **Description:** Integrate Mailpit and the PostgreSQL-backed task queue `steady_queue` for async jobs.
* **Steps:**
  - [x] 1. Add **`Mailpit`** service to `docker-compose.yml` (SMTP port `1025`, Web port `8025`).
  - [x] 2. Install and configure **`steady_queue`** (or clean PG-backed queue) and configure Django `EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"`.
  - [x] 3. Add a new container service `queue-worker` in `docker-compose.yml` that boots the persistent queue consumer daemon using the exact command: `uv run manage.py steady_queue`, sharing the Postgres database and env variables.
  - [x] 4. Write asynchronous task handlers for:
     - [x] `send_welcome_email(user_id)` (fired on user signup).
     - [x] `send_invoice_email(invoice_id)` (fired on billing invoice events).
     - [x] `send_freezing_alert_email(user_id)` (fired on account freeze).
     - [x] `schedule_freeze_expiry_check(user_id)` (scheduled 30 days into the future: checks if `freezed_at` is still set; if so, performs soft-deletion and emails confirmation).
* **Verification:** Verify Mailpit container receives SMTP traffic and check that queue triggers tasks asynchronously on database state mutations.

---

## 🛠️ [x] Task 13: DRF REST API Layer
* **Description:** Build complete serializing, viewing, and routing APIs using Django REST Framework.
* **Steps:**
  - [x] 1. Install `djangorestframework` and add `"rest_framework"` to `INSTALLED_APPS` in `gpurent/settings.py`.
  - [x] 2. Implement Serializers and ViewSets inside the apps:
     - [x] `TenantViewSet`: Endpoints for signup/register, freeze/unfreeze account, and account soft-deletion.
     - [x] `LeaseViewSet`: Endpoints for listing catalog, renting shared/dedicated GPUs, and upgrading mid-lease.
     - [x] `BillingViewSet`: Endpoints for checking prepaid balances, recharging, and listing invoices.
  - [x] 3. Expose REST paths in `gpurent/urls.py` under the `/api/v1/` prefix.
  - [x] 4. Wire our custom token security checking (`X-API-Token`) and rate-limiting to DRF view actions.
* **Verification:** Perform mock requests against ViewSets verifying correct status codes and responses.

---

## 🛠️ [x] Task 14: Live Admin HTMX Toasts
* **Description:** Build a real-time Stackable Toast Notification bar in the Django Admin using HTMX.
* **Steps:**
  - [x] 1. Define model `SystemAlert` in `leases/models.py` with `message` (TextField), `alert_type` (CharField: signup, billing, delete), and `is_read` (BooleanField, default=False).
  - [x] 2. Override the standard Django Admin base template (`admin/base_site.html`) to inject:
     - [x] HTMX script (`<script src="https://unpkg.com/htmx.org@1.9.10"></script>`).
     - [x] A fixed, floating bottom-right container (`<div id="htmx-toast-container" style="position:fixed; bottom:20px; right:20px; z-index:9999;"></div>`).
     - [x] An HTMX polling request tag on the container: `hx-get="/admin/api/live-alerts/" hx-trigger="every 5s" hx-swap="beforeend"`.
  - [x] 3. Create view `admin_live_alerts_endpoint` returning HTML fragments representing new `SystemAlert` records formatted as stackable Bootstrap toasts.
  - [x] 4. Set alerts to automatically fade out and remove themselves after 4 seconds using a simple CSS/JS fade-out transition.
* **Verification:** Open Django Admin in a browser, trigger a billing or user signup event, and confirm the corresponding toast pops up dynamically in the corner without page reload.

---

## 🛠️ [x] Task 15: Stripe Webhook Integration & Async Reconciliation
* **Description:** Handle payment gateway events asynchronously and verify web signatures securely.
* **Steps:**
  - [x] 1. Create view endpoint `stripe_webhook_endpoint` at `/api/billing/webhooks/stripe/`.
  - [x] 2. Read incoming payloads and verify the `Stripe-Signature` header against the mock signing key.
  - [x] 3. Map event payloads:
     - [x] `charge.refunded`: Parse invoice ID, mark `Invoice` as `REFUNDED` inside the DB, and refund prepaid balances.
     - [x] `invoice.payment_failed`: Parse tenant ID, immediately trigger `SUSPENDED_PAYMENT` on all active leases, and release occupied physical cards back to `AVAILABLE`.
  - [x] 4. Offload event parsing asynchronously to `steady_queue` to keep webhook response times under 100ms.
* **Verification:** Simulate webhook payloads and verify database state and lease suspension triggers execute perfectly in background logs.
