from decimal import Decimal
from unittest.mock import patch

import httpx
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from rest_framework import status

from billing.models import Invoice, InvoiceStatus, UserCredit
from leases.models import GPUModel, RentalLease, RentalLeaseStatus

User = get_user_model()


class APILayerTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        # Seed catalog in test database
        from io import StringIO

        from django.core.management import call_command

        call_command("seed_catalog", stdout=StringIO())

        # Retrieve seeded model ids
        self.rtx_model = GPUModel.objects.get(name="NVIDIA RTX 4090 (24GB)")
        self.h100_model = GPUModel.objects.get(name="NVIDIA H100 (80GB SXM5)")

    def test_register_creates_tenant_with_credits_and_enqueues_email(self):
        # Trigger register endpoint
        payload = {
            "username": "api_tenant",
            "email": "api_tenant@example.com",
            "password": "strongpassword123",
        }

        # No token needed for register (public)
        response = self.client.post(
            "/api/v1/tenants/register/",
            data=payload,
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["username"], "api_tenant")

        # Verify DB entities
        user = User.objects.get(username="api_tenant")
        self.assertIsNotNone(user.profile)
        self.assertEqual(user.email, "api_tenant@example.com")

        # Verify returned token matches the real DRF token key in DB
        real_token_key = user.auth_token.key
        self.assertEqual(response.json()["api_token"], real_token_key)

        # Test utilizing this real token key to request authenticated endpoints (e.g. leases catalog)
        response_catalog = self.client.get(
            "/api/v1/leases/catalog/",
            headers={"X-API-Token": real_token_key},
        )
        self.assertEqual(response_catalog.status_code, status.HTTP_200_OK)

        # Verify $50.00 prepaid starting balance
        credit = UserCredit.objects.get(user=user)
        self.assertEqual(credit.balance, Decimal("50.00"))

    def test_unauthenticated_request_is_rejected(self):
        # Try to read catalog without token header
        response = self.client.get("/api/v1/leases/catalog/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Try to read catalog with invalid token header
        response_invalid = self.client.get(
            "/api/v1/leases/catalog/",
            headers={"X-API-Token": "invalid_format_token"},
        )
        self.assertEqual(response_invalid.status_code, status.HTTP_403_FORBIDDEN)

    def test_catalog_and_rent_lifecycle_via_api(self):
        # Create a user to authenticate
        user = User.objects.create_user(username="apiuser", password="password")
        UserCredit.objects.create(user=user, balance=Decimal("100.00"))
        token = "dev_token_apiuser"

        # 1. Fetch catalog
        response = self.client.get(
            "/api/v1/leases/catalog/",
            headers={"X-API-Token": token},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should return all 5 Nvidia models
        self.assertEqual(len(response.json()), 5)

        # Confirm each model reports 3 available physical instances (seeded count)
        for model in response.json():
            self.assertEqual(model["available_instances_count"], 3)

        # 2. Rent a shared RTX 4090 GPU via API
        rent_payload = {
            "gpu_model_id": str(self.rtx_model.id),
            "is_dedicated": False,
        }
        response_rent = self.client.post(
            "/api/v1/leases/rent/",
            data=rent_payload,
            content_type="application/json",
            headers={"X-API-Token": token},
        )
        self.assertEqual(response_rent.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response_rent.json()["status"], "ACTIVE")

        # Verify lease is correctly created in DB
        lease_id = response_rent.json()["id"]
        lease = RentalLease.objects.get(pk=lease_id)
        self.assertEqual(lease.user, user)
        self.assertEqual(lease.status, RentalLeaseStatus.ACTIVE)
        self.assertFalse(lease.gpu_instance.is_dedicated)

    @patch("billing.services.payment_gateway.httpx.post")
    def test_rent_dedicated_gpu_requires_upfront_payment(self, mock_post):
        # Mock payment gateway response: Success
        mock_response = httpx.Response(status_code=200, json={"status": "succeeded"})
        mock_post.return_value = mock_response

        # Create user
        User.objects.create_user(username="deduser", password="password")
        token = "dev_token_deduser"

        rent_payload = {
            "gpu_model_id": str(self.h100_model.id),
            "is_dedicated": True,
            "card_token": "tok_visa",
        }
        response_rent = self.client.post(
            "/api/v1/leases/rent/",
            data=rent_payload,
            content_type="application/json",
            headers={"X-API-Token": token},
        )
        self.assertEqual(response_rent.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response_rent.json()["status"], "ACTIVE")
        self.assertEqual(Decimal(response_rent.json()["total_billed_amount"]), Decimal("4.76"))

    def test_billing_dashboard_endpoints(self):
        user = User.objects.create_user(username="billuser", password="password")
        UserCredit.objects.create(user=user, balance=Decimal("75.50"))
        token = "dev_token_billuser"

        # Create sample invoices
        Invoice.objects.create(
            user=user,
            lease_id=None,
            amount=Decimal("15.00"),
            status=InvoiceStatus.PAID,
            description="Tier swap fee",
        )

        # 1. Fetch balance API
        response_bal = self.client.get(
            "/api/v1/billing/balance/",
            headers={"X-API-Token": token},
        )
        self.assertEqual(response_bal.status_code, status.HTTP_200_OK)
        self.assertEqual(Decimal(response_bal.json()["balance"]), Decimal("75.50"))

        # 2. Fetch invoices list API
        response_inv = self.client.get(
            "/api/v1/billing/invoices/",
            headers={"X-API-Token": token},
        )
        self.assertEqual(response_inv.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_inv.json()), 1)
        self.assertEqual(Decimal(response_inv.json()[0]["amount"]), Decimal("15.00"))

    @patch("django.tasks.backends.immediate.ImmediateBackend.enqueue")
    def test_freeze_and_unfreeze_account_via_api(self, mock_enqueue):
        user = User.objects.create_user(username="freezeuser", password="password")
        UserCredit.objects.create(user=user, balance=Decimal("100.00"))
        token = "dev_token_freezeuser"

        # 1. Freeze account
        response_freeze = self.client.post(
            "/api/v1/tenants/freeze/",
            data={"keep_dedicated_gpus": False},
            content_type="application/json",
            headers={"X-API-Token": token},
        )
        self.assertEqual(response_freeze.status_code, status.HTTP_200_OK)
        self.assertEqual(response_freeze.json()["status"], "account_frozen")

        # Verify that access to other APIs is now blocked by API Shielding
        response_blocked = self.client.get(
            "/api/v1/leases/catalog/",
            headers={"X-API-Token": token},
        )
        self.assertEqual(response_blocked.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Unfreeze account (should pass through API shielding)
        response_unfreeze = self.client.post(
            "/api/v1/tenants/unfreeze/",
            headers={"X-API-Token": token},
        )
        self.assertEqual(response_unfreeze.status_code, status.HTTP_200_OK)
        self.assertEqual(response_unfreeze.json()["status"], "account_active")

        # Verify access is restored
        response_restored = self.client.get(
            "/api/v1/leases/catalog/",
            headers={"X-API-Token": token},
        )
        self.assertEqual(response_restored.status_code, status.HTTP_200_OK)
