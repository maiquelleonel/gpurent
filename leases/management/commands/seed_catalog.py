from decimal import Decimal

from django.core.management.base import BaseCommand

from leases.models import GPUInstance, GPUInstanceStatus, GPUModel


class Command(BaseCommand):
    help = "Seeds the GPU Models and initial physical GPU Instances."

    def handle(self, *args, **options):
        models_data = [
            {
                "name": "NVIDIA H100 (80GB SXM5)",
                "vram_capacity_gb": 80,
                "price_per_hour": Decimal("4.76"),
            },
            {
                "name": "NVIDIA A100 (80GB PCIe)",
                "vram_capacity_gb": 80,
                "price_per_hour": Decimal("1.88"),
            },
            {
                "name": "NVIDIA A100 (40GB PCIe)",
                "vram_capacity_gb": 40,
                "price_per_hour": Decimal("1.21"),
            },
            {
                "name": "NVIDIA L4 (24GB PCIe)",
                "vram_capacity_gb": 24,
                "price_per_hour": Decimal("0.55"),
            },
            {
                "name": "NVIDIA RTX 4090 (24GB)",
                "vram_capacity_gb": 24,
                "price_per_hour": Decimal("0.44"),
            },
        ]

        for m_data in models_data:
            gpu_model, created = GPUModel.objects.update_or_create(
                name=m_data["name"],
                defaults={
                    "vram_capacity_gb": m_data["vram_capacity_gb"],
                    "price_per_hour": m_data["price_per_hour"],
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created model: {gpu_model.name}"))
            else:
                self.stdout.write(f"Updated/Confirmed model: {gpu_model.name}")

            prefix = gpu_model.name.replace("NVIDIA ", "").replace(" (", "-").replace(")", "").replace(" ", "-")
            for i in range(1, 4):
                serial_number = f"GPU-{prefix}-{i:03d}"
                is_dedicated = i == 3
                gpu_instance, inst_created = GPUInstance.objects.get_or_create(
                    serial_number=serial_number,
                    defaults={
                        "model": gpu_model,
                        "status": GPUInstanceStatus.AVAILABLE,
                        "is_dedicated": is_dedicated,
                    },
                )
                if inst_created:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Created instance: {gpu_instance.serial_number} (Dedicated: {is_dedicated})"
                        )
                    )
                else:
                    self.stdout.write(f"  Confirmed instance: {gpu_instance.serial_number}")

        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully!"))
