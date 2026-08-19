import logging
import uuid

from leases.models import GPUInstance, GPUInstanceStatus, GPUModel, SystemAlert

logger = logging.getLogger(__name__)


def auto_provision_gpu(model_name: str | None = None, is_dedicated: bool = False) -> GPUInstance:
    """
    Provisions a new physical GPU card into the inventory catalog as AVAILABLE,
    and creates a real-time toast SystemAlert to notify administrators.
    """
    if model_name:
        model = GPUModel.objects.filter(name__icontains=model_name).first()
    else:
        # Default or pick a high-demand model (RTX 4090, L4, A100, H100)
        model = GPUModel.objects.order_by("?").first()

    if not model:
        raise ValueError("No GPU models available in catalog to provision.")

    tag = model.name.split()[1] if len(model.name.split()) > 1 else "GPU"
    tag = "".join(c for c in tag if c.isalnum()).upper()
    random_suffix = uuid.uuid4().hex[:6].upper()
    serial_number = f"GPU-{tag}-{random_suffix}"

    instance = GPUInstance.objects.create(
        model=model,
        serial_number=serial_number,
        status=GPUInstanceStatus.AVAILABLE,
        is_dedicated=is_dedicated,
    )

    # Trigger real-time SystemAlert toast
    try:
        SystemAlert.objects.create(
            alert_type="provisioning",
            message=f"🚀 New GPU provisioned and ready for lease: {model.name} (Serial: {instance.serial_number})",
        )
    except Exception:
        logger.exception("Failed to create GPU provisioning SystemAlert")

    logger.info("Auto-provisioned new GPU instance: %s (%s)", instance.serial_number, model.name)
    return instance
