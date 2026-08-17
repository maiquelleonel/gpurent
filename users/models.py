import uuid

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class TokenUsage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    api_token = models.CharField(max_length=255, db_index=True)
    endpoint = models.CharField(max_length=255)
    request_timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    response_status = models.PositiveIntegerField()

    class Meta:
        verbose_name = _("Token Usage")
        verbose_name_plural = _("Token Usages")
        ordering = ["-request_timestamp"]

    def __str__(self) -> str:
        return f"{self.api_token} - {self.endpoint} ({self.response_status})"
