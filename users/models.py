import uuid

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TokenUsage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    api_token = models.CharField(max_length=255, db_index=True)
    endpoint = models.CharField(max_length=255)
    request_timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    response_status = models.PositiveIntegerField()

    class Meta:
        verbose_name = _("Token Usage")
        verbose_name_plural = _("Token Usages")
        ordering = ["-request_timestamp"]

    def __str__(self) -> str:
        return f"{self.api_token} - {self.endpoint} ({self.response_status})"


class TenantProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    freezed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    keep_dedicated_gpus = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("Tenant Profile")
        verbose_name_plural = _("Tenant Profiles")

    def __str__(self) -> str:
        return f"Profile for {self.user.username}"

    def can_delete(self) -> bool:
        """
        Returns True if the tenant is eligible for deletion (no outstanding unpaid invoices
        and non-negative prepaid credit balance).
        """
        from billing.models import Invoice, InvoiceStatus, UserCredit

        # Check for outstanding unpaid invoices
        unpaid_exists = Invoice.objects.filter(user=self.user, status=InvoiceStatus.UNPAID).exists()
        if unpaid_exists:
            return False

        # Check for negative prepaid credit balance
        try:
            credit = UserCredit.objects.get(user=self.user)
            if credit.balance < 0:
                return False
        except UserCredit.DoesNotExist:
            pass

        return True


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_tenant_profile(sender, instance, created, **kwargs):
    """
    Signal receiver that automatically creates a TenantProfile and an official DRF auth Token
    whenever a new User is created.
    """
    if created:
        TenantProfile.objects.create(user=instance)

        # Generate official DRF Authentication Token
        from rest_framework.authtoken.models import Token

        Token.objects.create(user=instance)

        # Trigger async welcome email (Django 6.0 task backend-agnostic)
        from users.tasks import send_welcome_email

        send_welcome_email.enqueue(user_id=str(instance.id))
