import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from billing.services.ledger import invoice_flat_fee, invoice_lease_usage
from leases.models import GPUInstanceStatus, RentalLease, RentalLeaseStatus
from leases.utils.time_scale import get_simulated_duration
from users.models import TenantProfile

logger = logging.getLogger(__name__)


def soft_delete_tenant(user_id) -> TenantProfile:
    """
    Orchestrates the soft-deletion of a Tenant account.
    Verifies that the tenant has zero financial arrears and releases all active GPU resources.
    Marks deleted_at and disables core authentication.
    """
    with transaction.atomic():
        try:
            profile = TenantProfile.objects.select_for_update().get(user_id=user_id)
        except TenantProfile.DoesNotExist as e:
            raise ValueError(f"TenantProfile for User {user_id} does not exist.") from e

        if profile.deleted_at is not None:
            raise ValueError("Tenant account is already soft-deleted.")

        # 1. Verify that the user has zero financial liabilities
        if not profile.can_delete():
            raise ValueError(
                "Cannot delete account. All outstanding UNPAID invoices must be settled "
                "and prepaid credit balance must be non-negative."
            )

        now = timezone.now()

        # 2. Release all active GPU leases back to the inventory
        active_leases = RentalLease.objects.filter(
            user=profile.user,
            status=RentalLeaseStatus.ACTIVE,
        )

        for lease in active_leases:
            # Invoice usage up to this millisecond
            invoice_lease_usage(lease, ended_at=now)
            lease.status = RentalLeaseStatus.COMPLETED
            lease.ended_at = now
            lease.save(update_fields=["status", "ended_at"])

            if lease.gpu_instance:
                gpu_instance = lease.gpu_instance
                gpu_instance.status = GPUInstanceStatus.AVAILABLE
                gpu_instance.save(update_fields=["status"])

        # 3. Apply soft-delete timestamps and disable core authentication
        profile.deleted_at = now
        profile.save(update_fields=["deleted_at"])

        user = profile.user
        user.is_active = False
        user.save(update_fields=["is_active"])

        # Trigger real-time SystemAlert for admin dashboard
        from leases.models import SystemAlert

        SystemAlert.objects.create(
            alert_type="delete",
            message=f"Tenant account soft-deleted: {user.username}",
        )

        logger.info("Successfully soft-deleted tenant account for user: %s", user.username)
        return profile


def freeze_tenant_account(user_id, keep_dedicated_gpus: bool = False) -> TenantProfile:
    """
    Orchestrates the account freezing procedure.
    Shared GPU leases are terminated instantly. Dedicated leases can either be held (incurring a
    10% preservation weekly fee calculated on reactivation) or released immediately.
    """
    with transaction.atomic():
        try:
            profile = TenantProfile.objects.select_for_update().get(user_id=user_id)
        except TenantProfile.DoesNotExist as e:
            raise ValueError(f"TenantProfile for User {user_id} does not exist.") from e

        if profile.freezed_at is not None:
            raise ValueError("Account is already frozen.")

        now = timezone.now()

        # Get all active leases
        active_leases = RentalLease.objects.filter(
            user=profile.user,
            status=RentalLeaseStatus.ACTIVE,
        )

        for lease in active_leases:
            # Settle elapsed usage up to this exact moment
            invoice_lease_usage(lease, ended_at=now)

            gpu_instance = lease.gpu_instance
            if not gpu_instance:
                continue

            if gpu_instance.is_dedicated and keep_dedicated_gpus:
                # Keep dedicated GPU locked/reserved. The lease remains ACTIVE in database,
                # but we reset started_at to now. The 10% preservation fee will be evaluated on unfreeze.
                lease.started_at = now
                lease.save(update_fields=["started_at"])
                logger.info("Dedicated GPU %s remains reserved for frozen user.", gpu_instance.serial_number)
            else:
                # Shared leases, or dedicated leases where user opted to release
                lease.status = RentalLeaseStatus.COMPLETED
                lease.ended_at = now
                lease.save(update_fields=["status", "ended_at"])

                gpu_instance.status = GPUInstanceStatus.AVAILABLE
                gpu_instance.save(update_fields=["status"])
                logger.info("Released GPU %s back to general inventory.", gpu_instance.serial_number)

        profile.freezed_at = now
        profile.keep_dedicated_gpus = keep_dedicated_gpus
        profile.save(update_fields=["freezed_at", "keep_dedicated_gpus"])

        # Trigger async freeze alert email and schedule 30-day freeze expiry task
        from datetime import timedelta

        from users.tasks import schedule_freeze_expiry_check, send_freezing_alert_email

        send_freezing_alert_email.enqueue(user_id=str(profile.user.id))

        # Check backend capability: if supports_defer is True (SteadyQueueBackend), schedule 30 days in future.
        # Otherwise (ImmediateBackend in tests), enqueue immediately for synchronous testing.
        backend = schedule_freeze_expiry_check.get_backend()
        if getattr(backend, "supports_defer", False):
            run_time = timezone.now() + timedelta(days=30)
            schedule_freeze_expiry_check.using(run_after=run_time).enqueue(user_id=str(profile.user.id))
        else:
            schedule_freeze_expiry_check.enqueue(user_id=str(profile.user.id))

        logger.info("Successfully froze tenant account for user: %s", profile.user.username)
        return profile


