"""Subscription models.

The ``SubscriptionSettings`` singleton holds the app-wide flag that controls
whether the subscription section is available on login. It is deliberately
global (not per-user) so a site admin can enable/disable the whole
subscription flow from the Django admin in one place.
"""

from django.db import models

from applications.accounts.models import Madrasa


class Subscription(models.Model):
    """A paid subscription (1 year) attached to a Madrasa (institution)."""

    institution = models.ForeignKey(Madrasa, on_delete=models.CASCADE)
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=False)

    def activate_for_year(self):
        """Set start/end dates to cover the current year and mark active."""
        from django.utils import timezone
        from datetime import timedelta

        self.start_date = timezone.now()
        self.end_date = self.start_date + timedelta(days=365)
        self.active = True
        self.save(update_fields=["start_date", "end_date", "active"])

    @property
    def is_active(self):
        """True if the subscription's end date is still in the future."""
        if self.end_date is None:
            return False
        from django.utils import timezone

        return self.end_date >= timezone.now()

    def __str__(self):
        return f"{self.institution} subscription ({'active' if self.active else 'inactive'})"


class Transaction(models.Model):
    """Payment transaction record (e.g. Cashfree order)."""

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
        self.save(update_fields=["status", "cf_payment_id"])

    def __str__(self):
        return f"{self.order_id} - {self.status}"


class SubscriptionSettings(models.Model):
    """Global, app-level setting that gates the subscription section.

    This is a singleton: only one row exists in the database and it holds
    the single ``subscription_enabled`` flag for the entire web app.
    """

    subscription_enabled = models.BooleanField(
        default=False,
        help_text=(
            "When OFF (default), the subscription section is hidden from the"
            " UI and no one is redirected to the paywall on login. Set to ON"
            " to allow users to purchase a subscription."
        ),
    )

    class Meta:
        verbose_name = "Subscription Settings"
        verbose_name_plural = "Subscription Settings"
        db_table = "subscription_subscriptionsettings"

    def __str__(self):
        return (
            "Subscription settings - enabled: "
            f"{'Yes' if self.subscription_enabled else 'No'}"
        )

    @classmethod
    def get_global(cls):
        """Return the single ``SubscriptionSettings`` instance."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @classmethod
    def is_enabled(cls):
        """Return True when the subscription section is globally enabled."""
        return cls.get_global().subscription_enabled

    def save(self, *args, **kwargs):
        # Enforce the singleton pattern: delete any other rows before saving
        # so only one row with pk=1 ever exists.
        self.pk = 1
        super().save(*args, **kwargs)
