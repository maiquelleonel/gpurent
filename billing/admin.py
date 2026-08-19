from django.contrib import admin

from billing.models import ClientUsageCycle, Invoice, UserCredit


@admin.register(UserCredit)
class UserCreditAdmin(admin.ModelAdmin):
    list_display = ("user", "balance", "frozen_prepaid_balance", "updated_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("id", "updated_at")


@admin.register(ClientUsageCycle)
class ClientUsageCycleAdmin(admin.ModelAdmin):
    list_display = (
        "client",
        "plan_type",
        "gpu",
        "hours_consumed",
        "total_consumption",
        "total_credits",
        "cycle_ended_at_display",
        "is_active",
    )
    list_filter = ("plan_type", "is_active", "gpu")
    search_fields = ("client__username", "client__email", "gpu")
    readonly_fields = (
        "id",
        "client",
        "plan_type",
        "gpu",
        "hours_consumed",
        "total_consumption",
        "total_credits",
        "cycle_started_at",
        "cycle_ended_at",
        "is_active",
        "created_at",
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("client")

    @admin.display(description="Cycle Ended At")
    def cycle_ended_at_display(self, obj):
        return obj.cycle_ended_at if obj.cycle_ended_at else "-"


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "lease_id", "amount", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__username", "user__email", "description")
    readonly_fields = ("id", "created_at")
