import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from billing.models import ClientUsageCycle, Invoice, InvoiceStatus, PlanType, UserCredit
from leases.models import GPUModel, RentalLease, RentalLeaseStatus
from leases.utils.time_scale import get_simulated_duration

logger = logging.getLogger(__name__)


def is_prepaid_model(model: GPUModel) -> bool:
    """
    Checks if a GPU model belongs to the pre-paid tier (RTX 4090 or L4).
    """
    name = model.name.upper()
    return "RTX" in name or "L4" in name


def is_postpaid_model(model: GPUModel) -> bool:
    """
    Checks if a GPU model belongs to the post-paid tier (A100 or H100).
    """
    name = model.name.upper()
    return "A100" in name or "H100" in name


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
        threshold = (credit.starting_balance * Decimal("0.20")).quantize(Decimal("0.01"))
        if credit.balance <= threshold:
            from billing.tasks import send_low_credit_warning_email

            send_low_credit_warning_email.enqueue(user_id=str(credit.user.id))
            credit.low_credit_alert_sent = True
            credit.save(update_fields=["low_credit_alert_sent"])

            # Trigger real-time SystemAlert for admin dashboard
            try:
                from leases.models import SystemAlert

                SystemAlert.objects.create(
                    alert_type="billing",
                    message=(
                        f"⚠️ Low credit alert: User {credit.user.username} has depleted 80% of prepaid balance "
                        f"(Balance: ${credit.balance})"
                    ),
                )
            except Exception:
                logger.exception("Failed to create low credit SystemAlert")


def get_or_create_active_cycle(user, model: GPUModel, is_prepaid: bool) -> ClientUsageCycle:
    """
    Fetches the active ClientUsageCycle for a user, or initializes a new one.
    """
    cycle = ClientUsageCycle.objects.filter(client=user, is_active=True).first()
    if not cycle:
        plan_type = PlanType.PREPAID if is_prepaid else PlanType.POSTPAID
        initial_credits = Decimal("0.00")
        if is_prepaid:
            credit = UserCredit.objects.filter(user=user).first()
            if credit:
                initial_credits = credit.balance

        cycle = ClientUsageCycle.objects.create(
            client=user,
            plan_type=plan_type,
            gpu=model.name,
            hours_consumed=Decimal("0.0000"),
            total_consumption=Decimal("0.00"),
            total_credits=initial_credits,
            cycle_started_at=timezone.now(),
            cycle_ended_at=None,
            is_active=True,
        )
    return cycle


def record_fractional_usage(lease: RentalLease, ended_at=None) -> tuple[Decimal, bool]:
    """
    Records real-time fractional GPU usage (hours and minutes converted to decimal hours)
    without issuing intermediate invoices on every tick.
    - Pre-paid: Decrements balance in real-time. If balance <= 0, closes cycle and returns (cost, is_depleted=True).
    - Post-paid: Accumulates usage. If 30 simulated days elapsed, closes cycle, generates Invoice (UNPAID),
      and starts a new billing cycle.
    Returns (accrued_cost, is_depleted).
    """
    if not lease.gpu_instance:
        return Decimal("0.00"), False

    if ended_at is None:
        ended_at = timezone.now()

    model = lease.gpu_instance.model
    effective_rate, discount_applied = get_effective_hourly_rate(lease.user, model)
    simulated_duration = get_simulated_duration(lease.started_at, ended_at)
    simulated_hours = Decimal(simulated_duration.total_seconds()) / Decimal("3600.0")
    cost = (simulated_hours * effective_rate).quantize(Decimal("0.01"))

    is_prepaid = is_prepaid_model(model)
    cycle = get_or_create_active_cycle(lease.user, model, is_prepaid)

    # Accumulate usage
    if simulated_hours > Decimal("0.00"):
        cycle.hours_consumed = (cycle.hours_consumed + simulated_hours).quantize(Decimal("0.0001"))
        cycle.total_consumption = (cycle.total_consumption + cost).quantize(Decimal("0.01"))

        # Update lease accumulator
        current_billed = Decimal(str(lease.total_billed_amount))
        lease.total_billed_amount = (current_billed + cost).quantize(Decimal("0.01"))
        if discount_applied:
            lease.volume_discount_applied = Decimal("10.00")
        lease.started_at = ended_at
        lease.save(update_fields=["total_billed_amount", "volume_discount_applied", "started_at"])

    if is_prepaid:
        credit, _ = UserCredit.objects.select_for_update().get_or_create(user=lease.user)
        credit.balance = (credit.balance - cost).quantize(Decimal("0.01"))
        credit.save(update_fields=["balance"])
        _check_and_trigger_low_credit_warning(credit)

        if credit.balance <= Decimal("0.00"):
            cycle.cycle_ended_at = ended_at
            cycle.is_active = False
            cycle.save(update_fields=["hours_consumed", "total_consumption", "cycle_ended_at", "is_active"])
            return cost, True

        cycle.save(update_fields=["hours_consumed", "total_consumption"])
        return cost, False
    else:
        # Post-paid: Check 30-day billing cycle closure
        cycle_duration = get_simulated_duration(cycle.cycle_started_at, ended_at)
        if cycle_duration.total_seconds() >= 30 * 24 * 3600 and cycle.total_consumption > Decimal("0.00"):
            cycle.cycle_ended_at = ended_at
            cycle.is_active = False
            cycle.save(update_fields=["hours_consumed", "total_consumption", "cycle_ended_at", "is_active"])

            net_invoice_amount = cycle.total_consumption
            description = f"30-Day Postpaid Usage Invoice for {model.name} from {cycle.cycle_started_at} to {ended_at}."
            if discount_applied:
                description += " (10% Volume Discount Applied)"

            try:
                credit = UserCredit.objects.select_for_update().get(user=lease.user)
                if credit.frozen_prepaid_balance > Decimal("0.00"):
                    abatement = min(net_invoice_amount, credit.frozen_prepaid_balance)
                    net_invoice_amount = (net_invoice_amount - abatement).quantize(Decimal("0.01"))
                    credit.frozen_prepaid_balance = (credit.frozen_prepaid_balance - abatement).quantize(
                        Decimal("0.01")
                    )
                    credit.save(update_fields=["frozen_prepaid_balance"])
                    description += f" (Abated ${abatement} from frozen prepaid balance)"
            except UserCredit.DoesNotExist:
                pass

            invoice_status = InvoiceStatus.PAID if net_invoice_amount == Decimal("0.00") else InvoiceStatus.UNPAID
            Invoice.objects.create(
                user=lease.user,
                lease_id=lease.id,
                amount=net_invoice_amount,
                status=invoice_status,
                description=description,
            )

            # Start new cycle
            ClientUsageCycle.objects.create(
                client=lease.user,
                plan_type=PlanType.POSTPAID,
                gpu=model.name,
                hours_consumed=Decimal("0.0000"),
                total_consumption=Decimal("0.00"),
                total_credits=Decimal("0.00"),
                cycle_started_at=ended_at,
                cycle_ended_at=None,
                is_active=True,
            )
        else:
            cycle.save(update_fields=["hours_consumed", "total_consumption"])

        return cost, False


