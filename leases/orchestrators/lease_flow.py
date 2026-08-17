import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from billing.models import Invoice, InvoiceStatus, UserCredit
from billing.services.payment_gateway import process_payment
from leases.models import GPUInstance, GPUInstanceStatus, GPUModel, RentalLease, RentalLeaseStatus

logger = logging.getLogger(__name__)


def provision_lease(user, gpu_model_id, is_dedicated: bool = False, card_token: str = None) -> RentalLease:
    """
    Provisions a new GPU Rental Lease.
    If the requested GPU is dedicated (is_dedicated=True), enforces upfront payment processing
    against the local payment mock gateway before activating the lease.
    """
    with transaction.atomic():
        try:
            model = GPUModel.objects.get(pk=gpu_model_id)
        except GPUModel.DoesNotExist as e:
            raise ValueError(f"GPU Model with ID {gpu_model_id} does not exist.") from e

        # Check pre-paid credit limits if it's a pre-paid model family
        is_prepaid = model.name.startswith("NVIDIA RTX") or model.name.startswith("NVIDIA L4")
        if is_prepaid:
            credit, _ = UserCredit.objects.select_for_update().get_or_create(user=user)
            if credit.balance <= Decimal("0.00"):
                raise ValueError("Insufficient pre-paid credits to initiate lease. Please top up your balance.")

        # Find an available physical instance matching model and dedication requirement
        gpu_instance = GPUInstance.objects.filter(
            model=model,
            status=GPUInstanceStatus.AVAILABLE,
            is_dedicated=is_dedicated,
        ).first()

        if not gpu_instance:
            raise ValueError(f"No available physical GPU instances for model {model.name} (Dedicated: {is_dedicated}).")

        # Reserve and audit physical instance
        if is_dedicated:
            # Dedicated Isolation Auditor: Enforce strict single-tenant allocation
            active_count = RentalLease.objects.filter(
                gpu_instance=gpu_instance, status=RentalLeaseStatus.ACTIVE
            ).count()
            if active_count > 0:
                raise ValueError(f"Dedicated GPU instance {gpu_instance.serial_number} is already active.")
            gpu_instance.status = GPUInstanceStatus.LEASED
            gpu_instance.save(update_fields=["status"])
        else:
            # Shared Concurrency Auditor: Limit shared physical cards to maximum 4 active tenants
            active_count = RentalLease.objects.filter(
                gpu_instance=gpu_instance, status=RentalLeaseStatus.ACTIVE
            ).count()
            if active_count >= 4:
                raise ValueError(f"Shared GPU instance {gpu_instance.serial_number} has reached max capacity.")
            elif active_count == 3:
                # This lease will be the 4th active lease, marking instance as fully LEASED (occupied)
                gpu_instance.status = GPUInstanceStatus.LEASED
                gpu_instance.save(update_fields=["status"])
            else:
                # Keep instance status as AVAILABLE to accept more tenants
                gpu_instance.status = GPUInstanceStatus.AVAILABLE
                gpu_instance.save(update_fields=["status"])

        # Create the RentalLease row in PROVISIONING state
        now = timezone.now()
        lease = RentalLease.objects.create(
            user=user,
            gpu_instance=gpu_instance,
            status=RentalLeaseStatus.PROVISIONING,
            started_at=now,
        )

        if is_dedicated:
            # Enforce upfront payment for dedicated instances
            # We charge the hourly rate for the first hour as the upfront payment amount
            upfront_amount = model.price_per_hour
            if not card_token:
                card_token = "tok_visa"  # Default mock token if none supplied

            # Call mock gateway client
            payment_status = process_payment(user.id, upfront_amount, card_token)

            if payment_status == "PAID":
                # Create paid invoice
                Invoice.objects.create(
                    user=user,
                    lease_id=lease.id,
                    amount=upfront_amount,
                    status=InvoiceStatus.PAID,
                    description=f"Pre-paid upfront deposit for Dedicated {model.name} lease.",
                )
                # Activate lease
                lease.status = RentalLeaseStatus.ACTIVE
                lease.total_billed_amount = upfront_amount
                lease.save(update_fields=["status", "total_billed_amount"])
                logger.info("Successfully provisioned and activated dedicated lease %s.", lease.id)
            else:
                # Release physical card and fail lease
                gpu_instance.status = GPUInstanceStatus.AVAILABLE
                gpu_instance.save(update_fields=["status"])
                raise ValueError("Upfront dedicated payment failed. Card declined.")
        else:
            # Shared instance: directly activate
            lease.status = RentalLeaseStatus.ACTIVE
            lease.save(update_fields=["status"])
            logger.info("Successfully provisioned and activated shared lease %s.", lease.id)

        return lease
