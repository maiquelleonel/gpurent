import logging
from decimal import Decimal

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from billing.models import UserCredit
from users.orchestrators.lifecycle import (
    freeze_tenant_account,
    soft_delete_tenant,
    unfreeze_tenant_account,
)
from users.serializers import UserRegisterSerializer

logger = logging.getLogger(__name__)


class TenantViewSet(viewsets.ViewSet):
    """
    ViewSet that manages the Tenant account lifecycles: registration, freezing,
    unfreezing, and soft-deletion of accounts.
    """

    @action(detail=False, methods=["post"], permission_classes=[AllowAny], authentication_classes=[])
    def register(self, request):
        """
        Public endpoint: registers a new User account, auto-generates their TenantProfile
        (via django signals), enqueues their welcome email, and tops up their pre-paid credit
        balance with $50.00.
        """
        serializer = UserRegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()

            # Initialize pre-paid UserCredit with $50.00 starting balance
            UserCredit.objects.create(user=user, balance=Decimal("50.00"))
            logger.info("Initialized $50.00 credit balance for new registered user: %s", user.username)

            # Trigger real-time SystemAlert for admin dashboard
            from leases.models import SystemAlert

            SystemAlert.objects.create(
                alert_type="signup",
                message=f"New tenant registered: {user.username} (Email: {user.email})",
            )

            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated])
    def freeze(self, request):
        """
        Authenticated endpoint: freezes the active Tenant account.
        Accepts 'keep_dedicated_gpus' (bool) parameter to determine reservation policies.
        """
        keep_dedicated = request.data.get("keep_dedicated_gpus", False)
        try:
            profile = freeze_tenant_account(request.user.id, keep_dedicated_gpus=keep_dedicated)
            return Response(
                {"status": "account_frozen", "keep_dedicated_gpus": profile.keep_dedicated_gpus},
                status=status.HTTP_200_OK,
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated])
    def unfreeze(self, request):
        """
        Authenticated endpoint: reactivates a frozen Tenant account.
        Bypasses API shielding checks to prevent lockouts.
        """
        try:
            profile = unfreeze_tenant_account(request.user.id)
            return Response(
                {"status": "account_active", "keep_dedicated_gpus": profile.keep_dedicated_gpus},
                status=status.HTTP_200_OK,
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["delete"], permission_classes=[IsAuthenticated])
    def delete_account(self, request):
        """
        Authenticated endpoint: executes clean soft-deletion of the Tenant account.
        Verifies there are zero unpaid liabilities before deletion.
        """
        try:
            soft_delete_tenant(request.user.id)
            return Response({"status": "account_soft_deleted"}, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
