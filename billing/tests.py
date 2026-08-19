from decimal import Decimal
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from billing.models import ClientUsageCycle, Invoice, InvoiceStatus, PlanType, UserCredit
from billing.services.ledger import invoice_lease_usage
from billing.services.payment_gateway import (
    PaymentGatewayException,
    PaymentTimeoutException,
    process_payment,
    process_refund,
)
from leases.models import GPUInstance, GPUInstanceStatus, GPUModel, RentalLease, RentalLeaseStatus
from leases.orchestrators.lease_flow import provision_lease
from leases.simulation.worker import MetricsSimulatorWorker

User = get_user_model()


class BillingAndPaymentTestCase(TestCase):
    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(username="billinguser", password="securepassword")

        # Create GPU Models
        self.rtx_model = GPUModel.objects.create(
            name="NVIDIA RTX 4090 (24GB)",
            vram_capacity_gb=24,
            price_per_hour=Decimal("0.44"),
        )
        self.h100_model = GPUModel.objects.create(
            name="NVIDIA H100 (80GB SXM5)",
            vram_capacity_gb=80,
            price_per_hour=Decimal("4.76"),
        )

        # Create GPU Instances
        self.rtx_instance = GPUInstance.objects.create(
            serial_number="GPU-RTX-4090-TEST",
            model=self.rtx_model,
            status=GPUInstanceStatus.AVAILABLE,
            is_dedicated=False,
        )
        self.h100_instance = GPUInstance.objects.create(
            serial_number="GPU-H100-TEST",
            model=self.h100_model,
            status=GPUInstanceStatus.AVAILABLE,
            is_dedicated=True,
        )

    # ==========================================
    # US04 - TASK 4.1: PRE-PAID DEPLETION TICKER
    # ==========================================
    def test_prepaid_credit_depletion_auto_suspends_lease(self):
        # Top up user pre-paid credit with exactly $1.00
        credit = UserCredit.objects.create(user=self.user, balance=Decimal("1.00"))

        # Provision a shared RTX 4090 lease
        lease = provision_lease(self.user, self.rtx_model.id, is_dedicated=False)
        self.assertEqual(lease.status, RentalLeaseStatus.ACTIVE)

        # Confirm instance remains AVAILABLE (shared instance with < 4 leases)
        self.rtx_instance.refresh_from_db()
        self.assertEqual(self.rtx_instance.status, GPUInstanceStatus.AVAILABLE)

        # Simulate that 3 real minutes have elapsed since start.
        # With TIME_SCALE_FACTOR = 120, 3 real minutes = 6 simulated hours.
        # Cost: 6 hours * $0.44 = $2.64. This exceeds the $1.00 prepaid limit!
        lease.started_at = timezone.now() - timezone.timedelta(minutes=3)
        lease.save(update_fields=["started_at"])

        # Execute simulation tick
        worker = MetricsSimulatorWorker()
        simulated_count = worker.tick()

        # The lease should be processed but suspended during the tick, so simulated count should be 0 (suspended)
        self.assertEqual(simulated_count, 0)

        # Verify lease status transitioned to SUSPENDED_PAYMENT
        lease.refresh_from_db()
        self.assertEqual(lease.status, RentalLeaseStatus.SUSPENDED_PAYMENT)
        self.assertIsNotNone(lease.ended_at)

        # Verify physical instance is released back to AVAILABLE
        self.rtx_instance.refresh_from_db()
        self.assertEqual(self.rtx_instance.status, GPUInstanceStatus.AVAILABLE)

        # Verify prepaid credits are deducted (should have gone negative or exactly matching deduction)
        credit.refresh_from_db()
        # $1.00 - $2.64 = -$1.64
        self.assertEqual(credit.balance, Decimal("-1.64"))

        # Verify ClientUsageCycle recorded the usage and marked cycle as closed
        cycle = ClientUsageCycle.objects.filter(client=self.user).first()
        self.assertIsNotNone(cycle)
        self.assertEqual(cycle.total_consumption, Decimal("2.64"))
        self.assertFalse(cycle.is_active)
        self.assertIsNotNone(cycle.cycle_ended_at)

    # ==========================================
    # US04 - TASK 4.2: VOLUME DISCOUNT ENFORCEMENT
    # ==========================================
    def test_volume_discount_applied_for_six_concurrent_leases(self):
        # Create a pre-paid user with $100.00 credit
        UserCredit.objects.create(user=self.user, balance=Decimal("100.00"))

        # Pre-create 6 additional physical RTX 4090 instances
        instances = []
        for i in range(1, 8):
            inst = GPUInstance.objects.create(
                serial_number=f"GPU-RTX-DISCOUNT-{i}",
                model=self.rtx_model,
                status=GPUInstanceStatus.AVAILABLE,
                is_dedicated=False,
            )
            instances.append(inst)

        # Create exactly 6 concurrent ACTIVE leases for the same model
        leases = []
        started_at = timezone.now() - timezone.timedelta(minutes=1)  # 2 simulated hours
        for i in range(6):
            lease = RentalLease.objects.create(
                user=self.user,
                gpu_instance=instances[i],
                status=RentalLeaseStatus.ACTIVE,
                started_at=started_at,
            )
            leases.append(lease)

        # Execute simulation tick which invoices all of them
        worker = MetricsSimulatorWorker()
        simulated_count = worker.tick()

        # All 6 leases simulated
        self.assertEqual(simulated_count, 6)

        # Verify volume discount was applied to all of them because count > 5 (exactly 6)
        # Base price per hour = $0.44. Discounted by 10% = $0.396.
        # Elapsed time = 2 simulated hours. Cost per lease = 2 * $0.396 = $0.792 -> rounded to $0.79.
        for lease in leases:
            lease.refresh_from_db()
            self.assertEqual(lease.total_billed_amount, Decimal("0.79"))
            self.assertEqual(lease.volume_discount_applied, Decimal("10.00"))

        # Verify client usage cycle accumulated the consumption

        cycle = ClientUsageCycle.objects.filter(client=self.user, is_active=True).first()
        self.assertIsNotNone(cycle)
        self.assertGreater(cycle.total_consumption, Decimal("0.00"))

        # Verify explicit invoicing records the volume discount in description
        lease_to_invoice = leases[0]
        lease_to_invoice.started_at = timezone.now() - timezone.timedelta(minutes=1)
        lease_to_invoice.save()
        invoice_lease_usage(lease_to_invoice)
        invoice = Invoice.objects.filter(lease_id=lease_to_invoice.id).first()
        self.assertIsNotNone(invoice)
        self.assertIn("10% Volume Discount Applied", invoice.description)

    # ==========================================
    # US04 - TASK 4.3: DEDICATED UPFRONT PAYMENT
    # ==========================================
    @patch("billing.services.payment_gateway.httpx.post")
    def test_dedicated_lease_provision_success(self, mock_post):
        # Mock payment gateway response: Success
        mock_response = httpx.Response(status_code=200, json={"status": "succeeded"})
        mock_post.return_return_value = mock_response  # fallback for httpx mocking
        mock_post.return_value = mock_response

        # Attempt to provision dedicated H100
        lease = provision_lease(self.user, self.h100_model.id, is_dedicated=True, card_token="tok_visa")

        # Verify lease is ACTIVE and billing amount matches the 1-hour upfront payment
        self.assertEqual(lease.status, RentalLeaseStatus.ACTIVE)
        self.assertEqual(lease.total_billed_amount, Decimal("4.76"))

        # Verify invoice is PAID
        invoice = Invoice.objects.filter(lease_id=lease.id).first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.amount, Decimal("4.76"))
        self.assertEqual(invoice.status, InvoiceStatus.PAID)

        # Verify physical instance is leased
        self.h100_instance.refresh_from_db()
        self.assertEqual(self.h100_instance.status, GPUInstanceStatus.LEASED)

    @patch("billing.services.payment_gateway.httpx.post")
    def test_dedicated_lease_provision_failed_payment_triggers_rollback(self, mock_post):
        # Mock payment gateway response: Decline/Failed
        mock_response = httpx.Response(status_code=402, json={"error": "card_declined"})
        mock_post.return_value = mock_response

        # Provision should fail with ValueError
        with self.assertRaises(ValueError) as context:
            provision_lease(self.user, self.h100_model.id, is_dedicated=True, card_token="tok_declined")

        self.assertIn("Upfront dedicated payment failed", str(context.exception))

        # Verify physical instance remains AVAILABLE
        self.h100_instance.refresh_from_db()
        self.assertEqual(self.h100_instance.status, GPUInstanceStatus.AVAILABLE)

        # No leases or invoices exist for this model
        self.assertEqual(RentalLease.objects.filter(gpu_instance=self.h100_instance).count(), 0)
        self.assertEqual(Invoice.objects.filter(user=self.user).count(), 0)

    # ==========================================
    # US05: PAYMENT GATEWAY CLIENT AND TIMEOUTS
    # ==========================================
    @patch("billing.services.payment_gateway.httpx.post")
    def test_payment_gateway_timeout_exception(self, mock_post):
        # Mock connection timeout
        mock_post.side_effect = httpx.TimeoutException("Connection timed out.")

        with self.assertRaises(PaymentTimeoutException):
            process_payment(self.user.id, Decimal("10.00"), "tok_visa")

    @patch("billing.services.payment_gateway.httpx.post")
    def test_payment_gateway_request_exception(self, mock_post):
        # Mock network failure
        mock_post.side_effect = httpx.RequestError("Network down.")

        with self.assertRaises(PaymentGatewayException):
            process_payment(self.user.id, Decimal("10.00"), "tok_visa")

    @patch("billing.services.payment_gateway.httpx.post")
    def test_refund_success(self, mock_post):
        mock_post.return_value = httpx.Response(status_code=200, json={"status": "refunded"})
        success = process_refund("invoice_123")
        self.assertTrue(success)

    @patch("billing.services.payment_gateway.httpx.post")
    def test_refund_timeout_exception(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("Timed out")
        with self.assertRaises(PaymentTimeoutException):
            process_refund("invoice_123")

    # ==========================================
    # US15: STRIPE WEBHOOKS & ASYNC RECONCILIATION
    # ==========================================
    def test_stripe_webhook_signature_rejected(self):
        # 1. Missing header gets 400 Bad Request
        response_missing = self.client.post(
            "/api/billing/webhooks/stripe/",
            data={},
            content_type="application/json",
        )
        self.assertEqual(response_missing.status_code, 400)
        self.assertEqual(response_missing.content.decode(), "Invalid Stripe signature.")

        # 2. Invalid header value gets 400 Bad Request
        response_invalid = self.client.post(
            "/api/billing/webhooks/stripe/",
            data={},
            content_type="application/json",
            headers={"Stripe-Signature": "invalid_signing_secret"},
        )
        self.assertEqual(response_invalid.status_code, 400)

    def test_stripe_webhook_refund_success_reconciles_database(self):
        # Create an invoice for $20.00
        invoice = Invoice.objects.create(
            user=self.user,
            lease_id=None,
            amount=Decimal("20.00"),
            status=InvoiceStatus.PAID,
            description="Upfront charge for GPU Model.",
        )

        # Create user prepaid balance
        credit = UserCredit.objects.create(user=self.user, balance=Decimal("50.00"))

        payload = {
            "type": "charge.refunded",
            "data": {
                "object": {
                    "metadata": {
                        "invoice_id": str(invoice.id),
                    }
                }
            },
        }

        # Fire webhook POST request with valid mock Stripe-Signature header
        response = self.client.post(
            "/api/billing/webhooks/stripe/",
            data=payload,
            content_type="application/json",
            headers={"Stripe-Signature": "whsec_test_secret_123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode(), "Webhook processed successfully.")

        # Assert Invoice status was updated to REFUNDED in DB (ImmediateBackend processed task instantly)
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.REFUNDED)
        self.assertIn("Refunded via Stripe Webhook", invoice.description)

        # Assert prepaid balance was refunded (50.00 + 20.00 = 70.00)
        credit.refresh_from_db()
        self.assertEqual(credit.balance, Decimal("70.00"))

        # Verify that a SystemAlert of type 'billing' was successfully logged
        from leases.models import SystemAlert

        alert = SystemAlert.objects.filter(alert_type="billing").order_by("-created_at").first()
        self.assertIsNotNone(alert)
        self.assertIn("Refund processed for Invoice", alert.message)

    def test_stripe_webhook_payment_failed_suspends_active_leases(self):
        # Rent a shared RTX 4090 card
        self.rtx_instance.status = GPUInstanceStatus.LEASED
        self.rtx_instance.save()
        lease = RentalLease.objects.create(
            user=self.user,
            gpu_instance=self.rtx_instance,
            status=RentalLeaseStatus.ACTIVE,
            started_at=timezone.now(),
        )

        payload = {
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "metadata": {
                        "user_id": str(self.user.id),
                    }
                }
            },
        }

        # Fire failed payment webhook
        response = self.client.post(
            "/api/billing/webhooks/stripe/",
            data=payload,
            content_type="application/json",
            headers={"Stripe-Signature": "whsec_test_secret_123"},
        )
        self.assertEqual(response.status_code, 200)

        # Assert lease is suspended and physical GPU instance released back to available
        lease.refresh_from_db()
        self.assertEqual(lease.status, RentalLeaseStatus.SUSPENDED_PAYMENT)
        self.rtx_instance.refresh_from_db()
        self.assertEqual(self.rtx_instance.status, GPUInstanceStatus.AVAILABLE)

        # Verify that a SystemAlert of type 'billing' was successfully logged
        from leases.models import SystemAlert

        alert = SystemAlert.objects.filter(alert_type="billing").first()
        self.assertIsNotNone(alert)
        self.assertIn("Payment failed webhook triggered", alert.message)

    # ==========================================
    # US10: UNIFIED PREPAID/POSTPAID BILLING ADJUSTMENTS
    # ==========================================
    def test_prepaid_eighty_percent_warning(self):
        from django.core import mail

        mail.outbox = []

        credit = UserCredit.objects.create(user=self.user, balance=Decimal("100.00"))
        self.assertEqual(credit.starting_balance, Decimal("100.00"))

        lease = provision_lease(self.user, self.rtx_model.id, is_dedicated=False)
        self.assertEqual(lease.status, RentalLeaseStatus.ACTIVE)

        # 1. First deduction of $5.00 (95% remaining, no alert)
        lease.started_at = timezone.now() - timezone.timedelta(minutes=6)
        lease.save(update_fields=["started_at"])

        worker = MetricsSimulatorWorker()
        worker.tick()

        credit.refresh_from_db()
        self.assertTrue(credit.balance > Decimal("20.00"))
        warnings_first = [m for m in mail.outbox if "Low Prepaid Credit Warning" in m.subject]
        self.assertEqual(len(warnings_first), 0)

        # 2. Large deduction that drops balance to <= $20.00 (representing >= 80% depletion)
        lease.started_at = timezone.now() - timezone.timedelta(minutes=100)
        lease.save(update_fields=["started_at"])

        worker.tick()

        credit.refresh_from_db()
        self.assertTrue(credit.balance <= Decimal("20.00"))
        self.assertTrue(credit.low_credit_alert_sent)

        warnings = [m for m in mail.outbox if "Low Prepaid Credit Warning" in m.subject]
        self.assertEqual(len(warnings), 1)
        self.assertIn("consumed 80% or more", warnings[0].body)

    def test_pre_to_post_upgrade_freezes_credit_and_abates_final_invoice(self):
        l4_model = GPUModel.objects.create(
            name="NVIDIA L4 (24GB)",
            vram_capacity_gb=24,
            price_per_hour=Decimal("0.50"),
        )
        GPUInstance.objects.create(
            serial_number="GPU-L4-UPGRADE-TEST",
            model=l4_model,
            status=GPUInstanceStatus.AVAILABLE,
            is_dedicated=False,
        )

        credit = UserCredit.objects.create(user=self.user, balance=Decimal("50.00"))

        lease = provision_lease(self.user, l4_model.id, is_dedicated=False)
        self.assertEqual(lease.status, RentalLeaseStatus.ACTIVE)

        from leases.orchestrators.upgrade_flow import upgrade_lease_tier

        upgraded_lease = upgrade_lease_tier(lease.id, self.h100_model.id)

        self.assertEqual(upgraded_lease.gpu_instance.model, self.h100_model)

        credit.refresh_from_db()
        self.assertEqual(credit.frozen_prepaid_balance, Decimal("35.00"))
        self.assertEqual(credit.balance, Decimal("0.00"))

        # Subsequent postpaid settlement abates the frozen balance
        upgraded_lease.started_at = timezone.now() - timezone.timedelta(minutes=5)
        upgraded_lease.save(update_fields=["started_at"])

        invoice_lease_usage(upgraded_lease)

        invoice = (
            Invoice.objects.filter(lease_id=upgraded_lease.id, description__contains="Usage invoice")
            .order_by("-created_at")
            .first()
        )
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.amount, Decimal("12.60"))
        self.assertEqual(invoice.status, InvoiceStatus.UNPAID)
        self.assertIn("Abated", invoice.description)

        credit.refresh_from_db()
        self.assertEqual(credit.frozen_prepaid_balance, Decimal("0.00"))

    def test_flat_fees_instantly_paid_by_prepaid_balance(self):
        l4_model = GPUModel.objects.create(
            name="NVIDIA L4 (24GB)",
            vram_capacity_gb=24,
            price_per_hour=Decimal("0.50"),
        )
        GPUInstance.objects.create(
            serial_number="GPU-L4-FLAT-FEE-TEST",
            model=l4_model,
            status=GPUInstanceStatus.AVAILABLE,
            is_dedicated=False,
        )

        credit = UserCredit.objects.create(user=self.user, balance=Decimal("50.00"))

        lease = provision_lease(self.user, l4_model.id, is_dedicated=False)

        from leases.orchestrators.upgrade_flow import upgrade_lease_tier

        upgrade_lease_tier(lease.id, self.h100_model.id)

        invoice = Invoice.objects.filter(lease_id=lease.id, description__contains="Flat upgrade charge").first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.amount, Decimal("15.00"))
        self.assertEqual(invoice.status, InvoiceStatus.PAID)

        credit.refresh_from_db()
        self.assertEqual(credit.frozen_prepaid_balance, Decimal("35.00"))

    def test_postpaid_grace_period_enforcement(self):
        from users.models import TenantProfile

        self.h100_instance.status = GPUInstanceStatus.LEASED
        self.h100_instance.save()
        lease = RentalLease.objects.create(
            user=self.user,
            gpu_instance=self.h100_instance,
            status=RentalLeaseStatus.ACTIVE,
            started_at=timezone.now(),
        )

        invoice = Invoice.objects.create(
            user=self.user,
            lease_id=lease.id,
            amount=Decimal("100.00"),
            status=InvoiceStatus.UNPAID,
            description="Usage invoice for NVIDIA H100 (80GB SXM5)",
        )

        # 6 simulated days = 75 real minutes elapsed
        invoice.created_at = timezone.now() - timezone.timedelta(minutes=75)
        invoice.save(update_fields=["created_at"])

        worker = MetricsSimulatorWorker()
        worker.tick()

        profile = TenantProfile.objects.get(user=self.user)
        self.assertIsNotNone(profile.freezed_at)

        lease.refresh_from_db()
        self.assertEqual(lease.status, RentalLeaseStatus.COMPLETED)
        self.h100_instance.refresh_from_db()
        self.assertEqual(self.h100_instance.status, GPUInstanceStatus.AVAILABLE)

        unfreeze_fee_invoice = Invoice.objects.filter(description="Standard Unfreeze Fee", user=self.user).first()
        self.assertIsNotNone(unfreeze_fee_invoice)
        self.assertEqual(unfreeze_fee_invoice.amount, Decimal("25.00"))
        self.assertEqual(unfreeze_fee_invoice.status, InvoiceStatus.UNPAID)

    # ==========================================
    # US04 - TASK 4.5: 3+ MONTH PREPAID PACKAGE BONUS
    # ==========================================
    def test_prepaid_package_three_months_awards_one_month_bonus_for_new_user(self):
        from billing.services.ledger import purchase_prepaid_package

        new_user = User.objects.create_user(username="newpromo_user", password="securepassword")

        # Purchase 3-month package on RTX 4090 ($0.44/h * 730h * 3 = $963.60)
        res = purchase_prepaid_package(new_user, self.rtx_model, months=3, hours_per_month=730)

        self.assertTrue(res["bonus_applied"])
        self.assertEqual(res["base_amount"], Decimal("963.60"))
        self.assertEqual(res["bonus_amount"], Decimal("321.20"))  # 1 month = 730h * $0.44
        self.assertEqual(res["total_credited"], Decimal("1284.80"))

        credit = UserCredit.objects.get(user=new_user)
        self.assertEqual(credit.balance, Decimal("1284.80"))

        invoice = Invoice.objects.get(id=res["invoice_id"])
        self.assertEqual(invoice.amount, Decimal("963.60"))
        self.assertEqual(invoice.status, InvoiceStatus.PAID)
        self.assertIn("Includes 1 Free Month Promo Bonus", invoice.description)

    def test_prepaid_package_under_three_months_no_bonus(self):
        from billing.services.ledger import purchase_prepaid_package

        new_user = User.objects.create_user(username="twomonth_user", password="securepassword")
        res = purchase_prepaid_package(new_user, self.rtx_model, months=2, hours_per_month=730)

        self.assertFalse(res["bonus_applied"])
        self.assertEqual(res["base_amount"], Decimal("642.40"))
        self.assertEqual(res["bonus_amount"], Decimal("0.00"))
        self.assertEqual(res["total_credited"], Decimal("642.40"))

        credit = UserCredit.objects.get(user=new_user)
        self.assertEqual(credit.balance, Decimal("642.40"))

    def test_prepaid_package_six_months_awards_one_fixed_month_bonus(self):
        from billing.services.ledger import purchase_prepaid_package

        new_user = User.objects.create_user(username="sixmonth_user", password="securepassword")
        res = purchase_prepaid_package(new_user, self.rtx_model, months=6, hours_per_month=730)

        self.assertTrue(res["bonus_applied"])
        self.assertEqual(res["base_amount"], Decimal("1927.20"))
        self.assertEqual(res["bonus_amount"], Decimal("321.20"))  # 1 fixed month
        self.assertEqual(res["total_credited"], Decimal("2248.40"))

    def test_prepaid_package_existing_user_ineligible_for_promo_bonus(self):
        from billing.services.ledger import purchase_prepaid_package

        # self.user already has prior test activity / we can create an existing invoice
        Invoice.objects.create(
            user=self.user,
            amount=Decimal("10.00"),
            status=InvoiceStatus.PAID,
            description="Existing invoice",
        )

        res = purchase_prepaid_package(self.user, self.rtx_model, months=3, hours_per_month=730)
        self.assertFalse(res["bonus_applied"])
        self.assertEqual(res["bonus_amount"], Decimal("0.00"))
        self.assertEqual(res["base_amount"], Decimal("963.60"))
        self.assertEqual(res["total_credited"], Decimal("963.60"))

    def test_prepaid_package_api_endpoint(self):
        from rest_framework.test import APIClient

        client = APIClient()
        promo_user = User.objects.create_user(username="api_promo_user", password="securepassword")
        client.force_authenticate(user=promo_user)

        response = client.post(
            "/api/v1/billing/purchase-package/",
            {"model_id": str(self.rtx_model.id), "months": 3, "hours_per_month": 730},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["bonus_applied"])
        self.assertEqual(response.data["bonus_amount"], Decimal("321.20"))

    # ==========================================
    # US16: CLIENT USAGE CYCLES & FRACTIONAL USAGE
    # ==========================================
    def test_client_usage_cycle_accumulation_fractional_hours(self):
        UserCredit.objects.create(user=self.user, balance=Decimal("100.00"))
        lease = provision_lease(self.user, self.rtx_model.id, is_dedicated=False)

        # Simulate elapsed time of 30 real seconds = 1 simulated hour (cost $0.44)
        lease.started_at = timezone.now() - timezone.timedelta(seconds=30)
        lease.save(update_fields=["started_at"])

        worker = MetricsSimulatorWorker()
        worker.tick()

        cycle = ClientUsageCycle.objects.filter(client=self.user, is_active=True).first()
        self.assertIsNotNone(cycle)
        self.assertEqual(cycle.plan_type, PlanType.PREPAID)
        self.assertEqual(cycle.gpu, self.rtx_model.name)
        self.assertEqual(cycle.hours_consumed, Decimal("1.0000"))
        self.assertEqual(cycle.total_consumption, Decimal("0.44"))
        self.assertIsNone(cycle.cycle_ended_at)
        self.assertTrue(cycle.is_active)

        # Assert no premature invoice was emitted during normal running ticks
        invoices_count = Invoice.objects.filter(lease_id=lease.id).count()
        self.assertEqual(invoices_count, 0)

    def test_postpaid_thirty_day_cycle_generates_invoice_and_rolls_new_cycle(self):
        h100_instance = GPUInstance.objects.create(
            serial_number="GPU-H100-CYCLE-TEST",
            model=self.h100_model,
            status=GPUInstanceStatus.AVAILABLE,
            is_dedicated=False,
        )
        lease = RentalLease.objects.create(
            user=self.user,
            gpu_instance=h100_instance,
            status=RentalLeaseStatus.ACTIVE,
            started_at=timezone.now() - timezone.timedelta(minutes=1),
        )
        # Create active postpaid cycle started 31 simulated days ago
        # (with TIME_SCALE_FACTOR=120, 31 days = 372 real minutes)
        cycle = ClientUsageCycle.objects.create(
            client=self.user,
            plan_type=PlanType.POSTPAID,
            gpu=self.h100_model.name,
            hours_consumed=Decimal("720.0000"),
            total_consumption=Decimal("1353.60"),
            total_credits=Decimal("0.00"),
            cycle_started_at=timezone.now() - timezone.timedelta(minutes=372),
            cycle_ended_at=None,
            is_active=True,
        )

        worker = MetricsSimulatorWorker()
        worker.tick()

        cycle.refresh_from_db()
        self.assertFalse(cycle.is_active)
        self.assertIsNotNone(cycle.cycle_ended_at)

        # Assert 30-day postpaid invoice was generated
        invoice = Invoice.objects.filter(lease_id=lease.id, status=InvoiceStatus.UNPAID).first()
        self.assertIsNotNone(invoice)
        self.assertGreater(invoice.amount, Decimal("1350.00"))
        self.assertIn("30-Day Postpaid Usage Invoice", invoice.description)

        # Assert a new active cycle was opened
        new_cycle = ClientUsageCycle.objects.filter(client=self.user, is_active=True).first()
        self.assertIsNotNone(new_cycle)
        self.assertNotEqual(new_cycle.id, cycle.id)
        self.assertEqual(new_cycle.hours_consumed, Decimal("0.0000"))
        self.assertEqual(new_cycle.total_consumption, Decimal("0.00"))
