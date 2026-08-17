from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from billing.models import Invoice, UserCredit
from billing.services.ledger import calculate_accrued_cost, invoice_lease_usage
from leases.models import GPUInstance, GPUInstanceStatus, GPUModel, RentalLease, RentalLeaseStatus
from leases.utils.time_scale import get_simulated_duration

User = get_user_model()


class TimeScaleTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="timeuser", password="securepassword")

        # Create model and instances
        self.rtx_model = GPUModel.objects.create(
            name="NVIDIA RTX 4090 (24GB)",
            vram_capacity_gb=24,
            price_per_hour=Decimal("0.44"),
        )
        self.rtx_instance = GPUInstance.objects.create(
            serial_number="GPU-RTX-TIME",
            model=self.rtx_model,
            status=GPUInstanceStatus.LEASED,
            is_dedicated=False,
        )

    def test_get_simulated_duration_math(self):
        started_at = timezone.now()
        # 1. 30 real-world seconds
        ended_at_30s = started_at + timedelta(seconds=30)
        # 30 * 120 (TIME_SCALE_FACTOR) = 3600 simulated seconds = 1 simulated hour (3600 seconds)
        simulated_duration = get_simulated_duration(started_at, ended_at_30s)
        self.assertEqual(simulated_duration.total_seconds(), 3600.0)

        # 2. 1 real-world minute
        ended_at_1m = started_at + timedelta(minutes=1)
        # 1 minute * 120 = 120 simulated minutes = 2 simulated hours (7200 seconds)
        simulated_duration_2 = get_simulated_duration(started_at, ended_at_1m)
        self.assertEqual(simulated_duration_2.total_seconds(), 7200.0)

        # 3. Invalid negative time range
        simulated_duration_neg = get_simulated_duration(ended_at_1m, started_at)
        self.assertEqual(simulated_duration_neg.total_seconds(), 0.0)

    def test_calculate_accrued_cost_with_accelerated_time(self):
        # 1 real minute in the past represents 2 simulated hours.
        # Cost for RTX 4090 ($0.44/hr) for 2 simulated hours should be:
        # 2 * 0.44 = $0.88
        started_at = timezone.now() - timedelta(minutes=1)
        cost = calculate_accrued_cost(started_at, timezone.now(), self.rtx_model.price_per_hour)
        self.assertEqual(cost, Decimal("0.88"))

        # 30 real seconds in the past represents 1 simulated hour.
        # Cost should be 1 * 0.44 = $0.44
        started_at_30s = timezone.now() - timedelta(seconds=30)
        cost_30s = calculate_accrued_cost(started_at_30s, timezone.now(), self.rtx_model.price_per_hour)
        self.assertEqual(cost_30s, Decimal("0.44"))

    def test_billing_ledger_accrued_cost_and_credit_deduction(self):
        # Top up user credits
        credit = UserCredit.objects.create(user=self.user, balance=Decimal("10.00"))

        # Create lease started 1 physical minute ago (2 simulated hours -> cost $0.88)
        started_at = timezone.now() - timedelta(minutes=1)
        lease = RentalLease.objects.create(
            user=self.user,
            gpu_instance=self.rtx_instance,
            status=RentalLeaseStatus.ACTIVE,
            started_at=started_at,
        )

        # Invoice lease usage
        amount = invoice_lease_usage(lease)

        # Assert correct billing amount ($0.88)
        self.assertEqual(amount, Decimal("0.88"))

        # Verify pre-paid balance deduction (10.00 - 0.88 = 9.12)
        credit.refresh_from_db()
        self.assertEqual(credit.balance, Decimal("9.12"))

        # Verify Invoice creation
        invoice = Invoice.objects.filter(lease_id=lease.id).first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.amount, Decimal("0.88"))
