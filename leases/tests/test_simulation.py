from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from leases.models import GPUInstance, GPUInstanceStatus, GPUModel, MetricSnapshot, RentalLease, RentalLeaseStatus
from leases.simulation.worker import MetricsSimulatorWorker

User = get_user_model()


class SimulationTestCase(TestCase):
    def setUp(self):
        # Create a test user
        self.user = User.objects.create_user(username="testuser", password="secretpassword")

        # Create GPU Models
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

        # Create GPU Instances
        self.h100_instance = GPUInstance.objects.create(
            serial_number="GPU-H100-001",
            model=self.h100_model,
            status=GPUInstanceStatus.LEASED,
            is_dedicated=True,
        )
        self.rtx_instance = GPUInstance.objects.create(
            serial_number="GPU-RTX-001",
            model=self.rtx_model,
            status=GPUInstanceStatus.AVAILABLE,
            is_dedicated=False,
        )

        # Create an ACTIVE Lease
        self.active_lease = RentalLease.objects.create(
            user=self.user,
            gpu_instance=self.h100_instance,
            status=RentalLeaseStatus.ACTIVE,
            started_at=timezone.now(),
        )

        # Create a non-ACTIVE (PROVISIONING) Lease
        self.provisioning_lease = RentalLease.objects.create(
            user=self.user,
            gpu_instance=self.rtx_instance,
            status=RentalLeaseStatus.PROVISIONING,
            started_at=timezone.now(),
        )

    def test_simulation_tick_only_selects_active_leases(self):
        self.assertEqual(MetricSnapshot.objects.count(), 0)

        # Instantiate worker and execute tick
        worker = MetricsSimulatorWorker()
        simulated_count = worker.tick()

        # Check only the 1 active lease was simulated
        self.assertEqual(simulated_count, 1)
        self.assertEqual(MetricSnapshot.objects.count(), 1)

        # Assert fields are within expected bounds
        snapshot = MetricSnapshot.objects.first()
        self.assertEqual(snapshot.gpu_instance, self.h100_instance)

        # VRAM capacity of H100 is 80GB. Metric fluctuations must be 40% to 95%.
        # 80 * 0.40 = 32.0GB and 80 * 0.95 = 76.0GB
        self.assertTrue(Decimal("32.0") <= snapshot.vram_used_gb <= Decimal("76.0"))

        # Compute load must be 0% to 100%
        self.assertTrue(Decimal("0.0") <= snapshot.compute_load_pct <= Decimal("100.0"))

        # Normal temperature must be 65C to 85C (with a potential high anomalous spike which is also handled)
        self.assertTrue(Decimal("65.0") <= snapshot.temperature_c <= Decimal("98.0"))

        # Check alert flag consistency
        if snapshot.temperature_c > Decimal("90.0"):
            self.assertTrue(snapshot.is_thermal_alert)
        else:
            self.assertFalse(snapshot.is_thermal_alert)

    def test_thermal_watchdog_alert_triggered(self):
        worker = MetricsSimulatorWorker()

        # Force a safe temperature (80.0C)
        snapshot_safe = worker.generate_metrics(self.active_lease, force_temp=Decimal("80.0"))
        self.assertEqual(snapshot_safe.temperature_c, Decimal("80.0"))
        self.assertFalse(snapshot_safe.is_thermal_alert)

        # Force a high temperature (92.5C) representing a system anomaly
        snapshot_alert = worker.generate_metrics(self.active_lease, force_temp=Decimal("92.5"))
        self.assertEqual(snapshot_alert.temperature_c, Decimal("92.5"))
        self.assertTrue(snapshot_alert.is_thermal_alert)

    def test_active_lease_without_gpu_raises_error(self):
        # Create an active lease without a physical GPU instance (edge case)
        invalid_lease = RentalLease.objects.create(
            user=self.user,
            gpu_instance=None,
            status=RentalLeaseStatus.ACTIVE,
            started_at=timezone.now(),
        )

        worker = MetricsSimulatorWorker()
        with self.assertRaises(ValueError):
            worker.generate_metrics(invalid_lease)
