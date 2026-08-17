import logging

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q
from django.http import HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from leases.models import GPUInstanceStatus, GPUModel, SystemAlert
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
    Fetches all unread SystemAlert records, formats them as Bootstrap toast HTML,
    marks them as read in the DB, and returns the HTML fragment.
    """
    unread_alerts = SystemAlert.objects.filter(is_read=False).order_by("created_at")

    if not unread_alerts.exists():
        # Return empty response if no new alerts
        return HttpResponse("")

    html_fragments = []
    for alert in unread_alerts:
        # Create standard Bootstrap Toast HTML
        bg_color = "bg-primary"
        if alert.alert_type == "delete":
            bg_color = "bg-danger"
        elif alert.alert_type == "billing":
            bg_color = "bg-success"

        toast_html = f"""
        <div class="toast show align-items-center text-white {bg_color} border-0 mb-2 shadow"
             role="alert" aria-live="assertive" aria-atomic="true"
             style="min-width: 250px; transition: opacity 0.5s ease-out;">
          <div class="d-flex">
            <div class="toast-body">
              <strong>{alert.alert_type.upper()}:</strong> {alert.message}
            </div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto"
                    data-bs-dismiss="toast" aria-label="Close"
                    onclick="this.closest('.toast').remove();"></button>
          </div>
        </div>
        <script>
          // Automatic fade-out and self-destruction after 4 seconds
          setTimeout(function() {{
            var toast = document.currentScript.previousElementSibling;
            if (toast) {{
              toast.style.opacity = '0';
              setTimeout(function() {{ toast.remove(); }}, 500);
            }}
          }}, 4000);
        </script>
        """
        html_fragments.append(toast_html)
        alert.is_read = True
        alert.save(update_fields=["is_read"])

    return HttpResponse("\n".join(html_fragments))
