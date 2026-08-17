import logging
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.tasks import task
from django.utils import timezone

from billing.models import Invoice
from users.models import TenantProfile
from users.orchestrators.lifecycle import soft_delete_tenant

logger = logging.getLogger(__name__)
User = get_user_model()


@task(queue_name="emails")
def send_welcome_email(user_id):
    """
    Asynchronously sends a welcome transactional email to a newly registered user,
    providing their name and a mock API Token.
    """
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.error("Failed to send welcome email: User %s does not exist.", user_id)
        return

    # Attempt to retrieve official DRF token key
    from rest_framework.authtoken.models import Token

    try:
        token_key = Token.objects.get(user=user).key
    except Token.DoesNotExist:
        token_key = f"dev_token_{user.username}"

    subject = "Welcome to GPURent!"
    message = (
        f"Hi {user.username},\n\n"
        f"Welcome to the GPURent platform!\n"
        f"Your account is active. To authenticate with our API, use the header:\n"
        f"X-API-Token: {token_key}\n\n"
        f"Best regards,\nThe GPURent Team"
    )
    recipient = user.email or f"{user.username}@example.com"

    send_mail(
        subject=subject,
        message=message,
        from_email="noreply@gpurent.com",
        recipient_list=[recipient],
    )
    logger.info("Sent welcome email to: %s", recipient)


@task(queue_name="emails")
def send_invoice_email(invoice_id):
    """
    Asynchronously sends a transactional billing receipt email to a user when an invoice is issued.
    """
    try:
        invoice = Invoice.objects.select_related("user").get(pk=invoice_id)
    except Invoice.DoesNotExist:
        logger.error("Failed to send invoice email: Invoice %s does not exist.", invoice_id)
        return

    user = invoice.user
    subject = f"GPURent Billing Receipt - Invoice #{invoice.id}"
    message = (
        f"Hi {user.username},\n\n"
        f"A new billing invoice has been issued on your GPURent account:\n\n"
        f"Invoice ID: {invoice.id}\n"
        f"Amount: ${invoice.amount}\n"
        f"Status: {invoice.status}\n"
        f"Description: {invoice.description}\n\n"
        f"Thank you for using GPURent!"
    )
    recipient = user.email or f"{user.username}@example.com"

    send_mail(
        subject=subject,
        message=message,
        from_email="billing@gpurent.com",
        recipient_list=[recipient],
    )
    logger.info("Sent invoice receipt email to: %s", recipient)


@task(queue_name="emails")
def send_freezing_alert_email(user_id):
    """
    Asynchronously sends an account freeze notification email.
    """
    try:
        user = User.objects.select_related("profile").get(pk=user_id)
    except User.DoesNotExist:
        logger.error("Failed to send freeze email: User %s does not exist.", user_id)
        return

    profile = user.profile
    policy = "Preserve & Hold (10%/week retention fee)" if profile.keep_dedicated_gpus else "Release to pool"

    subject = "Your GPURent Account is Frozen"
    message = (
        f"Hi {user.username},\n\n"
        f"This email confirms that your GPURent account has been successfully frozen.\n"
        f"Standard hourly GPU rental costs are paused. Your account reactivation policy is set to:\n"
        f"-> {policy}\n\n"
        f"Important: If your account remains frozen for more than 30 days, "
        f"it will be automatically soft-deleted in accordance with our system terms."
    )
    recipient = user.email or f"{user.username}@example.com"

    send_mail(
        subject=subject,
        message=message,
        from_email="support@gpurent.com",
        recipient_list=[recipient],
    )
    logger.info("Sent freeze alert email to: %s", recipient)


