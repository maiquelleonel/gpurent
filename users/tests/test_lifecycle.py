from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from billing.models import Invoice, InvoiceStatus, UserCredit
from leases.models import GPUInstance, GPUInstanceStatus, GPUModel, RentalLease, RentalLeaseStatus
from users.models import TenantProfile
from users.orchestrators.lifecycle import (
    freeze_tenant_account,
    soft_delete_tenant,
    unfreeze_tenant_account,
)

User = get_user_model()


class TenantLifecycleTestCase(TestCase):
    def setUp(self):
        # Create users
        self.user = User.objects.create_user(username="tenantuser", password="securepassword")
        self.profile = self.user.profile  # Auto-created via signal

        # Create credits
        self.credit = UserCredit.objects.create(user=self.user, balance=Decimal("100.00"))

        # Create Models and Instances
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

        self.rtx_instance = GPUInstance.objects.create(
            serial_number="GPU-RTX-FREEZE",
            model=self.rtx_model,
            status=GPUInstanceStatus.AVAILABLE,
            is_dedicated=False,
        )
        self.h100_instance = GPUInstance.objects.create(
            serial_number="GPU-H100-FREEZE",
            model=self.h100_model,
            status=GPUInstanceStatus.AVAILABLE,
            is_dedicated=True,
        )

    def test_signal_automatically_creates_tenant_profile(self):
        # Create new user
        new_user = User.objects.create_user(username="newtenant", password="password123")
        self.assertIsNotNone(new_user.profile)
        self.assertTrue(isinstance(new_user.profile, TenantProfile))
        self.assertIsNone(new_user.profile.freezed_at)
        self.assertIsNone(new_user.profile.deleted_at)

    def test_can_delete_eligibility_validations(self):
        # 1. By default, can delete is True
        self.assertTrue(self.profile.can_delete())

        # 2. Blocked if there are unpaid invoices
        invoice = Invoice.objects.create(
            user=self.user,
            lease_id=None,
            amount=Decimal("15.00"),
            status=InvoiceStatus.UNPAID,
            description="Unpaid upgrade fee",
        )
        self.assertFalse(self.profile.can_delete())

        # Settle invoice
        invoice.status = InvoiceStatus.PAID
        invoice.save()
        self.assertTrue(self.profile.can_delete())

        # 3. Blocked if prepaid credit balance is negative
        self.credit.balance = Decimal("-5.50")
        self.credit.save()
        self.assertFalse(self.profile.can_delete())

        # Settle credits back to zero
        self.credit.balance = Decimal("0.00")
        self.credit.save()
        self.assertTrue(self.profile.can_delete())

    def test_soft_delete_releases_active_leases_and_disables_auth(self):
        # Lease rtx instance
        self.rtx_instance.status = GPUInstanceStatus.LEASED
        self.rtx_instance.save()
        lease = RentalLease.objects.create(
            user=self.user,
            gpu_instance=self.rtx_instance,
            status=RentalLeaseStatus.ACTIVE,
            started_at=timezone.now(),
        )

        # Trigger soft-delete
        updated_profile = soft_delete_tenant(self.user.id)

        # Check soft-deleted fields and disabled auth
        self.assertIsNotNone(updated_profile.deleted_at)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

        # Check that active leases are terminated and physical instances released
        lease.refresh_from_db()
        self.assertEqual(lease.status, RentalLeaseStatus.COMPLETED)
        self.rtx_instance.refresh_from_db()
        self.assertEqual(self.rtx_instance.status, GPUInstanceStatus.AVAILABLE)

    @patch("django.tasks.backends.immediate.ImmediateBackend.enqueue")
    def test_freeze_and_unfreeze_shared_gpus_releases_immediately(self, mock_enqueue):
        self.rtx_instance.status = GPUInstanceStatus.LEASED
        self.rtx_instance.save()
        lease = RentalLease.objects.create(
            user=self.user,
            gpu_instance=self.rtx_instance,
            status=RentalLeaseStatus.ACTIVE,
            started_at=timezone.now(),
        )

        # Freeze account releasing all gpus
        freeze_tenant_account(self.user.id, keep_dedicated_gpus=False)

        self.profile.refresh_from_db()
        self.assertIsNotNone(self.profile.freezed_at)
        self.assertFalse(self.profile.keep_dedicated_gpus)

        # Confirm shared lease is terminated and instance released
        lease.refresh_from_db()
        self.assertEqual(lease.status, RentalLeaseStatus.COMPLETED)
        self.rtx_instance.refresh_from_db()
        self.assertEqual(self.rtx_instance.status, GPUInstanceStatus.AVAILABLE)

        # Unfreeze
        unfreeze_tenant_account(self.user.id)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.freezed_at)

    @patch("django.tasks.backends.immediate.ImmediateBackend.enqueue")
    def test_freeze_and_unfreeze_dedicated_gpu_with_preservation_fee(self, mock_enqueue):
        # Rent dedicated H100
        self.h100_instance.status = GPUInstanceStatus.LEASED
        self.h100_instance.save()
        lease = RentalLease.objects.create(
            user=self.user,
            gpu_instance=self.h100_instance,
            status=RentalLeaseStatus.ACTIVE,
            started_at=timezone.now(),
        )

        # Freeze account OPTING to hold dedicated GPU
        freeze_tenant_account(self.user.id, keep_dedicated_gpus=True)

        self.profile.refresh_from_db()
        self.assertIsNotNone(self.profile.freezed_at)
        self.assertTrue(self.profile.keep_dedicated_gpus)

        # Confirm dedicated lease remains ACTIVE
        lease.refresh_from_db()
        self.assertEqual(lease.status, RentalLeaseStatus.ACTIVE)
        self.h100_instance.refresh_from_db()
        self.assertEqual(self.h100_instance.status, GPUInstanceStatus.LEASED)

        # Simulate 1 physical minute of frozen state (represents 2 simulated hours)
        self.profile.freezed_at = timezone.now() - timezone.timedelta(minutes=1)
        self.profile.save()

        # Unfreeze
        unfreeze_tenant_account(self.user.id)

        # Check holding fee was calculated and charged
        # H100 standard hourly price = 4.76
        # Weekly holding fee = 10% of hourly * 168 hours
        # Pro-rated holding fee for 2 simulated hours: 2 * (4.76 * 10%) = 2 * 0.476 = 0.952 -> 0.95
        lease.refresh_from_db()
        self.assertEqual(lease.total_billed_amount, Decimal("0.95"))

        # Verify pre-paid UserCredit deduction (100.00 - 0.95 = 99.05)
        self.credit.refresh_from_db()
        self.assertEqual(self.credit.balance, Decimal("99.05"))

        # Verify pre-paid Invoice was created
        invoice = Invoice.objects.filter(lease_id=lease.id).first()
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice.amount, Decimal("0.95"))
        self.assertEqual(invoice.status, InvoiceStatus.PAID)

        # Unfrozen state reset
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.freezed_at)
        self.assertFalse(self.profile.keep_dedicated_gpus)

    @patch("django.tasks.backends.immediate.ImmediateBackend.enqueue")
    def test_api_shielding_middleware_blocks_frozen_and_deleted_users(self, mock_enqueue):
        client = Client()
        client.force_login(self.user)

        # 1. Accessing normally
        response = client.get("/admin/")
        self.assertIn(response.status_code, [200, 302])

        # 2. Freeze account
        freeze_tenant_account(self.user.id)
        response_frozen = client.get("/admin/")
        self.assertEqual(response_frozen.status_code, 403)
        self.assertJSONEqual(
            response_frozen.content.decode(), {"error": "Account is frozen. Please reactivate to proceed."}
        )

        # Allow accessing unfreeze endpoint (bypasses middleware API shielding, returning 405 instead of 403)
        response_unfreeze_route = client.get("/api/v1/tenants/unfreeze/")
        self.assertIn(response_unfreeze_route.status_code, [200, 302, 404, 405])

        # 3. Unfreeze account and then soft-delete
        unfreeze_tenant_account(self.user.id)
        soft_delete_tenant(self.user.id)

        # A soft-deleted (is_active=False) user is logged out and redirected to login (302)
        response_deleted = client.get("/admin/")
        self.assertEqual(response_deleted.status_code, 302)

    def test_freeze_expiry_task_soft_deletes_account(self):
        # Freeze account (mocking enqueue so it doesn't run prematurely)
        with patch("django.tasks.backends.immediate.ImmediateBackend.enqueue"):
            freeze_tenant_account(self.user.id)

        # Verify frozen but not yet deleted
        self.profile.refresh_from_db()
        self.assertIsNotNone(self.profile.freezed_at)
        self.assertIsNone(self.profile.deleted_at)

        # Manually invoke the freeze expiry task to simulate 30-day cron trigger
        from users.tasks import schedule_freeze_expiry_check

        schedule_freeze_expiry_check.func(self.user.id)

        # Assert account was successfully soft-deleted after expiry!
        self.profile.refresh_from_db()
        self.assertIsNotNone(self.profile.deleted_at)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