def unfreeze_tenant_account(user_id) -> TenantProfile:
    """
    Orchestrates the account reactivation procedure.
    If dedicated GPUs were held, calculates and bills the 10% preservation fee (pro-rated weekly,
    accelerated by TIME_SCALE_FACTOR) and updates lease start times. Restores API access.
    """
    with transaction.atomic():
        try:
            profile = TenantProfile.objects.select_for_update().get(user_id=user_id)
        except TenantProfile.DoesNotExist as e:
            raise ValueError(f"TenantProfile for User {user_id} does not exist.") from e

        if profile.freezed_at is None:
            raise ValueError("Account is not frozen.")

        now = timezone.now()

        # If dedicated GPUs were held, calculate the 10% preservation fee
        if profile.keep_dedicated_gpus:
            held_leases = RentalLease.objects.filter(
                user=profile.user,
                status=RentalLeaseStatus.ACTIVE,
                gpu_instance__is_dedicated=True,
            )

            # Compute simulated elapsed hours during frozen state (supports TIME_SCALE_FACTOR)
            sim_duration = get_simulated_duration(profile.freezed_at, now)
            sim_hours = Decimal(sim_duration.total_seconds()) / Decimal("3600.0")

            for lease in held_leases:
                hourly_rate = lease.gpu_instance.model.price_per_hour
                # 10% hourly preservation rate
                holding_rate = (hourly_rate * Decimal("0.10")).quantize(Decimal("0.0001"))
                holding_fee = (sim_hours * holding_rate).quantize(Decimal("0.01"))

                if holding_fee > Decimal("0.00"):
                    fee_description = (
                        f"10% Dedicated GPU reservation fee for {lease.gpu_instance.model.name} "
                        f"during account frozen state ({sim_hours:.2f} simulated hours)."
                    )
                    # Deduct the preservation fee from pre-paid balance
                    invoice_flat_fee(
                        user=profile.user,
                        lease_id=lease.id,
                        amount=holding_fee,
                        description=fee_description,
                        is_prepaid=True,
                    )
                    # Update lease billed amount and reset started_at for standard billing resumption
                    lease.total_billed_amount = (lease.total_billed_amount + holding_fee).quantize(Decimal("0.01"))

                lease.started_at = now
                lease.save(update_fields=["started_at", "total_billed_amount"])

        profile.freezed_at = None
        profile.keep_dedicated_gpus = False
        profile.save(update_fields=["freezed_at", "keep_dedicated_gpus"])

        logger.info("Successfully unfroze tenant account for user: %s", profile.user.username)
        return profile
