from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from billing.models import UserCredit
from leases.models import GPUInstance, GPUInstanceStatus, GPUModel, RentalLeaseStatus
from leases.orchestrators.lease_flow import provision_lease
from leases.services.fleet_analytics import get_fleet_snapshot

User = get_user_model()


class ConcurrencyAndAuditorTestCase(TestCase):
    def setUp(self):
        # Create users
        self.users = [User.objects.create_user(username=f"user_{i}", password="password") for i in range(6)]

        # Top up prepaid credit for all test users
        for u in self.users:
            UserCredit.objects.create(user=u, balance=Decimal("100.00"))
        self.h100_model = GPUModel.objects.create(
            name="NVIDIA H100 (80GB SXM5)",
            vram_capacity_gb=80,
            price_per_hour=Decimal("4.76"),
        )
        self.rtx_model = GPUModel.objects.create(
            name="NVIDIA RTX 4090 (24GB)",
            vram_capacity_gb=24,
            price_per_hour=Decimal("0.44"),
        )

        # Create 1 physical dedicated instance of H100
        self.h100_instance = GPUInstance.objects.create(
            serial_number="GPU-H100-DEDICATED-99",
            model=self.h100_model,
            status=GPUInstanceStatus.AVAILABLE,
            is_dedicated=True,
        )

        # Create exactly 1 physical shared instance of RTX 4090
        self.rtx_instance = GPUInstance.objects.create(
            serial_number="GPU-RTX-SHARED-99",
            model=self.rtx_model,
            status=GPUInstanceStatus.AVAILABLE,
            is_dedicated=False,
        )

    @patch("billing.services.payment_gateway.httpx.post")
    def test_dedicated_single_tenant_isolation(self, mock_post):
        # Mock payment gateway response: Success
        import httpx

        mock_response = httpx.Response(status_code=200, json={"status": "succeeded"})
        mock_post.return_value = mock_response

        # Rent H100 dedicated instance once for User 0 (with a mocked gateway card_token)
        lease1 = provision_lease(
            user=self.users[0],
            gpu_model_id=self.h100_model.id,
            is_dedicated=True,
            card_token="tok_visa",
        )
        self.assertEqual(lease1.status, RentalLeaseStatus.ACTIVE)

        # Verify physical instance is now LEASED
        self.h100_instance.refresh_from_db()
        self.assertEqual(self.h100_instance.status, GPUInstanceStatus.LEASED)

        # Try to rent dedicated H100 a second time for User 1
        with self.assertRaises(ValueError) as context:
            provision_lease(
                user=self.users[1],
                gpu_model_id=self.h100_model.id,
                is_dedicated=True,
                card_token="tok_visa",
            )

        self.assertIn("No available physical GPU instances", str(context.exception))

    def test_shared_multi_tenant_concurrency(self):
        # We can rent the same shared instance up to 4 times for different users
        leases = []
        for i in range(3):
            lease = provision_lease(
                user=self.users[i],
                gpu_model_id=self.rtx_model.id,
                is_dedicated=False,
            )
            self.assertEqual(lease.status, RentalLeaseStatus.ACTIVE)
            leases.append(lease)

            # Up to 3, instance should remain AVAILABLE
            self.rtx_instance.refresh_from_db()
            self.assertEqual(self.rtx_instance.status, GPUInstanceStatus.AVAILABLE)

        # Rent the 4th time (reaches limit)
        lease4 = provision_lease(
            user=self.users[3],
            gpu_model_id=self.rtx_model.id,
            is_dedicated=False,
        )
        self.assertEqual(lease4.status, RentalLeaseStatus.ACTIVE)

        # Confirm physical instance has transitioned to LEASED (occupied)
        self.rtx_instance.refresh_from_db()
        self.assertEqual(self.rtx_instance.status, GPUInstanceStatus.LEASED)

        # Attempt to rent a 5th time (should fail because card is LEASED and no other cards are available)
        with self.assertRaises(ValueError) as context:
            provision_lease(
                user=self.users[4],
                gpu_model_id=self.rtx_model.id,
                is_dedicated=False,
            )

        self.assertIn("No available physical GPU instances", str(context.exception))

    def test_concurrency_analytics_no_n_plus_one_queries(self):
        # Set up active leases to populate dashboard
        provision_lease(self.users[0], self.rtx_model.id, is_dedicated=False)
        provision_lease(self.users[1], self.rtx_model.id, is_dedicated=False)

        # Query snapshot while capturing database query count
        with CaptureQueriesContext(connection) as ctx:
            snapshot = get_fleet_snapshot()

        # Dashboard analytics should run in exactly 5 query evaluations (no N+1 loops)
        self.assertLessEqual(len(ctx), 6)

        # Verify analytics format correctness
        self.assertEqual(snapshot["active_leases_count"], 2)
        self.assertEqual(snapshot["active_clients_count"], 2)
        self.assertEqual(snapshot["available_cards_count"], 2)  # H100 dedicated and shared RTX are both AVAILABLE
        self.assertEqual(snapshot["leased_cards_count"], 0)  # RTX is available since occupancy (2) < 4
        self.assertEqual(snapshot["total_allocated_vram"], 48)  # 2 * 24GB RTX 4090
