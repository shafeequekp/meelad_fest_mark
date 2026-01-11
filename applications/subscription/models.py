from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from applications.accounts.models import Madrasa


class Subscription(models.Model):
    institution = models.ForeignKey(Madrasa, on_delete=models.CASCADE)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=False)

    def activate_for_year(self):
        self.start_date = timezone.now()
        self.end_date = self.start_date + timedelta(days=365)
        self.active = True
        self.save()

    @property
    def is_active(self):
        """Returns True if subscription end_date is in the future."""
        if self.end_date is None:
            return False
        return self.end_date >= timezone.now()

    def __str__(self):
        return f"{self.institution} subscription ({'active' if self.active else 'inactive'})"


class Transaction(models.Model):
    ORDER_STATUS = (
        ("CREATED", "Created"),
        ("PENDING", "Pending"),
        ("PAID", "Paid"),
        ("FAILED", "Failed"),
        ("CANCELLED", "Cancelled"),
    )

    institution = models.ForeignKey(Madrasa, on_delete=models.CASCADE)
    order_id = models.CharField(max_length=128, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="INR")
    cf_payment_id = models.CharField(max_length=128, blank=True, null=True)
    status = models.CharField(max_length=20, choices=ORDER_STATUS, default="CREATED")
    raw_response = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def mark_paid(self, cf_payment_id=None):
        self.status = "PAID"
        if cf_payment_id:
            self.cf_payment_id = cf_payment_id
        self.save()

    def __str__(self):
        return f"{self.order_id} - {self.status}"
