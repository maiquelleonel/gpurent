import logging

from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.tasks import task

logger = logging.getLogger(__name__)
User = get_user_model()


@task(queue_name="emails")
def send_low_credit_warning_email(user_id):
    """
    Asynchronously sends a warning email to a prepaid user when they have consumed
    80% of their starting credits.
    """
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.error("Failed to send low credit warning: User %s does not exist.", user_id)
        return

    subject = "Low Prepaid Credit Warning"
    message = (
        f"Hi {user.username},\n\n"
        f"This is a warning that you have consumed 80% or more of your starting prepaid credits.\n"
        f"Please top up your balance soon to avoid service interruption.\n\n"
        f"Best regards,\nThe GPURent Team"
    )
    recipient = user.email or f"{user.username}@example.com"

    send_mail(
        subject=subject,
        message=message,
        from_email="billing@gpurent.com",
        recipient_list=[recipient],
    )
    logger.info("Sent low credit warning email to: %s", recipient)


@task(queue_name="emails")
def send_invoice_email(user_id, invoice_id, is_payment_receipt=False):
    """
    Asynchronously sends an invoice or payment receipt email to a user.
    """
    try:
        user = User.objects.get(pk=user_id)
        from billing.models import Invoice

        invoice = Invoice.objects.get(pk=invoice_id)
    except (User.DoesNotExist, Exception) as e:
        logger.error("Failed to send invoice email: %s", e)
        return

    if is_payment_receipt:
        subject = f"Receipt for Invoice #{str(invoice.id)[:8]}"
        message = (
            f"Hi {user.username},\n\n"
            f"Thank you for your payment of ${invoice.amount} for: {invoice.description}.\n"
            f"Status: PAID.\n\n"
            f"Best regards,\nThe GPURent Team"
        )
    else:
        subject = f"New Invoice Generated #{str(invoice.id)[:8]}"
        message = (
            f"Hi {user.username},\n\n"
            f"A new invoice of ${invoice.amount} has been issued for your recent cycle: {invoice.description}.\n"
            f"Please settle this invoice within 5 days to keep your services active.\n\n"
            f"Best regards,\nThe GPURent Team"
        )

    recipient = user.email or f"{user.username}@example.com"
    send_mail(
        subject=subject,
        message=message,
        from_email="billing@gpurent.com",
        recipient_list=[recipient],
    )
    logger.info("Sent invoice email (receipt=%s) to: %s", is_payment_receipt, recipient)
