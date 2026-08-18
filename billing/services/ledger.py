import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from billing.models import Invoice, InvoiceStatus, UserCredit
from leases.models import GPUModel, RentalLease, RentalLeaseStatus
from leases.utils.time_scale import get_simulated_duration

logger = logging.getLogger(__name__)


def get_effective_hourly_rate(user, model: GPUModel) -> tuple[Decimal, bool]:
    """
    Calculates the effective hourly rate for a user renting a GPUModel.
    Applies a 10% volume discount if the user has more than 5 active leases of
    the exact same GPU model simultaneously.
    Returns (rate, discount_applied).
    """
    active_count = RentalLease.objects.filter(
        user=user,
        status=RentalLeaseStatus.ACTIVE,
        gpu_instance__model=model,
    ).count()

    base_price = model.price_per_hour
    if active_count > 5:
        discounted_price = (base_price * Decimal("0.90")).quantize(Decimal("0.0001"))
        return discounted_price, True
    return base_price, False


def calculate_accrued_cost(started_at, ended_at, hourly_rate: Decimal) -> Decimal:
    """
    Calculates the cost based on timezone-aware start/end times, hourly rate,
    and leases.utils.time_scale.get_simulated_duration.
    """
    simulated_duration = get_simulated_duration(started_at, ended_at)
    simulated_hours = Decimal(simulated_duration.total_seconds()) / Decimal("3600.0")
    cost = (simulated_hours * hourly_rate).quantize(Decimal("0.01"))
    return cost


def _check_and_trigger_low_credit_warning(credit):
    """
    Checks if credit balance has depleted by 80% or more compared to starting_balance.
    If so, and warning not sent yet, enqueues the send_low_credit_warning_email task.
    """
    if credit.starting_balance > Decimal("0.00") and not credit.low_credit_alert_sent:
        # Check if balance <= 20% of starting_balance
        threshold = (credit.starting_balance * Decimal("0.20")).quantize(Decimal("0.01"))
        if credit.balance <= threshold:
            from billing.tasks import send_low_credit_warning_email

            send_low_credit_warning_email.enqueue(user_id=str(credit.user.id))
            credit.low_credit_alert_sent = True
            credit.save(update_fields=["low_credit_alert_sent"])


def invoice_lease_usage(lease: RentalLease, ended_at=None) -> Decimal:
    """
    Invoices the active usage of a lease from its started_at timestamp up to ended_at (default: now).
    Deducts from pre-paid UserCredit if the GPU model is RTX 4090 or L4.
    Otherwise, creates an UNPAID post-paid invoice.
    Returns the invoiced amount.
    """
    if not lease.gpu_instance:
        return Decimal("0.00")

    if ended_at is None:
        ended_at = timezone.now()

    model = lease.gpu_instance.model
    effective_rate, discount_applied = get_effective_hourly_rate(lease.user, model)
    amount = calculate_accrued_cost(lease.started_at, ended_at, effective_rate)

    if amount <= Decimal("0.00"):
        return Decimal("0.00")

    is_prepaid = model.name.startswith("NVIDIA RTX") or model.name.startswith("NVIDIA L4")

    description = f"Usage invoice for {model.name} from {lease.started_at} to {ended_at}."
    if discount_applied:
        description += " (10% Volume Discount Applied)"

    if not is_prepaid:
        with transaction.atomic():
            try:
                credit = UserCredit.objects.select_for_update().get(user=lease.user)
                if credit.frozen_prepaid_balance > Decimal("0.00"):
                    abatement = min(amount, credit.frozen_prepaid_balance)
                    amount = (amount - abatement).quantize(Decimal("0.01"))
                    credit.frozen_prepaid_balance = (credit.frozen_prepaid_balance - abatement).quantize(
                        Decimal("0.01")
                    )
                    credit.save(update_fields=["frozen_prepaid_balance"])
                    description += f" (Abated ${abatement} from frozen prepaid balance)"
            except UserCredit.DoesNotExist:
                pass

    # Determine default status of the invoice
    if is_prepaid:
        status = InvoiceStatus.PAID
    else:
        status = InvoiceStatus.PAID if amount == Decimal("0.00") else InvoiceStatus.UNPAID

    Invoice.objects.create(
        user=lease.user,
        lease_id=lease.id,
        amount=amount,
        status=status,
        description=description,
    )

    if is_prepaid:
        with transaction.atomic():
            credit, _ = UserCredit.objects.select_for_update().get_or_create(user=lease.user)
            credit.balance = (credit.balance - amount).quantize(Decimal("0.01"))
            credit.save(update_fields=["balance"])
            _check_and_trigger_low_credit_warning(credit)

    # Update lease billed amount
    current_billed = Decimal(str(lease.total_billed_amount))
    lease.total_billed_amount = (current_billed + amount).quantize(Decimal("0.01"))
    if discount_applied:
        # Let's save that volume discount was applied
        lease.volume_discount_applied = Decimal("10.00")
    lease.save(update_fields=["total_billed_amount", "volume_discount_applied"])

    logger.info(
        "Invoiced lease %s for usage: %s (%s). Prepaid=%s",
        lease.id,
        amount,
        status,
        is_prepaid,
    )
    return amount


def invoice_flat_fee(user, lease_id, amount: Decimal, description: str, is_prepaid: bool) -> Invoice:
    """
    Invoices a flat fee (like upgrade charges) to the user.
    Deducts from pre-paid UserCredit if the user has prepaid credits (balance > 0) or is_prepaid is True.
    """
    try:
        credit = UserCredit.objects.get(user=user)
        has_credit = credit.balance > Decimal("0.00")
    except UserCredit.DoesNotExist:
        has_credit = False

    should_pay_from_credit = is_prepaid or has_credit
    status = InvoiceStatus.PAID if should_pay_from_credit else InvoiceStatus.UNPAID

    invoice = Invoice.objects.create(
        user=user,
        lease_id=lease_id,
        amount=amount,
        status=status,
        description=description,
    )

    if should_pay_from_credit:
        with transaction.atomic():
            credit, _ = UserCredit.objects.select_for_update().get_or_create(user=user)
            credit.balance = (credit.balance - amount).quantize(Decimal("0.01"))
            credit.save(update_fields=["balance"])
            _check_and_trigger_low_credit_warning(credit)

    logger.info("Invoiced flat fee to user %s: %s (%s)", user.username, amount, status)
    return invoice
