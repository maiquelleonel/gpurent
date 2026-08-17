import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserCredit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="credit")
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("User Credit")
        verbose_name_plural = _("User Credits")

    def __str__(self) -> str:
        return f"{self.user.username} - {self.balance}"


class InvoiceStatus(models.TextChoices):
    UNPAID = "UNPAID", _("Unpaid")
    PAID = "PAID", _("Paid")
    FAILED = "FAILED", _("Failed")


class Invoice(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="invoices")
    lease_id = models.UUIDField(db_index=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=16, choices=InvoiceStatus.choices, default=InvoiceStatus.UNPAID)
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Invoice")
        verbose_name_plural = _("Invoices")
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Invoice {self.pk} - {self.amount} ({self.status})"
