import logging
import random
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from billing.models import UserCredit
from billing.services.ledger import invoice_lease_usage
from leases.models import GPUInstanceStatus, MetricSnapshot, RentalLease, RentalLeaseStatus

logger = logging.getLogger(__name__)


class MetricsSimulatorWorker:
    """
    Simulation engine that periodically queries active GPU leases, calculates accrued billing,
    deducts pre-paid credits, suspends delinquent leases, generates synthetic utilization metrics
    (VRAM, compute, temperature), evaluates thermal watchdogs, and persists snapshots to the database.
    """

    def __init__(self, interval: float = 5.0):
        self.interval = interval
        self._is_running = False

    def generate_metrics(self, lease: RentalLease, force_temp: Decimal = None) -> MetricSnapshot:
        """
        Generates realistic metrics for a specific active RentalLease instance.
        """
        gpu_instance = lease.gpu_instance
        if not gpu_instance:
            raise ValueError(f"Active lease {lease.id} has no assigned physical GPU instance.")

        model = gpu_instance.model
        vram_capacity = Decimal(str(model.vram_capacity_gb))

        # VRAM: Fluctuates between 40% and 95% of model capacity
        vram_pct = Decimal(str(random.uniform(40.0, 95.0))) / Decimal("100.0")
        vram_used = (vram_capacity * vram_pct).quantize(Decimal("0.01"))

        # Compute Load: Between 0.0% and 100.0%
        compute_load = Decimal(str(random.uniform(0.0, 100.0))).quantize(Decimal("0.01"))

        # Temperature: Normally between 65.0C and 85.0C, with a 2% chance of a thermal anomaly spike (91.0C - 98.0C)
        if force_temp is not None:
            temperature = force_temp.quantize(Decimal("0.01"))
        else:
            if random.random() < 0.02:
                # Thermal spike anomaly
                temperature = Decimal(str(random.uniform(91.0, 98.0))).quantize(Decimal("0.01"))
            else:
                temperature = Decimal(str(random.uniform(65.0, 85.0))).quantize(Decimal("0.01"))

        # Watchdog: If temperature exceeds 90.0C, trigger immediate thermal alert
        is_thermal_alert = temperature > Decimal("90.0")
        if is_thermal_alert:
            logger.warning(
                "🚨 THERMAL ALERT on GPU instance %s (Serial: %s)! Temperature reached %s°C.",
                gpu_instance.id,
                gpu_instance.serial_number,
                temperature,
            )

        # Create MetricSnapshot record
        snapshot = MetricSnapshot.objects.create(
            gpu_instance=gpu_instance,
            vram_used_gb=vram_used,
            compute_load_pct=compute_load,
            temperature_c=temperature,
            is_thermal_alert=is_thermal_alert,
            timestamp=timezone.now(),
        )

        logger.info(
            "Persisted snapshot for GPU %s: VRAM=%sGB/%sGB, Load=%s%%, Temp=%s°C, Alert=%s",
            gpu_instance.serial_number,
            vram_used,
            vram_capacity,
            compute_load,
            temperature,
            is_thermal_alert,
        )

        return snapshot

    def tick(self) -> int:
        """
        Executes a single simulation tick:
        1. Invoices accrued usage for all active leases.
        2. Deducts credits from prepaid accounts and suspends delinquent leases.
        3. Generates and persists metric snapshots for remaining active leases.
        """
        active_leases = RentalLease.objects.filter(status=RentalLeaseStatus.ACTIVE).select_related(
            "gpu_instance__model"
        )

        simulated_count = 0
        now = timezone.now()

        for lease in active_leases:
            try:
                # Wrap each lease tick in a transaction block
                with transaction.atomic():
                    # Re-lock lease row for safe updates
                    locked_lease = RentalLease.objects.select_for_update().get(pk=lease.id)

                    gpu_instance = locked_lease.gpu_instance
                    if not gpu_instance:
                        continue

                    model = gpu_instance.model

                    # 1. Calculate and invoice elapsed usage up to now
                    invoice_lease_usage(locked_lease, ended_at=now)
                    locked_lease.started_at = now
                    locked_lease.save(update_fields=["started_at"])

                    # 2. If pre-paid, verify credit depletion
                    is_prepaid = model.name.startswith("NVIDIA RTX") or model.name.startswith("NVIDIA L4")
                    if is_prepaid:
                        # Lock user credit row
                        credit, _ = UserCredit.objects.select_for_update().get_or_create(user=locked_lease.user)

                        if credit.balance <= Decimal("0.00"):
                            logger.warning(
                                "⚠️ SUSPENDING LEASE %s due to pre-paid credit depletion! Balance: %s",
                                locked_lease.id,
                                credit.balance,
                            )
                            # Suspend the lease and release physical GPU
                            locked_lease.status = RentalLeaseStatus.SUSPENDED_PAYMENT
                            locked_lease.ended_at = now
                            locked_lease.save(update_fields=["status", "ended_at"])

                            gpu_instance.status = GPUInstanceStatus.AVAILABLE
                            gpu_instance.save(update_fields=["status"])
                            continue

                    # 3. Generate metric snapshot if lease is still active
                    self.generate_metrics(locked_lease)
                    simulated_count += 1

            except Exception:
                logger.exception("Failed to process simulation tick for lease %s", lease.id)

        # 4. Check postpaid arrears for 5-day grace period
        try:
            from billing.models import Invoice, InvoiceStatus
            from billing.services.ledger import invoice_flat_fee
            from leases.utils.time_scale import get_simulated_duration
            from users.models import TenantProfile
            from users.orchestrators.lifecycle import freeze_tenant_account

            unpaid_invoices = Invoice.objects.filter(status=InvoiceStatus.UNPAID)
            for inv in unpaid_invoices:
                is_postpaid_a100_h100 = False
                if "A100" in inv.description or "H100" in inv.description:
                    is_postpaid_a100_h100 = True
                elif inv.lease_id:
                    try:
                        lease_obj = RentalLease.objects.select_related("gpu_instance__model").get(id=inv.lease_id)
                        if lease_obj.gpu_instance and (
                            "A100" in lease_obj.gpu_instance.model.name or "H100" in lease_obj.gpu_instance.model.name
                        ):
                            is_postpaid_a100_h100 = True
                    except RentalLease.DoesNotExist:
                        pass

                if is_postpaid_a100_h100:
                    simulated_duration = get_simulated_duration(inv.created_at, now)
                    if simulated_duration.total_seconds() >= 5 * 24 * 3600:
                        try:
                            profile = TenantProfile.objects.get(user=inv.user)
                            is_frozen = profile.freezed_at is not None
                        except TenantProfile.DoesNotExist:
                            is_frozen = False

                        if not is_frozen:
                            logger.warning(
                                "🚨 FREEZING tenant account for user %s due to unpaid postpaid invoice older than 5 simulated days!",
                                inv.user.username,
                            )
                            # Freeze account (keep_dedicated_gpus=False releases physical GPUs and completes leases)
                            freeze_tenant_account(inv.user.id, keep_dedicated_gpus=False)
                            # Generate standard Unfreeze Fee of $25.00
                            invoice_flat_fee(
                                user=inv.user,
                                lease_id=None,
                                amount=Decimal("25.00"),
                                description="Standard Unfreeze Fee",
                                is_prepaid=False,
                            )
        except Exception:
            logger.exception("Failed to check postpaid arrears during simulation tick")

        return simulated_count
