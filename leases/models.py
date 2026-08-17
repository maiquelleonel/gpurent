import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class GPUModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=128, unique=True)
    vram_capacity_gb = models.PositiveIntegerField()
    price_per_hour = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = "GPU Model"
        verbose_name_plural = "GPU Models"
        ordering = ["-price_per_hour"]

    def __str__(self) -> str:
        return f"{self.name} — ${self.price_per_hour}/h"


class GPUInstanceStatus(models.TextChoices):
    AVAILABLE = "AVAILABLE", _("Available")
    LEASED = "LEASED", _("Leased")
    MAINTENANCE = "MAINTENANCE", _("Maintenance")


class GPUInstance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    serial_number = models.CharField(max_length=128, unique=True)
    model = models.ForeignKey(
        GPUModel,
        on_delete=models.PROTECT,
        related_name="instances",
    )
    status = models.CharField(
        max_length=16,
        choices=GPUInstanceStatus.choices,
        default=GPUInstanceStatus.AVAILABLE,
    )
    is_dedicated = models.BooleanField(default=False)

    class Meta:
        verbose_name = "GPU Instance"
        verbose_name_plural = "GPU Instances"
        indexes = [
            models.Index(fields=["status", "is_dedicated"]),
        ]

    def __str__(self) -> str:
        return f"{self.model.name} ({self.serial_number}) [{self.status}]"


class RentalLeaseStatus(models.TextChoices):
    PROVISIONING = "PROVISIONING", _("Provisioning")
    ACTIVE = "ACTIVE", _("Active")
    TERMINATING = "TERMINATING", _("Terminating")
    COMPLETED = "COMPLETED", _("Completed")
    SUSPENDED_PAYMENT = "SUSPENDED_PAYMENT", _("Suspended - Payment")


class RentalLease(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="leases",
    )
    gpu_instance = models.ForeignKey(
        GPUInstance,
        on_delete=models.PROTECT,
        related_name="leases",
        null=True,
    )
    status = models.CharField(
        max_length=32,
        choices=RentalLeaseStatus.choices,
        default=RentalLeaseStatus.PROVISIONING,
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    total_billed_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    volume_discount_applied = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal("0.00"),
    )

    class Meta:
        verbose_name = "Rental Lease"
        verbose_name_plural = "Rental Leases"
        indexes = [
            models.Index(fields=["status", "started_at"]),
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self) -> str:
        return f"Lease #{self.pk} — {self.user} ({self.status})"


class MetricSnapshot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    gpu_instance = models.ForeignKey(
        GPUInstance,
        on_delete=models.CASCADE,
        related_name="snapshots",
    )
    vram_used_gb = models.DecimalField(max_digits=5, decimal_places=2)
    compute_load_pct = models.DecimalField(max_digits=5, decimal_places=2)
    temperature_c = models.DecimalField(max_digits=5, decimal_places=2)
    is_thermal_alert = models.BooleanField(default=False)
    timestamp = models.DateTimeField()

    class Meta:
        verbose_name = "Metric Snapshot"
        verbose_name_plural = "Metric Snapshots"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["gpu_instance", "timestamp"]),
        ]

    def __str__(self) -> str:
        return f"Snapshot {self.gpu_instance.serial_number} @ {self.timestamp}"