@task(queue_name="account_lifecycle")
def schedule_freeze_expiry_check(user_id):
    """
    Asynchronous task scheduled to run 30 days after account freeze.
    Checks if account is still frozen. If so, triggers soft-deletion and emails confirmation.
    """
    try:
        profile = TenantProfile.objects.select_related("user").get(user_id=user_id)
    except TenantProfile.DoesNotExist:
        logger.error("Failed to run freeze expiry check: Profile for user %s does not exist.", user_id)
        return

    # If the user has already unfrozen their account (freezed_at is None) or is deleted, die silently.
    if profile.freezed_at is None or profile.deleted_at is not None:
        logger.info("Freeze expiry check skipped: Account for user %s is not currently frozen.", profile.user.username)
        return

    # Trigger soft-delete
    user = profile.user
    logger.warning("🚨 30-day freezing limit reached! Soft-deleting tenant account for %s.", user.username)

    try:
        soft_delete_tenant(user.id)

        # Send deletion confirmation email
        subject = "Your GPURent Account has been Closed"
        message = (
            f"Hi {user.username},\n\n"
            f"Your GPURent account has been automatically soft-deleted because it was "
            f"frozen for more than 30 consecutive days without reactivation.\n\n"
            f"If you wish to return, please contact support to restore your account data.\n\n"
            f"Best regards,\nThe GPURent Team"
        )
        recipient = user.email or f"{user.username}@example.com"

        send_mail(
            subject=subject,
            message=message,
            from_email="support@gpurent.com",
            recipient_list=[recipient],
        )
        logger.info("Sent freeze expiry deletion confirmation email to: %s", recipient)

    except Exception:
        logger.exception("Failed to execute freeze-expiry soft-deletion for user %s", user.id)


@task(queue_name="billing")
def process_webhook_refund_task(invoice_id):
    """
    Asynchronously processes a refund webhook event:
    Marks corresponding Invoice as REFUNDED and refunds pre-paid balances.
    Creates a SystemAlert to notify admins.
    """
    from django.db import transaction

    from billing.models import Invoice, InvoiceStatus, UserCredit
    from leases.models import SystemAlert

    with transaction.atomic():
        try:
            invoice = Invoice.objects.select_for_update().get(pk=invoice_id)
        except Invoice.DoesNotExist:
            logger.error("Failed to process refund task: Invoice %s does not exist.", invoice_id)
            return

        if invoice.status == InvoiceStatus.REFUNDED:
            logger.info("Invoice %s is already refunded.", invoice_id)
            return

        # Update status and description
        invoice.status = InvoiceStatus.REFUNDED
        invoice.description += " (Refunded via Stripe Webhook)"
        invoice.save(update_fields=["status", "description"])

        # Refund prepaid balance
        credit, _ = UserCredit.objects.select_for_update().get_or_create(user=invoice.user)
        credit.balance = (credit.balance + invoice.amount).quantize(Decimal("0.01"))
        credit.save(update_fields=["balance"])

        # Trigger real-time SystemAlert for admin dashboard
        SystemAlert.objects.create(
            alert_type="billing",
            message=f"Refund processed for Invoice #{invoice.id} of user {invoice.user.username}: ${invoice.amount}",
        )
        logger.info("Successfully processed async refund for invoice %s.", invoice_id)


@task(queue_name="billing")
def process_webhook_payment_failed_task(user_id):
    """
    Asynchronously processes a payment failure webhook event:
    Immediately suspends all active leases and releases cards.
    Creates a SystemAlert to notify admins.
    """
    from django.db import transaction

    from leases.models import GPUInstanceStatus, RentalLease, RentalLeaseStatus, SystemAlert

    with transaction.atomic():
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            logger.error("Failed to process payment failed task: User %s does not exist.", user_id)
            return

        active_leases = RentalLease.objects.filter(user=user, status=RentalLeaseStatus.ACTIVE)
        now = timezone.now()

        for lease in active_leases:
            # Suspend the lease and release the card
            lease.status = RentalLeaseStatus.SUSPENDED_PAYMENT
            lease.ended_at = now
            lease.save(update_fields=["status", "ended_at"])

            if lease.gpu_instance:
                gpu_instance = lease.gpu_instance
                gpu_instance.status = GPUInstanceStatus.AVAILABLE
                gpu_instance.save(update_fields=["status"])

        # Trigger real-time SystemAlert for admin dashboard
        SystemAlert.objects.create(
            alert_type="billing",
            message=f"Payment failed webhook triggered: Suspended all active leases for user {user.username}.",
        )
        logger.info("Successfully processed async payment failure suspension for user %s.", user_id)
