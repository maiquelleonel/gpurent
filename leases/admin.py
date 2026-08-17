from django.contrib import admin

from leases.models import GPUInstance, GPUModel, MetricSnapshot, RentalLease


@admin.register(GPUModel)
class GPUModelAdmin(admin.ModelAdmin):
    list_display = ("name", "vram_capacity_gb", "price_per_hour")
    search_fields = ("name",)
    readonly_fields = ("id",)


@admin.register(GPUInstance)
class GPUInstanceAdmin(admin.ModelAdmin):
    list_display = ("serial_number", "model", "status", "is_dedicated")
    list_filter = ("status", "is_dedicated", "model")
    search_fields = ("serial_number",)
    readonly_fields = ("id",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("model")


@admin.register(RentalLease)
class RentalLeaseAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "gpu_instance",
        "status",
        "started_at",
        "ended_at",
        "total_billed_amount",
    )
    list_filter = ("status", "started_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("id",)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "gpu_instance__model")


@admin.register(MetricSnapshot)
class MetricSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "gpu_instance",
        "vram_used_gb",
        "compute_load_pct",
        "temperature_c",
        "is_thermal_alert",
        "timestamp",
    )
    list_filter = ("is_thermal_alert", "timestamp")
    search_fields = ("gpu_instance__serial_number",)
    readonly_fields = (
        "id",
        "gpu_instance",
        "vram_used_gb",
        "compute_load_pct",
        "temperature_c",
        "is_thermal_alert",
        "timestamp",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("gpu_instance")
