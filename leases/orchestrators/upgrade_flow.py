import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from billing.services.ledger import invoice_flat_fee, invoice_lease_usage
from leases.models import GPUInstance, GPUInstanceStatus, GPUModel, RentalLease, RentalLeaseStatus

logger = logging.getLogger(__name__)


def upgrade_lease_tier(lease_id, target_model_id) -> RentalLease:
    """
    Orchestrates the mid-lease GPU upgrade workflow within a single atomic database transaction.
    Locks the lease row, invoices outstanding usage, frees up the old GPU, assesses dynamic
    upgrade fees ($15 for Tier Swap, $5 for VRAM scaling), allocates a new physical instance,
    and updates the lease reference.
    """
    with transaction.atomic():
        # 1. Obtain a row-level lock on the RentalLease
        try:
            lease = RentalLease.objects.select_for_update().get(pk=lease_id)
        except RentalLease.DoesNotExist as e:
            raise ValueError(f"RentalLease with ID {lease_id} does not exist.") from e

        # 2. Assert lease status is ACTIVE
        if lease.status != RentalLeaseStatus.ACTIVE:
            raise ValueError(f"Only active leases can be upgraded. Current status: {lease.status}")

        old_instance = lease.gpu_instance
        if not old_instance:
            raise ValueError(f"Lease {lease_id} has no associated physical GPU instance to upgrade from.")

        old_model = old_instance.model

        # Fetch target GPU model
        try:
            target_model = GPUModel.objects.get(pk=target_model_id)
        except GPUModel.DoesNotExist as e:
            raise ValueError(f"Target GPU Model with ID {target_model_id} does not exist.") from e

        if old_model.id == target_model.id:
            raise ValueError("Target model is the same as the current leased model.")

        # 3. Calculate and invoice accrued usage for the old GPU
        now = timezone.now()
        invoice_lease_usage(lease, ended_at=now)

        # 4. Release the old physical GPUInstance to the inventory
        old_instance.status = GPUInstanceStatus.AVAILABLE
        old_instance.save(update_fields=["status"])

        # 5. Determine dynamic upgrade fee
        old_family_prefix = old_model.name.split(" (")[0]
        target_family_prefix = target_model.name.split(" (")[0]

        if old_family_prefix == target_family_prefix:
            # VRAM scaling increment (e.g. A100 40GB ➔ A100 80GB)
            fee_amount = Decimal("5.00")
            fee_description = f"Flat upgrade charge: VRAM Scaling from {old_model.name} to {target_model.name}."
        else:
            # Mid-lease Tier Swap (different model family, e.g. L4 ➔ A100)
            fee_amount = Decimal("15.00")
            fee_description = f"Flat upgrade charge: Tier Swap from {old_model.name} to {target_model.name}."

        is_prepaid = target_model.name.startswith("NVIDIA RTX") or target_model.name.startswith("NVIDIA L4")

        # Invoice this flat fee
        invoice_flat_fee(
            user=lease.user,
            lease_id=lease.id,
            amount=fee_amount,
            description=fee_description,
            is_prepaid=is_prepaid,
        )

        # 6. Query and claim an available physical instance of the target model
        new_instance = GPUInstance.objects.filter(
            model=target_model,
            status=GPUInstanceStatus.AVAILABLE,
        ).first()

        if not new_instance:
            raise ValueError(f"No available physical instances for the selected model: {target_model.name}")

        new_instance.status = GPUInstanceStatus.LEASED
        new_instance.save(update_fields=["status"])

        # 7. Update RentalLease with new targets and reset start timestamp
        lease.gpu_instance = new_instance
        lease.started_at = now
        lease.total_billed_amount = (lease.total_billed_amount + fee_amount).quantize(Decimal("0.01"))
        lease.save(update_fields=["gpu_instance", "started_at", "total_billed_amount"])

        logger.info(
            "Successfully upgraded lease %s from %s to %s (Physical Serial: %s).",
            lease.id,
            old_model.name,
            target_model.name,
            new_instance.serial_number,
        )
        return lease
