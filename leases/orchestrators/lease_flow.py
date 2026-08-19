import logging
from decimal import Decimal

from django.utils import timezone

from billing.models import Invoice, InvoiceStatus, UserCredit
from billing.services.ledger import get_or_create_active_cycle, is_prepaid_model
from billing.services.payment_gateway import process_payment
from gpurent.core.orchestrators import BaseOrchestrator
from leases.models import GPUInstance, GPUInstanceStatus, GPUModel, RentalLease, RentalLeaseStatus

logger = logging.getLogger(__name__)


class LeaseProvisioningOrchestrator(BaseOrchestrator[RentalLease]):
    """
    Object-Oriented Orchestrator that manages the process of provisioning a new GPU lease.
    Inherits from the core BaseOrchestrator Shared Kernel to guarantee transaction safety,
    standardized logging, and DRY compliance.
    """

    def __init__(self, user, gpu_model_id, is_dedicated: bool = False, card_token: str = None):
        self.user = user
        self.gpu_model_id = gpu_model_id
        self.is_dedicated = is_dedicated
        self.card_token = card_token
        self.model = None
        self.gpu_instance = None
        self.lease = None

    def run(self) -> RentalLease:
        self._fetch_and_validate_model()
        self._check_prepaid_credits()
        self._allocate_physical_resource()
        self._audit_and_reserve_instance()
        self._create_lease()
        self._process_upfront_payment_or_activate()
        return self.lease

    def _fetch_and_validate_model(self):
        try:
            self.model = GPUModel.objects.get(pk=self.gpu_model_id)
        except GPUModel.DoesNotExist as e:
            raise ValueError(f"GPU Model with ID {self.gpu_model_id} does not exist.") from e

    def _check_prepaid_credits(self):
        # Check pre-paid credit limits if it's a pre-paid model family
        if is_prepaid_model(self.model):
            credit, _ = UserCredit.objects.select_for_update().get_or_create(user=self.user)
            if credit.balance <= Decimal("0.00"):
                raise ValueError("Insufficient pre-paid credits to initiate lease. Please top up your balance.")

    def _allocate_physical_resource(self):
        # Find an available physical instance matching model and dedication requirement
        self.gpu_instance = GPUInstance.objects.filter(
            model=self.model,
            status=GPUInstanceStatus.AVAILABLE,
            is_dedicated=self.is_dedicated,
        ).first()

        if not self.gpu_instance:
            raise ValueError(
                f"No available physical GPU instances for model {self.model.name} (Dedicated: {self.is_dedicated})."
            )

    def _audit_and_reserve_instance(self):
        # Reserve and audit physical instance
        if self.is_dedicated:
            # Dedicated Isolation Auditor: Enforce strict single-tenant allocation
            active_count = RentalLease.objects.filter(
                gpu_instance=self.gpu_instance, status=RentalLeaseStatus.ACTIVE
            ).count()
            if active_count > 0:
                raise ValueError(f"Dedicated GPU instance {self.gpu_instance.serial_number} is already active.")
            self.gpu_instance.status = GPUInstanceStatus.LEASED
            self.gpu_instance.save(update_fields=["status"])
        else:
            # Shared Concurrency Auditor: Limit shared physical cards to maximum 4 active tenants
            active_count = RentalLease.objects.filter(
                gpu_instance=self.gpu_instance, status=RentalLeaseStatus.ACTIVE
            ).count()
            if active_count >= 4:
                raise ValueError(f"Shared GPU instance {self.gpu_instance.serial_number} has reached max capacity.")
            elif active_count == 3:
                # This lease will be the 4th active lease, marking instance as fully LEASED (occupied)
                self.gpu_instance.status = GPUInstanceStatus.LEASED
                self.gpu_instance.save(update_fields=["status"])
            else:
                # Keep instance status as AVAILABLE to accept more tenants
                self.gpu_instance.status = GPUInstanceStatus.AVAILABLE
                self.gpu_instance.save(update_fields=["status"])

    def _create_lease(self):
        # Create the RentalLease row in PROVISIONING state
        now = timezone.now()
        self.lease = RentalLease.objects.create(
            user=self.user,
            gpu_instance=self.gpu_instance,
            status=RentalLeaseStatus.PROVISIONING,
            started_at=now,
        )

    def _process_upfront_payment_or_activate(self):
        if self.is_dedicated:
            # Enforce upfront payment for dedicated instances
            # We charge the hourly rate for the first hour as the upfront payment amount
            upfront_amount = self.model.price_per_hour
            token = self.card_token if self.card_token else "tok_visa"

            # Call mock gateway client
            payment_status = process_payment(self.user.id, upfront_amount, token)

            if payment_status == "PAID":
                # Create paid invoice
                Invoice.objects.create(
                    user=self.user,
                    lease_id=self.lease.id,
                    amount=upfront_amount,
                    status=InvoiceStatus.PAID,
                    description=f"Pre-paid upfront deposit for Dedicated {self.model.name} lease.",
                )
                # Activate lease
                self.lease.status = RentalLeaseStatus.ACTIVE
                self.lease.total_billed_amount = upfront_amount
                self.lease.save(update_fields=["status", "total_billed_amount"])
                get_or_create_active_cycle(self.user, self.model, is_prepaid_model(self.model))
                logger.info("Successfully provisioned and activated dedicated lease %s.", self.lease.id)
            else:
                # Release physical card and fail lease
                self.gpu_instance.status = GPUInstanceStatus.AVAILABLE
                self.gpu_instance.save(update_fields=["status"])
                raise ValueError("Upfront dedicated payment failed. Card declined.")
        else:
            # Shared instance: directly activate
            self.lease.status = RentalLeaseStatus.ACTIVE
            self.lease.save(update_fields=["status"])
            get_or_create_active_cycle(self.user, self.model, is_prepaid_model(self.model))
            logger.info("Successfully provisioned and activated shared lease %s.", self.lease.id)


def provision_lease(user, gpu_model_id, is_dedicated: bool = False, card_token: str = None) -> RentalLease:
    """
    Provisions a new GPU Rental Lease.
    Procedural wrapper that delegates to LeaseProvisioningOrchestrator for elegant DDD design.
    """
    return LeaseProvisioningOrchestrator(user, gpu_model_id, is_dedicated, card_token).execute()