def invoice_lease_usage(lease: RentalLease, ended_at=None) -> Decimal:
    """
    Invoices the active usage of a lease from its started_at timestamp up to ended_at (default: now).
    Used for final lease termination settlements or explicit invoice checkpoints.
    Deducts from pre-paid UserCredit if the GPU model is RTX 4090 or L4.
    Otherwise, creates an UNPAID post-paid invoice.
    Returns the invoiced gross amount.
    """
    if not lease.gpu_instance:
        return Decimal("0.00")

    if ended_at is None:
        ended_at = timezone.now()

    model = lease.gpu_instance.model
    effective_rate, discount_applied = get_effective_hourly_rate(lease.user, model)
    gross_amount = calculate_accrued_cost(lease.started_at, ended_at, effective_rate)

    if gross_amount <= Decimal("0.00"):
        return Decimal("0.00")

    is_prepaid = is_prepaid_model(model)
    net_invoice_amount = gross_amount

    description = f"Usage invoice for {model.name} from {lease.started_at} to {ended_at}."
    if discount_applied:
        description += " (10% Volume Discount Applied)"

    if not is_prepaid:
        with transaction.atomic():
            try:
                credit = UserCredit.objects.select_for_update().get(user=lease.user)
                if credit.frozen_prepaid_balance > Decimal("0.00"):
                    abatement = min(gross_amount, credit.frozen_prepaid_balance)
                    net_invoice_amount = (gross_amount - abatement).quantize(Decimal("0.01"))
                    credit.frozen_prepaid_balance = (credit.frozen_prepaid_balance - abatement).quantize(
                        Decimal("0.01")
                    )
                    credit.save(update_fields=["frozen_prepaid_balance"])
                    description += f" (Abated ${abatement} from frozen prepaid balance)"
            except UserCredit.DoesNotExist:
                pass

    if is_prepaid:
        status = InvoiceStatus.PAID
    else:
        status = InvoiceStatus.PAID if net_invoice_amount == Decimal("0.00") else InvoiceStatus.UNPAID

    Invoice.objects.create(
        user=lease.user,
        lease_id=lease.id,
        amount=net_invoice_amount,
        status=status,
        description=description,
    )

    if is_prepaid:
        with transaction.atomic():
            credit, _ = UserCredit.objects.select_for_update().get_or_create(user=lease.user)
            credit.balance = (credit.balance - gross_amount).quantize(Decimal("0.01"))
            credit.save(update_fields=["balance"])
            _check_and_trigger_low_credit_warning(credit)

    # Update lease billed amount
    current_billed = Decimal(str(lease.total_billed_amount))
    lease.total_billed_amount = (current_billed + gross_amount).quantize(Decimal("0.01"))
    if discount_applied:
        lease.volume_discount_applied = Decimal("10.00")
    lease.save(update_fields=["total_billed_amount", "volume_discount_applied"])

    # Close active usage cycle on settlement
    active_cycle = ClientUsageCycle.objects.filter(client=lease.user, is_active=True).first()
    if active_cycle:
        active_cycle.cycle_ended_at = ended_at
        active_cycle.is_active = False
        active_cycle.save(update_fields=["cycle_ended_at", "is_active"])

    logger.info(
        "Invoiced lease %s for usage: Gross $%s, Net Invoice $%s (%s). Prepaid=%s",
        lease.id,
        gross_amount,
        net_invoice_amount,
        status,
        is_prepaid,
    )
    return gross_amount


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


