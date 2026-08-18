import logging
from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from django.db import transaction

T = TypeVar("T")
logger = logging.getLogger(__name__)


class BaseOrchestrator(ABC, Generic[T]):
    """
    Abstract Base Class representing the core orchestrator for the entire gpurent project.
    Provides project-wide standardization, code reuse (DRY) for atomic transactions,
    standardized logging/auditing, and consistent error handling.
    """

    def execute(self) -> T:
        """
        Executes the business process wrapped in an atomic database transaction.
        Provides centralized logging and error capturing.
        """
        orchestrator_name = self.__class__.__name__
        logger.info("🎬 Starting orchestrator process: %s", orchestrator_name)

        try:
            with transaction.atomic():
                result = self.run()
                logger.info("✅ Successfully completed orchestrator process: %s", orchestrator_name)
                return result
        except Exception as e:
            logger.error("❌ Error during orchestrator process %s: %s", orchestrator_name, str(e))
            raise e

    @abstractmethod
    def run(self) -> T:
        """
        Abstract method containing the actual business steps of the orchestrator.
        Must be implemented by subclasses and is automatically run inside a transaction.
        """
        pass
