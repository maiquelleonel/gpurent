import logging
import time

from django.core.management.base import BaseCommand

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

            success = AgentEngine().run_all()
            if success:
                self.stdout.write(self.style.SUCCESS("All agent personas completed successfully!"))
            else:
                self.stdout.write(self.style.ERROR("Some agent personas failed."))

        worker = MetricsSimulatorWorker(interval=interval)

        try:
            while True:
                start_time = time.time()
                count = worker.tick()
                if count > 0:
                    self.stdout.write(self.style.SUCCESS(f"Simulated telemetries for {count} active lease(s)."))

                # Adjust sleep time to compensate for the tick processing duration
                elapsed = time.time() - start_time
                sleep_time = max(0.1, interval - elapsed)
                time.sleep(sleep_time)

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nTermination signal received. Shutting down simulator worker..."))

        self.stdout.write(self.style.SUCCESS("Simulator worker shutdown successfully!"))