def is_new_account_eligible_for_promo(user) -> bool:
    """
    Checks if a user is eligible for new account promotional bonuses.
    Returns True if user has no previous invoices and no previous leases.
    """
    has_invoices = Invoice.objects.filter(user=user).exists()
    has_leases = RentalLease.objects.filter(user=user).exists()
    return not (has_invoices or has_leases)


def purchase_prepaid_package(
    user,
    model: GPUModel,
    months: int,
    hours_per_month: int = 730,
) -> dict:
    """
    Purchases a prepaid usage package for a GPUModel.
    Awards 1 free month equivalent in credit if months >= 3 and user is a new account.
    Volume discounts do not stack with this promotional package.
    """
    if months < 1:
        raise ValueError("Months must be at least 1.")

    hourly_rate = model.price_per_hour
    base_hours = Decimal(str(months)) * Decimal(str(hours_per_month))
    base_amount = (base_hours * hourly_rate).quantize(Decimal("0.01"))

    is_eligible = is_new_account_eligible_for_promo(user)
    bonus_applied = months >= 3 and is_eligible

    if bonus_applied:
        bonus_hours = Decimal(str(hours_per_month))
        bonus_amount = (bonus_hours * hourly_rate).quantize(Decimal("0.01"))
        total_credited = (base_amount + bonus_amount).quantize(Decimal("0.01"))
        description = (
            f"Prepaid {months}-Month Package for {model.name} (Includes 1 Free Month Promo Bonus of ${bonus_amount})"
        )
    else:
        bonus_amount = Decimal("0.00")
        total_credited = base_amount
        description = f"Prepaid {months}-Month Package for {model.name}"

    with transaction.atomic():
        credit, _ = UserCredit.objects.select_for_update().get_or_create(user=user)
        credit.balance = (credit.balance + total_credited).quantize(Decimal("0.01"))
        credit.save(update_fields=["balance"])

        invoice = Invoice.objects.create(
            user=user,
            amount=base_amount,
            status=InvoiceStatus.PAID,
            description=description,
        )

        # Close any previous inactive cycles if existing and open a new active cycle
        ClientUsageCycle.objects.filter(client=user, is_active=True).update(
            is_active=False, cycle_ended_at=timezone.now()
        )
        ClientUsageCycle.objects.create(
            client=user,
            plan_type=PlanType.PREPAID,
            gpu=model.name,
            hours_consumed=Decimal("0.0000"),
            total_consumption=Decimal("0.00"),
            total_credits=total_credited,
            cycle_started_at=timezone.now(),
            cycle_ended_at=None,
            is_active=True,
        )

    logger.info(
        "Purchased %s months package for user %s. Base: $%s, Bonus: $%s, Credited: $%s",
        months,
        user.username,
        base_amount,
        bonus_amount,
        total_credited,
    )

    return {
        "user_id": str(user.id),
        "model_id": str(model.id),
        "months_purchased": months,
        "base_amount": base_amount,
        "bonus_amount": bonus_amount,
        "total_credited": total_credited,
        "bonus_applied": bonus_applied,
        "invoice_id": str(invoice.id),
        "new_balance": credit.balance,
    }


def settle_postpaid_invoice(invoice_id, payment_method="mock_gateway") -> Invoice:
    """
    Settles an outstanding UNPAID postpaid invoice via payment gateway,
    transitions invoice status to PAID, and emits payment confirmation SystemAlert.
    """
    with transaction.atomic():
        invoice = Invoice.objects.select_for_update().get(id=invoice_id)
        if invoice.status == InvoiceStatus.PAID:
            logger.info("Invoice %s is already settled.", invoice_id)
            return invoice

        invoice.status = InvoiceStatus.PAID
        invoice.save(update_fields=["status"])

        # Trigger real-time SystemAlert for payment confirmation toast
        try:
            from leases.models import SystemAlert

            SystemAlert.objects.create(
                alert_type="billing",
                message=(
                    f"💵 Postpaid invoice of ${invoice.amount} paid successfully by customer {invoice.user.username}!"
                ),
            )
        except Exception:
            logger.exception("Failed to create invoice settlement SystemAlert")

        # Send confirmation email
        try:
            from billing.tasks import send_invoice_email

            send_invoice_email.enqueue(
                user_id=str(invoice.user.id),
                invoice_id=str(invoice.id),
                is_payment_receipt=True,
            )
        except Exception:
            logger.exception("Failed to enqueue invoice settlement confirmation email")

    logger.info("Successfully settled invoice %s for user %s via %s", invoice_id, invoice.user.username, payment_method)
    return invoice
