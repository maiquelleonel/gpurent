import logging
import random
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from billing.services.ledger import record_fractional_usage
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
            try:
                from leases.models import SystemAlert

                SystemAlert.objects.create(
                    alert_type="hardware",
                    message=(
                        f"🔥 THERMAL ALERT on GPU {gpu_instance.serial_number} ({model.name})! "
                        f"Temperature reached {temperature}°C on tenant {lease.user.username}."
                    ),
                )
            except Exception:
                logger.exception("Failed to create thermal SystemAlert")

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

    def _settle_eligible_postpaid_invoices(self, tick_time):
        """
        Simulates enterprise clients paying off their issued postpaid invoices on subsequent ticks.
        """
        from billing.models import Invoice, InvoiceStatus
        from billing.services.ledger import settle_postpaid_invoice

        unpaid_postpaid_invoices = Invoice.objects.filter(
            status=InvoiceStatus.UNPAID,
            description__icontains="30-Day Postpaid",
            created_at__lt=tick_time - timezone.timedelta(seconds=1),
        )
        for inv in unpaid_postpaid_invoices:
            try:
                settle_postpaid_invoice(inv.id)
                logger.info("Settled postpaid invoice %s for user %s", inv.id, inv.user.username)
            except Exception:
                logger.exception("Failed to auto-settle postpaid invoice %s", inv.id)

    def _process_dynamic_fleet_and_tenants(self):
        """
        Orchestrates dynamic fleet auto-provisioning and dynamic client lease onboarding.
        """
        from django.contrib.auth import get_user_model

        from billing.models import UserCredit
        from leases.models import GPUInstance, GPUInstanceStatus, RentalLease, RentalLeaseStatus
        from leases.orchestrators.lease_flow import provision_lease
        from leases.services.fleet_provisioning import auto_provision_gpu

        User = get_user_model()
        available_count = GPUInstance.objects.filter(status=GPUInstanceStatus.AVAILABLE).count()

        # 1. Auto-provision GPU if catalog capacity is constrained
        if available_count < 2:
            try:
                auto_provision_gpu()
            except Exception:
                logger.exception("Failed to auto-provision GPU during simulation tick")

        # 2. Dynamic client onboarding if available GPUs exist
        available_gpu = GPUInstance.objects.filter(status=GPUInstanceStatus.AVAILABLE).select_related("model").first()
        active_dynamic_leases_count = RentalLease.objects.filter(
            status=RentalLeaseStatus.ACTIVE,
            user__username__startswith="dyn_client_",
        ).count()

        if available_gpu and active_dynamic_leases_count < 3 and random.random() < 0.35:
            client_num = random.randint(100, 999)
            username = f"dyn_client_{client_num}"
            try:
                user, _ = User.objects.get_or_create(username=username)
                UserCredit.objects.update_or_create(
                    user=user,
                    defaults={
                        "balance": Decimal("60.00"),
                        "starting_balance": Decimal("60.00"),
                        "low_credit_alert_sent": False,
                    },
                )
                provision_lease(user, available_gpu.model.id, is_dedicated=False)
                logger.info("Dynamic client %s joined and rented %s!", username, available_gpu.model.name)
            except Exception:
                logger.exception("Failed to onboard dynamic client %s", username)

    def tick(self) -> int:
        """
        Executes a single simulation tick:
        1. Accumulates fractional usage in real-time on active ClientUsageCycles.
        2. Deducts credits from prepaid accounts and suspends depleted leases.
        3. Generates and persists metric snapshots for remaining active leases.
        4. Auto-settles eligible postpaid invoices with toast alerts.
        5. Handles dynamic fleet provisioning and dynamic client onboarding.
        6. Enforces postpaid arrears late-payment freeze if invoices exceed 5 days.
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

                    # 1. Record fractional usage and check depletion
                    cost, is_depleted = record_fractional_usage(locked_lease, ended_at=now)

                    if is_depleted:
                        logger.warning(
                            "⚠️ SUSPENDING LEASE %s due to pre-paid credit depletion!",
                            locked_lease.id,
                        )
                        locked_lease.status = RentalLeaseStatus.SUSPENDED_PAYMENT
                        locked_lease.ended_at = now
                        locked_lease.save(update_fields=["status", "ended_at"])

                        gpu_instance.status = GPUInstanceStatus.AVAILABLE
                        gpu_instance.save(update_fields=["status"])

                        try:
                            from billing.models import UserCredit
                            from leases.models import SystemAlert

                            credit = UserCredit.objects.filter(user=locked_lease.user).first()
                            bal = credit.balance if credit else Decimal("0.00")
                            SystemAlert.objects.create(
                                alert_type="billing",
                                message=(
                                    f"🚨 Prepaid lease suspended for tenant {locked_lease.user.username}: "
                                    f"Balance depleted (${bal}). GPU {gpu_instance.serial_number} released."
                                ),
                            )
                        except Exception:
                            logger.exception("Failed to create credit depletion SystemAlert")

                        continue

                    # 2. Generate metric snapshot if lease is still active
                    self.generate_metrics(locked_lease)
                    simulated_count += 1

            except Exception:
                logger.exception("Failed to process simulation tick for lease %s", lease.id)

        # 4. Auto-settle eligible postpaid invoices
        self._settle_eligible_postpaid_invoices(now)

        # 5. Process dynamic fleet provisioning and dynamic client onboarding
        self._process_dynamic_fleet_and_tenants()

        # 6. Check postpaid arrears for 5-day grace period
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
                                "🚨 FREEZING tenant account for user %s due to unpaid postpaid invoice "
                                "older than 5 simulated days!",
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
