from django.contrib import admin

from users.models import TokenUsage


@admin.register(TokenUsage)
class TokenUsageAdmin(admin.ModelAdmin):
    list_display = ("api_token", "endpoint", "request_timestamp", "response_status")
    list_filter = ("response_status", "request_timestamp")
    search_fields = ("api_token", "endpoint")
    readonly_fields = ("id", "api_token", "endpoint", "request_timestamp", "response_status")
