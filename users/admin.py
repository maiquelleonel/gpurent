from django.contrib import admin

from users.models import TenantProfile, TokenUsage


@admin.register(TokenUsage)
class TokenUsageAdmin(admin.ModelAdmin):
    list_display = ("api_token", "endpoint", "request_timestamp", "response_status")
    list_filter = ("response_status", "request_timestamp")
    search_fields = ("api_token", "endpoint")
    readonly_fields = ("id", "api_token", "endpoint", "request_timestamp", "response_status")


@admin.register(TenantProfile)
class TenantProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "freezed_at", "deleted_at", "keep_dedicated_gpus")
    list_filter = ("keep_dedicated_gpus", "freezed_at", "deleted_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("id",)
