from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from leases.models import SystemAlert

User = get_user_model()


class LiveAlertsTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        # Create normal user and superuser (staff member)
        self.normal_user = User.objects.create_user(username="normal", password="password")
        self.staff_user = User.objects.create_superuser(
            username="admin_staff", email="admin@example.com", password="password"
        )

    def test_anonymous_and_non_staff_users_are_redirected(self):
        # 1. Anonymous request to alerts endpoint redirects to admin login (302)
        response_anon = self.client.get("/admin/api/live-alerts/")
        self.assertEqual(response_anon.status_code, 302)

        # 2. Non-staff authenticated user redirects as well
        self.client.force_login(self.normal_user)
        response_non_staff = self.client.get("/admin/api/live-alerts/")
        self.assertEqual(response_non_staff.status_code, 302)

    def test_live_alerts_polling_renders_toasts_and_marks_as_read(self):
        # Create unread System Alerts
        alert1 = SystemAlert.objects.create(
            alert_type="signup",
            message="New tenant registered: testuser",
        )
        alert2 = SystemAlert.objects.create(
            alert_type="billing",
            message="Invoice #123 generated: $15.00",
        )

        # Log in staff member
        self.client.force_login(self.staff_user)

        # 1. First poll: retrieves both unread alerts
        response = self.client.get("/admin/api/live-alerts/")
        self.assertEqual(response.status_code, 200)

        # Assert response HTML contains messages and appropriate Bootstrap colors
        html_content = response.content.decode()
        self.assertIn("New tenant registered: testuser", html_content)
        self.assertIn("Invoice #123 generated: $15.00", html_content)
        self.assertIn("django-admin-alert", html_content)
        self.assertIn("#fef9c3", html_content)  # default warm yellow bg for signup alert
        self.assertIn("#dcfce7", html_content)  # green bg for billing alert
        self.assertIn("setTimeout", html_content)  # auto-destruction script

        # Verify that both alerts are now marked as read in database
        alert1.refresh_from_db()
        alert2.refresh_from_db()
        self.assertTrue(alert1.is_read)
        self.assertTrue(alert2.is_read)

        # 2. Second poll: since both are read, response should be empty
        response_empty = self.client.get("/admin/api/live-alerts/")
        self.assertEqual(response_empty.status_code, 200)
        self.assertEqual(response_empty.content.decode(), "")

    def test_admin_live_dashboard_endpoint(self):
        from decimal import Decimal

        from billing.models import ClientUsageCycle, PlanType, UserCredit

        UserCredit.objects.create(user=self.normal_user, balance=Decimal("45.00"))
        ClientUsageCycle.objects.create(
            client=self.normal_user,
            plan_type=PlanType.PREPAID,
            gpu="NVIDIA RTX 4090 (24GB)",
            hours_consumed=Decimal("2.5000"),
            total_consumption=Decimal("1.10"),
            total_credits=Decimal("50.00"),
            is_active=True,
        )

        # Anonymous gets redirected
        response_anon = self.client.get("/admin/api/live-dashboard/")
        self.assertEqual(response_anon.status_code, 302)

        # Staff user gets live HTML fragments
        self.client.force_login(self.staff_user)
        response = self.client.get("/admin/api/live-dashboard/")
        self.assertEqual(response.status_code, 200)

        html = response.content.decode()
        self.assertIn("Live Real-Time Telemetry & Billing Dashboard", html)
        self.assertIn("Client Balance Counters", html)
        self.assertIn("Active GPU Compute & Hardware Telemetry", html)
        self.assertIn("Client Consumption Cycles", html)
        self.assertIn("$45.00", html)
        self.assertIn("2.5000h", html)
        self.assertIn("NVIDIA RTX 4090 (24GB)", html)
        self.assertIn('data-preserve-scroll="true"', html)

    def test_thermal_alert_creates_system_alert(self):
        from decimal import Decimal

        from django.utils import timezone

        from leases.models import GPUInstance, GPUInstanceStatus, GPUModel, RentalLease, RentalLeaseStatus
        from leases.simulation.worker import MetricsSimulatorWorker

        model, _ = GPUModel.objects.get_or_create(
            name="NVIDIA H100 (80GB SXM5)",
            defaults={"vram_capacity_gb": 80, "price_per_hour": Decimal("4.76")},
        )
        gpu = GPUInstance.objects.create(serial_number="GPU-HOT-001", model=model, status=GPUInstanceStatus.LEASED)
        lease = RentalLease.objects.create(
            user=self.normal_user,
            gpu_instance=gpu,
            status=RentalLeaseStatus.ACTIVE,
            started_at=timezone.now(),
        )

        worker = MetricsSimulatorWorker()
        worker.generate_metrics(lease, force_temp=Decimal("94.50"))

        alert = SystemAlert.objects.filter(alert_type="hardware").first()
        self.assertIsNotNone(alert)
        self.assertIn("THERMAL ALERT", alert.message)
        self.assertIn("94.50", alert.message)

    def test_prepaid_depletion_creates_system_alert(self):
        from decimal import Decimal

        from django.utils import timezone

        from billing.models import UserCredit
        from leases.models import GPUInstance, GPUInstanceStatus, GPUModel, RentalLease, RentalLeaseStatus
        from leases.simulation.worker import MetricsSimulatorWorker

        model, _ = GPUModel.objects.get_or_create(
            name="NVIDIA RTX 4090 (24GB)",
            defaults={"vram_capacity_gb": 24, "price_per_hour": Decimal("0.44")},
        )
        gpu = GPUInstance.objects.create(serial_number="GPU-DEP-001", model=model, status=GPUInstanceStatus.LEASED)
        RentalLease.objects.create(
            user=self.normal_user,
            gpu_instance=gpu,
            status=RentalLeaseStatus.ACTIVE,
            started_at=timezone.now() - timezone.timedelta(minutes=5),
        )
        UserCredit.objects.create(user=self.normal_user, balance=Decimal("0.05"))

        worker = MetricsSimulatorWorker()
        worker.tick()

        alert = SystemAlert.objects.filter(alert_type="billing", message__contains="Prepaid lease suspended").first()
        self.assertIsNotNone(alert)
        self.assertIn(self.normal_user.username, alert.message)

    def test_admin_index_renders_three_column_layout_and_scroll_script(self):
        self.client.force_login(self.staff_user)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)

        html = response.content.decode()
        self.assertIn("dashboard-3col-container", html)
        self.assertIn("dashboard-col-entities", html)
        self.assertIn("dashboard-col-actions", html)
        self.assertIn("dashboard-col-telemetry", html)
        self.assertIn("savedScrolls", html)

    def test_admin_live_dashboard_filters_inactive_cycles(self):
        from decimal import Decimal

        from django.utils import timezone

        from billing.models import ClientUsageCycle, PlanType

        # Create active and inactive cycles
        ClientUsageCycle.objects.create(
            client=self.normal_user,
            plan_type=PlanType.PREPAID,
            gpu="NVIDIA RTX 4090 (24GB)",
            hours_consumed=Decimal("1.2345"),
            total_consumption=Decimal("0.54"),
            total_credits=Decimal("50.00"),
            is_active=True,
        )
        ClientUsageCycle.objects.create(
            client=self.normal_user,
            plan_type=PlanType.POSTPAID,
            gpu="NVIDIA H100 (80GB SXM5)",
            hours_consumed=Decimal("720.0000"),
            total_consumption=Decimal("3427.20"),
            total_credits=Decimal("0.00"),
            is_active=False,
            cycle_ended_at=timezone.now(),
        )

        self.client.force_login(self.staff_user)
        response = self.client.get("/admin/api/live-dashboard/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()

        self.assertIn("1.2345h", html)
        self.assertNotIn("720.0000h", html)

    def test_auto_provision_gpu_creates_instance_and_system_alert(self):
        from decimal import Decimal

        from leases.models import GPUInstanceStatus, GPUModel
        from leases.services.fleet_provisioning import auto_provision_gpu

        GPUModel.objects.get_or_create(
            name="NVIDIA RTX 4090 (24GB)",
            defaults={"vram_capacity_gb": 24, "price_per_hour": Decimal("0.44")},
        )

        instance = auto_provision_gpu(model_name="RTX 4090")
        self.assertEqual(instance.status, GPUInstanceStatus.AVAILABLE)
        self.assertIn("RTX", instance.serial_number)

        alert = SystemAlert.objects.filter(alert_type="provisioning").first()
        self.assertIsNotNone(alert)
        self.assertIn("Nova GPU provisionada", alert.message)
        self.assertIn(instance.serial_number, alert.message)

    def test_settle_postpaid_invoice_flow(self):
        from decimal import Decimal

        from billing.models import Invoice, InvoiceStatus
        from billing.services.ledger import settle_postpaid_invoice

        invoice = Invoice.objects.create(
            user=self.normal_user,
            amount=Decimal("150.00"),
            status=InvoiceStatus.UNPAID,
            description="30-Day Postpaid Usage Invoice",
        )

        settled = settle_postpaid_invoice(invoice.id)
        self.assertEqual(settled.status, InvoiceStatus.PAID)

        alert = SystemAlert.objects.filter(
            alert_type="billing",
            message__contains="Fatura pós-paga de $150.00 paga com sucesso",
        ).first()
        self.assertIsNotNone(alert)

    def test_admin_live_alerts_renders_provisioning_toast(self):
        SystemAlert.objects.create(
            alert_type="provisioning",
            message="🚀 Nova GPU provisionada e pronta para aluguel: NVIDIA H100 (Serial: GPU-H100-TEST01)",
        )

        self.client.force_login(self.staff_user)
        response = self.client.get("/admin/api/live-alerts/")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()

        self.assertIn("FLEET PROVISIONED", html)
        self.assertIn("GPU-H100-TEST01", html)

    def test_postpaid_cycle_closing_and_autosettlement_in_worker_tick(self):
        from decimal import Decimal

        from django.utils import timezone

        from billing.models import ClientUsageCycle, Invoice, InvoiceStatus, PlanType
        from leases.models import GPUInstance, GPUInstanceStatus, GPUModel, RentalLease, RentalLeaseStatus
        from leases.simulation.worker import MetricsSimulatorWorker

        h100_model, _ = GPUModel.objects.get_or_create(
            name="NVIDIA H100 (80GB SXM5)",
            defaults={"vram_capacity_gb": 80, "price_per_hour": Decimal("4.76")},
        )
        gpu = GPUInstance.objects.create(
            serial_number="GPU-H100-CYCLE-AUTO",
            model=h100_model,
            status=GPUInstanceStatus.LEASED,
        )
        lease = RentalLease.objects.create(
            user=self.normal_user,
            gpu_instance=gpu,
            status=RentalLeaseStatus.ACTIVE,
            started_at=timezone.now() - timezone.timedelta(minutes=1),
        )

        # 1. Start with cycle near 30 days
        cycle = ClientUsageCycle.objects.create(
            client=self.normal_user,
            plan_type=PlanType.POSTPAID,
            gpu=h100_model.name,
            hours_consumed=Decimal("720.0000"),
            total_consumption=Decimal("3427.20"),
            total_credits=Decimal("0.00"),
            cycle_started_at=timezone.now() - timezone.timedelta(minutes=372),
            cycle_ended_at=None,
            is_active=True,
        )

        worker = MetricsSimulatorWorker()

        # Tick 1: Closes 30-day cycle, generates UNPAID invoice, creates new cycle
        worker.tick()
        cycle.refresh_from_db()
        self.assertFalse(cycle.is_active)

        invoice = Invoice.objects.filter(lease_id=lease.id, status=InvoiceStatus.UNPAID).first()
        self.assertIsNotNone(invoice)

        # Simulate time advancing for Tick 2
        invoice.created_at = timezone.now() - timezone.timedelta(seconds=5)
        invoice.save(update_fields=["created_at"])

        # Tick 2: Client pays postpaid invoice -> transitions to PAID & emits alert
        worker.tick()
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, InvoiceStatus.PAID)

        paid_alert = SystemAlert.objects.filter(
            alert_type="billing",
            message__contains="paga com sucesso",
        ).first()
        self.assertIsNotNone(paid_alert)
