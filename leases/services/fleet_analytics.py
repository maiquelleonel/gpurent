from django.db.models import Avg, Sum

from leases.models import GPUInstance, GPUInstanceStatus, GPUModel, RentalLease, RentalLeaseStatus


def get_fleet_snapshot() -> dict:
    """
    Computes database-optimized aggregations for real-time dashboard stats.
    Fulfills US07 Task 7.1 with zero N+1 queries.
    """
    active_leases_qs = RentalLease.objects.filter(status=RentalLeaseStatus.ACTIVE)

    # 1. Count total active leases
    active_leases_count = active_leases_qs.count()

    # 2. Count active concurrent clients (distinct users with active leases)
    active_clients_count = active_leases_qs.values("user").distinct().count()

    # 3. Count available vs leased physical GPU cards
    available_cards_count = GPUInstance.objects.filter(status=GPUInstanceStatus.AVAILABLE).count()
    leased_cards_count = GPUInstance.objects.filter(status=GPUInstanceStatus.LEASED).count()

    # 4. Calculate total allocated VRAM
    total_allocated_vram = (
        active_leases_qs.aggregate(total_vram=Sum("gpu_instance__model__vram_capacity_gb"))["total_vram"] or 0
    )

    # 5. Calculate average temperature per model type using DB-level joins
    model_temperatures = GPUModel.objects.annotate(avg_temp=Avg("instances__snapshots__temperature_c")).values(
        "id", "name", "avg_temp"
    )

    avg_temp_per_model = {
        item["name"]: (float(item["avg_temp"]) if item["avg_temp"] is not None else 0.0) for item in model_temperatures
    }

    return {
        "active_leases_count": active_leases_count,
        "active_clients_count": active_clients_count,
        "available_cards_count": available_cards_count,
        "leased_cards_count": leased_cards_count,
        "total_allocated_vram": int(total_allocated_vram),
        "avg_temp_per_model": avg_temp_per_model,
    }
