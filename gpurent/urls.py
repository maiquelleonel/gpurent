from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from billing.views import BillingViewSet, stripe_webhook_endpoint
from leases.views import LeaseViewSet, admin_live_alerts_endpoint
from users.views import TenantViewSet

router = DefaultRouter()
router.register(r"tenants", TenantViewSet, basename="tenant")
router.register(r"leases", LeaseViewSet, basename="lease")
router.register(r"billing", BillingViewSet, basename="billing")

urlpatterns = [
    path("admin/api/live-alerts/", admin_live_alerts_endpoint, name="admin_live_alerts"),
    path("api/billing/webhooks/stripe/", stripe_webhook_endpoint, name="stripe_webhook"),
    path("admin/", admin.site.urls),
    path("api/v1/", include(router.urls)),
]
