# 📋 [x] Implementation Tasks: US08 (Developer API Token & Rate-Limiting Audit)

This document contains the physical, actionable development tasks required to complete User Story 08.

---

## 🛠️ [x] Task 8.1: Token Usage Schema (`users/models.py`)
* **Description:** Implement the schema recording developer request metadata.
* **Steps:**
  - [x] 1. Define model `TokenUsage` in `users/models.py` with fields:
     - `id`: UUID (Primary Key)
     - `api_token`: CharField (with database index)
     - `endpoint`: CharField
     - `request_timestamp`: DateTimeField (with database index)
     - `response_status`: PositiveIntegerField
* **Verification:** Apply database migrations and verify schema.

---

## 🛠️ [x] Task 8.2: Rate Limiting Middleware (`users/middleware.py`)
* **Description:** Capture API request headers and enforce request limits.
* **Steps:**
  - [x] 1. Create module `users/middleware.py`.
  - [x] 2. Register middleware class `APITokenRateLimitMiddleware` inside `gpurent/settings.py`.
  - [x] 3. Inspect incoming requests for header `X-API-Token`. If missing, proceed normally or require auth based on routes.
* **Verification:** Confirm API requests containing the header register in terminal execution logs.

---

## 🛠️ [x] Task 8.3: Request Quota Evaluation
* **Description:** Block request processing when quota limit (60 requests/minute) is breached.
* **Steps:**
  - [x] 1. Count requests in `TokenUsage` for the active token within the last 60 seconds.
  - [x] 2. If count >= 60:
     - Create a log entry with response status `429`.
     - Immediately reject the request, returning an HTTP `429 Too Many Requests` response.
  - [x] 3. If count < 60:
     - Process request, save final response status to `TokenUsage`.
* **Verification:** Test flood request behavior with automated script to verify the rate-limiting trigger.

---

## 🛠️ [x] Task 8.4: Rate Limiting Unit Testing
* **Description:** Verify robust and secure rate limiting behaviors.
* **Steps:**
  - [x] 1. Create `users/tests/test_rate_limiter.py`.
  - [x] 2. Write test making 60 successful requests followed by a 61st, asserting that the 61st request returns HTTP status `429`.
  - [x] 3. Assert metadata is correctly indexed and logged to database.
* **Verification:** Run `uv run  manage.py test users.tests.test_rate_limiter`.
