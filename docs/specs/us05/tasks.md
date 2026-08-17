# 📋 [x] Implementation Tasks: US05 (Local Payment Mock Integration)

This document contains the physical, actionable development tasks required to complete User Story 05.

---

## 🛠️ [x] Task 5.1: Payment Gateway Service Client (`billing/services/payment_gateway.py`)
* **Description:** Implement the HTTP client interfacing with the offline local mock gateway.
* **Steps:**
  - [x] 1. Create folder structure `billing/services/` if it does not exist.
  - [x] 2. Implement `payment_gateway.py` utilizing the modern `httpx` library (modern, fast, and fully async-compatible as per architectural feedback).
  - [x] 3. Define connection endpoints pointing to the local containerized Mock gateway (`http://localhost:12111` or Mockoon at `http://localhost:8081`).
* **Verification:** Ensure that calling the service loads correct server address configurations.

---

## 🛠️ [x] Task 5.2: Strict HTTP Timeout Controls
* **Description:** Protect thread execution pools by applying timeout configurations to satisfy `guardian.W006`.
* **Steps:**
  - [x] 1. For every HTTP invocation, apply a strict timeout: `timeout=5.0`.
  - [x] 2. Catch `httpx.TimeoutException` and `httpx.RequestError` specifically.
  - [x] 3. Raise clear custom billing exceptions rather than allowing raw connection exceptions to bubble up.
* **Verification:** Ensure there are no un-timeouted HTTP library requests in the `billing` app.

---

## 🛠️ [x] Task 5.3: Gateway Transaction Scenarios
* **Description:** Implement specific integration logic for successful processing and declines.
* **Steps:**
  - [x] 1. Implement `process_payment(user_id, amount, card_token)`:
     - Post transaction details to Stripe/Mockoon mock.
     - Return transaction status (`PAID` or `FAILED`).
  - [x] 2. Implement `process_refund(invoice_id)`:
     - Call mock refund endpoint and return verification.
* **Verification:** Verify response payloads parse correctly and handle failed card responses.

---

## 🛠️ [x] Task 5.4: Payment Gateway Unit Testing
* **Description:** Test client network interactions and timeout defenses.
* **Steps:**
  - [x] 1. Create test cases for payment gateway inside `billing/tests.py`.
  - [x] 2. Mock the outgoing HTTP calls using `unittest.mock.patch` to simulate connection timeouts and API failures.
  - [x] 3. Verify that the client handles connection drops gracefully and records local failures.
* **Verification:** Run `just test` to verify all test cases pass successfully.
