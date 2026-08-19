import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserCredit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="credit")
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    frozen_prepaid_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    starting_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    low_credit_alert_sent = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("User Credit")
        verbose_name_plural = _("User Credits")

    def __str__(self) -> str:
        return f"{self.user.username} - {self.balance}"

    def save(self, *args, **kwargs):
        if self._state.adding:
            if self.starting_balance == Decimal("0.00"):
                self.starting_balance = self.balance
        else:
            try:
                orig = UserCredit.objects.get(pk=self.pk)
                if self.balance > orig.balance:
                    self.starting_balance = self.balance
                    self.low_credit_alert_sent = False
            except UserCredit.DoesNotExist:
                pass
        super().save(*args, **kwargs)


class InvoiceStatus(models.TextChoices):
    UNPAID = "UNPAID", _("Unpaid")
    PAID = "PAID", _("Paid")
    FAILED = "FAILED", _("Failed")
    REFUNDED = "REFUNDED", _("Refunded")


class PlanType(models.TextChoices):
    PREPAID = "PREPAID", _("Prepaid")
    POSTPAID = "POSTPAID", _("Postpaid")


class ClientUsageCycle(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="usage_cycles")
    plan_type = models.CharField(max_length=16, choices=PlanType.choices)
    gpu = models.CharField(max_length=128)
    hours_consumed = models.DecimalField(max_digits=10, decimal_places=4, default=Decimal("0.0000"))
    total_consumption = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total_credits = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    cycle_started_at = models.DateTimeField(default=timezone.now)
    cycle_ended_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Client Usage Cycle")
        verbose_name_plural = _("Client Usage Cycles")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["client", "is_active"]),
        ]

    def __str__(self) -> str:
        cycle_status = "Active" if self.is_active else f"Ended at {self.cycle_ended_at}"
        return f"{self.client.username} | {self.plan_type} | {self.gpu} ({cycle_status})"


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


@receiver(post_save, sender=Invoice)
def trigger_invoice_email(sender, instance, created, **kwargs):
    """
    Signal receiver that automatically queues a transactional billing email
    upon creation of any Invoice.
    """
    if created:
        from users.tasks import send_invoice_email

        send_invoice_email.enqueue(invoice_id=str(instance.id))

        # Trigger real-time SystemAlert for admin dashboard
        from leases.models import SystemAlert

        SystemAlert.objects.create(
            alert_type="billing",
            message=f"Invoice #{instance.id} issued for user {instance.user.username}: ${instance.amount}",
        )
