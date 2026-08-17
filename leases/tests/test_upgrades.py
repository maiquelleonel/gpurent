from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from billing.models import Invoice, InvoiceStatus, UserCredit
from leases.models import GPUInstance, GPUInstanceStatus, GPUModel, RentalLease, RentalLeaseStatus
from leases.orchestrators.upgrade_flow import upgrade_lease_tier

User = get_user_model()


class UpgradeFlowTestCase(TestCase):
    def setUp(self):
        # Create test user
        self.user = User.objects.create_user(username="upgradeuser", password="securepassword")

        # Create pre-paid credit for the user
        self.credit = UserCredit.objects.create(user=self.user, balance=Decimal("100.00"))

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
        self.a100_40_model = GPUModel.objects.create(
            name="NVIDIA A100 (40GB PCIe)",
            vram_capacity_gb=40,
            price_per_hour=Decimal("1.21"),
        )
        self.a100_80_model = GPUModel.objects.create(
            name="NVIDIA A100 (80GB PCIe)",
            vram_capacity_gb=80,
            price_per_hour=Decimal("1.88"),
        )

        # Create GPU Instances
        self.rtx_instance = GPUInstance.objects.create(
            serial_number="GPU-RTX-999",
            model=self.rtx_model,
            status=GPUInstanceStatus.LEASED,
            is_dedicated=False,
        )
        self.h100_instance = GPUInstance.objects.create(
            serial_number="GPU-H100-999",
            model=self.h100_model,
            status=GPUInstanceStatus.AVAILABLE,
            is_dedicated=True,
        )
        self.a100_40_instance = GPUInstance.objects.create(
            serial_number="GPU-A100-40GB-999",
            model=self.a100_40_model,
            status=GPUInstanceStatus.LEASED,
            is_dedicated=False,
        )
        self.a100_80_instance = GPUInstance.objects.create(
            serial_number="GPU-A100-80GB-999",
            model=self.a100_80_model,
            status=GPUInstanceStatus.AVAILABLE,
            is_dedicated=False,
        )

    def test_tier_swap_success(self):
        # 1. Create an active lease on RTX 4090 (prepaid source, $0.44/hour)
        # We simulate the lease started 1 real-world minute ago
        # With TIME_SCALE_FACTOR = 120, 1 real minute = 2 simulated hours.
        # Cost should be 2 * 0.44 = 0.88.
        started_at = timezone.now() - timezone.timedelta(minutes=1)
        lease = RentalLease.objects.create(
            user=self.user,
            gpu_instance=self.rtx_instance,
            status=RentalLeaseStatus.ACTIVE,
            started_at=started_at,
        )

        # Execute upgrade to H100 (post-paid target, different family)
        updated_lease = upgrade_lease_tier(lease.id, self.h100_model.id)

        # Verify physical resource swaps
        self.rtx_instance.refresh_from_db()
        self.h100_instance.refresh_from_db()
        self.assertEqual(self.rtx_instance.status, GPUInstanceStatus.AVAILABLE)
        self.assertEqual(self.h100_instance.status, GPUInstanceStatus.LEASED)

        # Verify updated lease fields
        self.assertEqual(updated_lease.gpu_instance, self.h100_instance)
        # Accrued usage cost ($0.88) + flat tier swap fee ($15.00) = $15.88
        self.assertEqual(updated_lease.total_billed_amount, Decimal("15.88"))

        # Verify Invoices generated
        # Outstanding accrued usage invoice (prepaid model RTX -> deducts credit)
        # Flat tier swap fee invoice (H100 target is postpaid -> invoice is UNPAID)
        invoices = Invoice.objects.filter(lease_id=lease.id).order_by("created_at")
        self.assertEqual(invoices.count(), 2)

        usage_invoice = invoices[0]
        self.assertEqual(usage_invoice.amount, Decimal("0.88"))
        self.assertEqual(usage_invoice.status, InvoiceStatus.PAID)  # Paid because RTX is prepaid

        fee_invoice = invoices[1]
        self.assertEqual(fee_invoice.amount, Decimal("15.00"))
        self.assertEqual(fee_invoice.status, InvoiceStatus.UNPAID)  # Unpaid because H100 target is postpaid

        # Verify Prepaid Credit deduction
        self.credit.refresh_from_db()
        # Initial $100.00 - accrued usage $0.88 = $99.12
        # (Tier swap fee of $15.00 is UNPAID deferred postpaid invoice, so not deducted from pre-paid balance)
        self.assertEqual(self.credit.balance, Decimal("99.12"))

    def test_vram_scaling_success(self):
        # 1. Create active lease on A100 40GB (postpaid source, $1.21/hour)
        # Lease started 1 real-world minute ago (2 simulated hours -> 2 * 1.21 = 2.42)
        started_at = timezone.now() - timezone.timedelta(minutes=1)
        lease = RentalLease.objects.create(
            user=self.user,
            gpu_instance=self.a100_40_instance,
            status=RentalLeaseStatus.ACTIVE,
            started_at=started_at,
        )

        # Execute upgrade to A100 80GB (postpaid target, same family)
        updated_lease = upgrade_lease_tier(lease.id, self.a100_80_model.id)

        # Verify physical resource swaps
        self.a100_40_instance.refresh_from_db()
        self.a100_80_instance.refresh_from_db()
        self.assertEqual(self.a100_40_instance.status, GPUInstanceStatus.AVAILABLE)
        self.assertEqual(self.a100_80_instance.status, GPUInstanceStatus.LEASED)

        # Verify updated lease fields
        self.assertEqual(updated_lease.gpu_instance, self.a100_80_instance)
        # Accrued cost ($2.42) + VRAM scaling flat fee ($5.00) = $7.42
        self.assertEqual(updated_lease.total_billed_amount, Decimal("7.42"))

        # Verify Invoices generated (Both are postpaid models -> UNPAID)
        invoices = Invoice.objects.filter(lease_id=lease.id).order_by("created_at")
        self.assertEqual(invoices.count(), 2)

        usage_invoice = invoices[0]
        self.assertEqual(usage_invoice.amount, Decimal("2.42"))
        self.assertEqual(usage_invoice.status, InvoiceStatus.UNPAID)

        fee_invoice = invoices[1]
        self.assertEqual(fee_invoice.amount, Decimal("5.00"))
        self.assertEqual(fee_invoice.status, InvoiceStatus.UNPAID)

        # User credits should be untouched since both models are postpaid
        self.credit.refresh_from_db()
        self.assertEqual(self.credit.balance, Decimal("100.00"))

    def test_transaction_rollback_on_allocation_failure(self):
        # 1. Create active lease on RTX 4090
        started_at = timezone.now() - timezone.timedelta(minutes=1)
        lease = RentalLease.objects.create(
            user=self.user,
            gpu_instance=self.rtx_instance,
            status=RentalLeaseStatus.ACTIVE,
            started_at=started_at,
        )

        # Temporarily make H100 target model unavailable
        self.h100_instance.status = GPUInstanceStatus.LEASED
        self.h100_instance.save()

        # Attempt upgrade, which should fail due to no available target instance
        with self.assertRaises(ValueError) as context:
            upgrade_lease_tier(lease.id, self.h100_model.id)

        self.assertIn("No available physical instances", str(context.exception))

        # Assert full database transaction rollback:
        # - Lease remains unchanged
        lease.refresh_from_db()
        self.assertEqual(lease.gpu_instance, self.rtx_instance)
        self.assertEqual(lease.total_billed_amount, Decimal("0.00"))
        self.assertEqual(lease.started_at, started_at)

        # - Old instance remains LEASED
        self.rtx_instance.refresh_from_db()
        self.assertEqual(self.rtx_instance.status, GPUInstanceStatus.LEASED)

        # - No invoices created
        self.assertEqual(Invoice.objects.filter(lease_id=lease.id).count(), 0)

        # - User Credit remains untouched
        self.credit.refresh_from_db()
        self.assertEqual(self.credit.balance, Decimal("100.00"))
