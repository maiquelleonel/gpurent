import logging
from decimal import Decimal

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class BillingException(Exception):
    """Base exception for billing and payment processing errors."""

    pass


class PaymentTimeoutException(BillingException):
    """Raised when the payment gateway request times out."""

    pass


class PaymentGatewayException(BillingException):
    """Raised when there's an API or communication failure with the payment gateway."""

    pass


def process_payment(user_id, amount: Decimal, card_token: str) -> str:
    """
    Submits a card charge request to the offline mock payment gateway.
    Enforces a strict 5.0 second timeout to prevent thread blocking (compliance with guardian.W006).
    Returns "PAID" if successful or "FAILED" if declined.
    """
    base_url = getattr(settings, "MOCK_PAYMENT_BASE_URL", "http://localhost:12111")
    url = f"{base_url}/v1/charges"

    data = {
        "amount": int(amount * 100),  # Convert to cents
        "currency": "usd",
        "source": card_token,
        "description": f"Charge for user {user_id}",
    }

    try:
        # Enforce strict 5.0 seconds timeout (connection and read timeout)
        response = httpx.post(url, data=data, timeout=5.0)

        # Handle mock declines based on specific tokens or responses
        if response.status_code == 402 or "decline" in card_token.lower():
            logger.warning("Payment processing declined for user %s, amount %s.", user_id, amount)
            return "FAILED"

        if response.status_code >= 400:
            logger.error("Payment gateway returned error status: %s", response.status_code)
            return "FAILED"

        logger.info("Payment of %s processed successfully for user %s.", amount, user_id)
        return "PAID"

    except httpx.TimeoutException as e:
        logger.exception("Timeout contacting payment gateway at %s", url)
        raise PaymentTimeoutException("Payment gateway request timed out. Please try again.") from e
    except httpx.RequestError as e:
        logger.exception("HTTP error contacting payment gateway at %s", url)
        raise PaymentGatewayException("Failed to communicate with payment gateway.") from e


def process_refund(invoice_id) -> bool:
    """
    Calls mock refund endpoint to process a transaction refund.
    """
    base_url = getattr(settings, "MOCK_PAYMENT_BASE_URL", "http://localhost:12111")
    url = f"{base_url}/v1/refunds"

    data = {
        "charge": str(invoice_id),
    }

    try:
        response = httpx.post(url, data=data, timeout=5.0)
        if response.status_code == 200 or response.status_code == 201:
            logger.info("Successfully processed refund for invoice %s.", invoice_id)
            return True
        logger.error("Refund failed at gateway: Status %s", response.status_code)
        return False
    except httpx.TimeoutException as e:
        logger.exception("Timeout processing refund for invoice %s", invoice_id)
        raise PaymentTimeoutException("Refund request timed out.") from e
    except httpx.RequestError as e:
        logger.exception("HTTP error processing refund for invoice %s", invoice_id)
        raise PaymentGatewayException("Failed to communicate refund request to gateway.") from e
