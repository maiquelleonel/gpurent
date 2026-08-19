import logging
from decimal import Decimal

from django.utils import timezone

from billing.services.ledger import (
    get_or_create_active_cycle,
    invoice_flat_fee,
    invoice_lease_usage,
    is_postpaid_model,
    is_prepaid_model,
)
from gpurent.core.orchestrators import BaseOrchestrator
from leases.models import GPUInstance, GPUInstanceStatus, GPUModel, RentalLease, RentalLeaseStatus

logger = logging.getLogger(__name__)


class LeaseUpgradeOrchestrator(BaseOrchestrator[RentalLease]):
    """
    Object-Oriented Orchestrator that manages the process of upgrading an active lease's GPU tier.
    Inherits from the core BaseOrchestrator Shared Kernel to guarantee transaction safety,
    standardized logging, and DRY compliance.
    """

    def __init__(self, lease_id, target_model_id):
        self.lease_id = lease_id
        self.target_model_id = target_model_id
        self.lease = None
        self.old_instance = None
        self.old_model = None
        self.target_model = None
        self.new_instance = None
        self.fee_amount = Decimal("0.00")
        self.fee_description = ""
        self.now = None

    def run(self) -> RentalLease:
        self._lock_and_validate_lease()
        self._fetch_and_validate_target_model()
        self._invoice_accrued_usage()
        self._release_old_resource()
        self._assess_and_invoice_fees()
        self._allocate_new_resource()
        self._finalize_upgrade()
        return self.lease

    def _lock_and_validate_lease(self):
        try:
            self.lease = RentalLease.objects.select_for_update().get(pk=self.lease_id)
        except RentalLease.DoesNotExist as e:
            raise ValueError(f"RentalLease with ID {self.lease_id} does not exist.") from e

        if self.lease.status != RentalLeaseStatus.ACTIVE:
            raise ValueError(f"Only active leases can be upgraded. Current status: {self.lease.status}")

        self.old_instance = self.lease.gpu_instance
        if not self.old_instance:
            raise ValueError(f"Lease {self.lease_id} has no associated physical GPU instance to upgrade from.")

        self.old_model = self.old_instance.model

    def _fetch_and_validate_target_model(self):
        try:
            self.target_model = GPUModel.objects.get(pk=self.target_model_id)
        except GPUModel.DoesNotExist as e:
            raise ValueError(f"Target GPU Model with ID {self.target_model_id} does not exist.") from e

        if self.old_model.id == self.target_model.id:
            raise ValueError("Target model is the same as the current leased model.")

    def _invoice_accrued_usage(self):
        self.now = timezone.now()
        invoice_lease_usage(self.lease, ended_at=self.now)

    def _release_old_resource(self):
        self.old_instance.status = GPUInstanceStatus.AVAILABLE
        self.old_instance.save(update_fields=["status"])

    def _assess_and_invoice_fees(self):
        old_family_prefix = self.old_model.name.split(" (")[0]
        target_family_prefix = self.target_model.name.split(" (")[0]

        if old_family_prefix == target_family_prefix:
            # VRAM scaling increment (e.g. A100 40GB ➔ A100 80GB)
            self.fee_amount = Decimal("5.00")
            self.fee_description = (
                f"Flat upgrade charge: VRAM Scaling from {self.old_model.name} to {self.target_model.name}."
            )
        else:
            # Mid-lease Tier Swap (different model family, e.g. L4 ➔ A100)
            self.fee_amount = Decimal("15.00")
            self.fee_description = (
                f"Flat upgrade charge: Tier Swap from {self.old_model.name} to {self.target_model.name}."
            )

        is_prepaid = is_prepaid_model(self.target_model)

        # Invoice this flat fee
        invoice_flat_fee(
            user=self.lease.user,
            lease_id=self.lease.id,
            amount=self.fee_amount,
            description=self.fee_description,
            is_prepaid=is_prepaid,
        )

        was_prepaid = is_prepaid_model(self.old_model)
        is_postpaid = is_postpaid_model(self.target_model)

        if was_prepaid and is_postpaid:
            from billing.models import UserCredit

            credit, _ = UserCredit.objects.select_for_update().get_or_create(user=self.lease.user)
            if credit.balance > Decimal("0.00"):
                credit.frozen_prepaid_balance = credit.balance
                credit.balance = Decimal("0.00")
                credit.save(update_fields=["frozen_prepaid_balance", "balance"])

    def _allocate_new_resource(self):
        self.new_instance = GPUInstance.objects.filter(
            model=self.target_model,
            status=GPUInstanceStatus.AVAILABLE,
        ).first()

        if not self.new_instance:
            raise ValueError(f"No available physical instances for the selected model: {self.target_model.name}")

        self.new_instance.status = GPUInstanceStatus.LEASED
        self.new_instance.save(update_fields=["status"])

    def _finalize_upgrade(self):
        self.lease.gpu_instance = self.new_instance
        self.lease.started_at = self.now
        self.lease.total_billed_amount = (self.lease.total_billed_amount + self.fee_amount).quantize(Decimal("0.01"))
        self.lease.save(update_fields=["gpu_instance", "started_at", "total_billed_amount"])
        get_or_create_active_cycle(self.lease.user, self.target_model, is_prepaid_model(self.target_model))

        logger.info(
            "Successfully upgraded lease %s from %s to %s (Physical Serial: %s).",
            self.lease.id,
            self.old_model.name,
            self.target_model.name,
            self.new_instance.serial_number,
        )


def upgrade_lease_tier(lease_id, target_model_id) -> RentalLease:
    """
    Orchestrates the mid-lease GPU upgrade workflow within a single atomic database transaction.
    Procedural wrapper that delegates to LeaseUpgradeOrchestrator for robust DDD design.
    """
    return LeaseUpgradeOrchestrator(lease_id, target_model_id).execute()
