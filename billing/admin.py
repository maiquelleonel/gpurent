from django.contrib import admin

from billing.models import Invoice, UserCredit


@admin.register(UserCredit)
class UserCreditAdmin(admin.ModelAdmin):
    list_display = ("user", "balance", "updated_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("id", "updated_at")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "lease_id", "amount", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("user__username", "user__email", "description")
    readonly_fields = ("id", "created_at")
