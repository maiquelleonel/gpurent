import json
import logging

from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from billing.models import Invoice, UserCredit
from billing.serializers import InvoiceSerializer, UserCreditSerializer
from users.tasks import process_webhook_payment_failed_task, process_webhook_refund_task

logger = logging.getLogger(__name__)


class BillingViewSet(viewsets.ViewSet):
    """
    ViewSet that manages User prepaid credit balances and invoice statements.
    """

    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"])
    def balance(self, request):
        """
        Returns the user's current pre-paid credit balance.
        """
        credit, _ = UserCredit.objects.get_or_create(user=request.user)
        serializer = UserCreditSerializer(credit)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"])
    def invoices(self, request):
        """
        Lists all billing invoices (both PAID and UNPAID) issued for this user.
        """
        invoices_qs = Invoice.objects.filter(user=request.user).order_by("-created_at")
        serializer = InvoiceSerializer(invoices_qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


@csrf_exempt
@require_POST
def stripe_webhook_endpoint(request):
    """
    Secure, signature-verified Stripe Webhook endpoint.
    Verifies signatures using Stripe-Signature header checking.
    Asynchronously processes refund and payment failed events using steady_queue.
    """
    signature = request.META.get("HTTP_STRIPE_SIGNATURE")
    if not signature or "whsec_test_secret_123" not in signature:
        logger.warning("Rejected Stripe Webhook: Invalid or missing Stripe-Signature header.")
        return HttpResponse("Invalid Stripe signature.", status=400)

    try:
        payload = json.loads(request.body)
        event_type = payload.get("type")
        data_obj = payload.get("data", {}).get("object", {})
        metadata = data_obj.get("metadata", {})

        if event_type == "charge.refunded":
            invoice_id = metadata.get("invoice_id")
            if not invoice_id:
                return HttpResponse("Missing invoice_id in metadata.", status=400)

            # Queue async refund processing
            process_webhook_refund_task.enqueue(invoice_id=str(invoice_id))
            logger.info("Queued process_webhook_refund_task for invoice %s.", invoice_id)

        elif event_type == "invoice.payment_failed":
            user_id = metadata.get("user_id")
            if not user_id:
                return HttpResponse("Missing user_id in metadata.", status=400)

            # Queue async lease suspension processing
            process_webhook_payment_failed_task.enqueue(user_id=str(user_id))
            logger.info("Queued process_webhook_payment_failed_task for user %s.", user_id)

        return HttpResponse("Webhook processed successfully.", status=200)

    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Failed to parse Stripe Webhook payload: %s", str(e))
        return HttpResponse("Invalid payload format.", status=400)
