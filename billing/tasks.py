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
