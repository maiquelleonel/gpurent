from rest_framework import serializers

from billing.models import Invoice, UserCredit


class UserCreditSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserCredit
        fields = ("id", "balance", "updated_at")
        read_only_fields = fields


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = ("id", "lease_id", "amount", "status", "description", "created_at")
        read_only_fields = fields


class PrepaidPackagePurchaseSerializer(serializers.Serializer):
    model_id = serializers.UUIDField()
    months = serializers.IntegerField(min_value=1, default=3)
    hours_per_month = serializers.IntegerField(min_value=1, default=730)
