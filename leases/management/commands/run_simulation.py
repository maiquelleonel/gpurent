import logging
import time

from django.core.management.base import BaseCommand

from billing.models import UserCredit
from billing.services.ledger import is_prepaid_model
from leases.models import RentalLease, RentalLeaseStatus
from leases.simulation.worker import MetricsSimulatorWorker

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Runs the background GPU consumption simulator loop for active leases."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=float,
            default=5.0,
            help="Simulation tick interval in seconds (default: 5.0)",
        )
        parser.add_argument(
            "--run-agents",
            action="store_true",
            help="Run programmatic Simulated Client Agent Engine on startup",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        self.stdout.write(
            self.style.SUCCESS(f"Starting background GPU Metrics Simulator. Tick interval: {interval} seconds.")
        )
        self.stdout.write("Press Ctrl+C to terminate gracefully.")

        if options["run_agents"]:
            self.stdout.write(self.style.WARNING("Booting Simulated Client Agent Engine..."))
            from leases.simulation.agent_engine import AgentEngine

            agent_engine = AgentEngine()
            success = agent_engine.run_all()
            if success:
                self.stdout.write(self.style.SUCCESS("All agent personas completed successfully!"))
            else:
                self.stdout.write(self.style.ERROR("Some agent personas failed."))

            agent_engine.spawn_persistent_demo_leases()
            self.stdout.write(self.style.SUCCESS("Active demo workloads initialized for live dashboard."))

        worker = MetricsSimulatorWorker(interval=interval)

        try:
            while True:
                start_time = time.time()
                count = worker.tick()
                if count > 0:
                    self.stdout.write(self.style.SUCCESS(f"Simulated telemetries for {count} active lease(s):"))
                    active_leases = RentalLease.objects.filter(status=RentalLeaseStatus.ACTIVE).select_related(
                        "user", "gpu_instance__model"
                    )
                    for lease in active_leases:
                        if lease.gpu_instance and lease.gpu_instance.model:
                            model_name = lease.gpu_instance.model.name
                            is_prepaid = is_prepaid_model(lease.gpu_instance.model)
                        else:
                            model_name = "N/A"
                            is_prepaid = False
                        tier = "Pre-paid" if is_prepaid else "Post-paid"
                        credit = UserCredit.objects.filter(user=lease.user).first()
                        balance_str = f"${credit.balance}" if credit else "$0.00"
                        self.stdout.write(
                            f"   • Lease {str(lease.id)[:8]}.. | User: {lease.user.username} | "
                            f"{model_name} [{tier}] | Billed: ${lease.total_billed_amount} | "
                            f"Balance: {balance_str}"
                        )

                # Adjust sleep time to compensate for the tick processing duration
                elapsed = time.time() - start_time
                sleep_time = max(0.1, interval - elapsed)
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nTermination signal received. Shutting down simulator worker..."))

        self.stdout.write(self.style.SUCCESS("Simulator worker shutdown successfully!"))
