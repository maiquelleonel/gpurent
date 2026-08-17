from rest_framework import serializers

from leases.models import GPUInstance, GPUModel, RentalLease


class GPUModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = GPUModel
        fields = ("id", "name", "vram_capacity_gb", "price_per_hour")
        read_only_fields = fields


class GPUInstanceSerializer(serializers.ModelSerializer):
    model = GPUModelSerializer(read_only=True)

    class Meta:
        model = GPUInstance
        fields = ("id", "serial_number", "status", "is_dedicated", "model")
        read_only_fields = fields


class RentalLeaseSerializer(serializers.ModelSerializer):
    gpu_instance = GPUInstanceSerializer(read_only=True)

    class Meta:
        model = RentalLease
        fields = (
            "id",
            "gpu_instance",
            "status",
            "started_at",
            "ended_at",
            "total_billed_amount",
            "volume_discount_applied",
        )
        read_only_fields = fields
