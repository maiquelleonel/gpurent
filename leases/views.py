import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import render
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from billing.models import ClientUsageCycle, UserCredit
from leases.models import GPUInstanceStatus, GPUModel, MetricSnapshot, RentalLease, RentalLeaseStatus, SystemAlert
from leases.orchestrators.lease_flow import provision_lease
from leases.orchestrators.upgrade_flow import upgrade_lease_tier
from leases.serializers import RentalLeaseSerializer
from leases.services.fleet_analytics import get_fleet_snapshot

logger = logging.getLogger(__name__)


class LeaseViewSet(viewsets.ViewSet):
    """
    ViewSet that manages GPU leases, catalog queries, upgrades, and fleet analytics dashboards.
    """

    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"])
    def catalog(self, request):
        """
        Lists available GPU Models along with their hourly rates and the count
        of currently AVAILABLE physical instances.
        """
        # Annotate models with available physical instance count
        models_qs = GPUModel.objects.annotate(
            available_count=Count(
                "instances",
                filter=Q(instances__status=GPUInstanceStatus.AVAILABLE),
            )
        )

        data = [
            {
                "id": str(m.id),
                "name": m.name,
                "vram_capacity_gb": m.vram_capacity_gb,
                "price_per_hour": str(m.price_per_hour),
                "available_instances_count": m.available_count,
            }
            for m in models_qs
        ]
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"])
    def rent(self, request):
        """
        Rents a GPU instance.
        Payload parameters:
          - 'gpu_model_id': UUID of requested GPU Model
          - 'is_dedicated': bool (default: False)
          - 'card_token': string (optional, for dedicated upfront auth)
        """
        model_id = request.data.get("gpu_model_id")
        is_dedicated = request.data.get("is_dedicated", False)
        card_token = request.data.get("card_token", None)

        if not model_id:
            return Response({"error": "gpu_model_id parameter is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            lease = provision_lease(
                user=request.user,
                gpu_model_id=model_id,
                is_dedicated=is_dedicated,
                card_token=card_token,
            )
            serializer = RentalLeaseSerializer(lease)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"])
    def upgrade(self, request):
        """
        Upgrades an active lease to a more powerful GPU Model mid-lease.
        Payload parameters:
          - 'lease_id': UUID of the lease to upgrade
          - 'target_model_id': UUID of the target GPU Model
        """
        lease_id = request.data.get("lease_id")
        target_model_id = request.data.get("target_model_id")

        if not lease_id or not target_model_id:
            return Response(
                {"error": "Both lease_id and target_model_id parameters are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            lease = upgrade_lease_tier(lease_id=lease_id, target_model_id=target_model_id)
            serializer = RentalLeaseSerializer(lease)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["get"])
    def fleet_snapshot(self, request):
        """
        Real-time monitoring analytics dashboard endpoint.
        Returns aggregate fleet snapshot metrics with zero N+1 database queries.
        """
        snapshot = get_fleet_snapshot()
        return Response(snapshot, status=status.HTTP_200_OK)


@staff_member_required
def admin_live_alerts_endpoint(request):
    """
    HTMX polling endpoint for real-time stackable toast admin notifications.
    Fetches all unread SystemAlert records, formats them as beautiful yellow Django-styled alerts,
    marks them as read in the DB, and returns the HTML fragment.
    """
    unread_alerts = SystemAlert.objects.filter(is_read=False).order_by("created_at")

    if not unread_alerts.exists():
        # Return empty response if no new alerts
        return HttpResponse("")

    html_fragments = []
    for alert in unread_alerts:
        # Determine specific alert title prefix, icon and colors
        alert_icon = "💵"
        alert_title = "SYSTEM NOTICE"
        border_color = "#ca8a04"  # yellow-600
        bg_color = "#fef9c3"  # yellow-100

        if alert.alert_type == "delete":
            alert_icon = "❌"
            alert_title = "SYSTEM DELETED"
            border_color = "#dc2626"  # red-600
            bg_color = "#fee2e2"  # red-100
        elif alert.alert_type == "billing":
            alert_icon = "💵"
            alert_title = "BILLING NOTICE"
            border_color = "#16a34a"  # green-600
            bg_color = "#dcfce7"  # green-100
        elif alert.alert_type == "thermal":
            alert_icon = "🔥"
            alert_title = "THERMAL WATCHDOG"
            border_color = "#ea580c"  # orange-600
            bg_color = "#ffedd5"  # orange-100
        elif alert.alert_type in ["provisioning", "hardware"]:
            alert_icon = "🚀"
            alert_title = "FLEET PROVISIONED"
            border_color = "#2563eb"  # blue-600
            bg_color = "#dbeafe"  # blue-100

        font_stack = "'Roboto', 'Lucida Grande', 'DejaVu Sans', 'Bitstream Vera Sans', Verdana, Arial, sans-serif"
        card_style = (
            f"box-sizing: border-box; width: 100%; max-width: 240px; background-color: {bg_color}; "
            f"border: 1px solid {border_color}; color: #000000; padding: 12px; font-family: {font_stack}; "
            f"font-size: 13px; line-height: 1.5; transition: opacity 0.5s ease-out; "
            f"box-shadow: 0 2px 4px rgba(0,0,0,0.1); border-left: 5px solid {border_color};"
        )
        header_style = (
            "font-weight: bold; margin-bottom: 5px; display: flex; justify-content: space-between; "
            "align-items: center; border-bottom: 1px solid rgba(0,0,0,0.1); padding-bottom: 4px;"
        )
        close_btn_style = "cursor: pointer; font-weight: bold; font-size: 16px; line-height: 1;"
        close_onclick = (
            "var toast=this.closest('.django-admin-alert'); toast.style.opacity='0'; "
            "setTimeout(function(){ toast.remove(); }, 500);"
        )

        toast_html = f"""
        <div class="django-admin-alert" style="{card_style}">
          <div style="{header_style}">
            <span style="display: flex; align-items: center; gap: 4px;">{alert_icon} {alert_title}</span>
            <span style="{close_btn_style}" onclick="{close_onclick}">&times;</span>
          </div>
          <div style="word-wrap: break-word;">{alert.message}</div>
          <script>
            // Automatic fade-out and self-destruction after 4 seconds
            (function() {{
              var alertEl = document.currentScript.parentNode;
              setTimeout(function() {{
                if (alertEl) {{
                  alertEl.style.opacity = '0';
                  setTimeout(function() {{
                    alertEl.remove();
                  }}, 500);
                }}
              }}, 4000);
            }})();
          </script>
        </div>
        """
        html_fragments.append(toast_html)
        alert.is_read = True
        alert.save(update_fields=["is_read"])

    return HttpResponse("\n".join(html_fragments))


@staff_member_required
def admin_live_dashboard_endpoint(request):
    """
    HTMX polling endpoint for real-time admin dashboard metrics.
    Renders live client balances, active GPU/compute hardware telemetry,
    and client consumption cycles.
    """
    user_credits = UserCredit.objects.select_related("user").order_by("user__username")
    active_leases = (
        RentalLease.objects.filter(status=RentalLeaseStatus.ACTIVE)
        .select_related("user", "gpu_instance__model")
        .order_by("-started_at")
    )

    gpu_metrics = []
    for lease in active_leases:
        if lease.gpu_instance:
            latest_snap = MetricSnapshot.objects.filter(gpu_instance=lease.gpu_instance).order_by("-timestamp").first()
            gpu_metrics.append(
                {
                    "lease": lease,
                    "gpu": lease.gpu_instance,
                    "model": lease.gpu_instance.model,
                    "snapshot": latest_snap,
                }
            )

    usage_cycles = ClientUsageCycle.objects.filter(is_active=True).select_related("client").order_by("-created_at")[:25]

    return render(
        request,
        "admin/live_dashboard_fragment.html",
        {
            "user_credits": user_credits,
            "gpu_metrics": gpu_metrics,
            "usage_cycles": usage_cycles,
        },
    )
