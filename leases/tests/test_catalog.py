from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from leases.models import GPUInstance, GPUInstanceStatus, GPUModel


class CatalogTestCase(TestCase):
    def test_seeding_management_command(self):
        GPUInstance.objects.all().delete()
        GPUModel.objects.all().delete()

        self.assertEqual(GPUModel.objects.count(), 0)
        self.assertEqual(GPUInstance.objects.count(), 0)

        # Silence stdout of the seeding management command during tests
        call_command("seed_catalog", stdout=StringIO())

        self.assertEqual(GPUModel.objects.count(), 5)
        self.assertEqual(GPUInstance.objects.count(), 15)

        h100 = GPUModel.objects.get(name="NVIDIA H100 (80GB SXM5)")
        self.assertEqual(h100.vram_capacity_gb, 80)
        self.assertEqual(h100.price_per_hour, Decimal("4.76"))

        a100_80 = GPUModel.objects.get(name="NVIDIA A100 (80GB PCIe)")
        self.assertEqual(a100_80.vram_capacity_gb, 80)
        self.assertEqual(a100_80.price_per_hour, Decimal("1.88"))

        a100_40 = GPUModel.objects.get(name="NVIDIA A100 (40GB PCIe)")
        self.assertEqual(a100_40.vram_capacity_gb, 40)
        self.assertEqual(a100_40.price_per_hour, Decimal("1.21"))

        l4 = GPUModel.objects.get(name="NVIDIA L4 (24GB PCIe)")
        self.assertEqual(l4.vram_capacity_gb, 24)
        self.assertEqual(l4.price_per_hour, Decimal("0.55"))

        rtx = GPUModel.objects.get(name="NVIDIA RTX 4090 (24GB)")
        self.assertEqual(rtx.vram_capacity_gb, 24)
        self.assertEqual(rtx.price_per_hour, Decimal("0.44"))

        instances = GPUInstance.objects.filter(model=h100).order_by("serial_number")
        shared_instances = instances.filter(is_dedicated=False)
        dedicated_instances = instances.filter(is_dedicated=True)

        self.assertEqual(shared_instances.count(), 2)
        self.assertEqual(dedicated_instances.count(), 1)

        for inst in instances:
            self.assertEqual(inst.status, GPUInstanceStatus.AVAILABLE)

    def test_protect_on_delete_constraint(self):
        call_command("seed_catalog", stdout=StringIO())

        gpu_model = GPUModel.objects.first()
        self.assertIsNotNone(gpu_model)

        with self.assertRaises(ProtectedError):
            gpu_model.delete()
