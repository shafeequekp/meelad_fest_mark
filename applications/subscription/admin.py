"""Django admin definitions for the subscription app.

Registers the ``SubscriptionSettings`` singleton (global app-level toggle)
and the ``Subscription`` / ``Transaction`` models.
"""

from django.contrib import admin

from applications.subscription.models import Subscription, Transaction, SubscriptionSettings


@admin.register(SubscriptionSettings)
class SubscriptionSettingsAdmin(admin.ModelAdmin):
    """Admin form for the global subscription-enable toggle.

    Shows a single checkbox with a clear description so a site admin can
    instantly enable/disable the entire subscription section for the web app.
    """

    list_display = ["id", "subscription_enabled"]
    list_filter = ["subscription_enabled"]
    search_fields = ["id"]
    ordering = ["id"]

    fieldsets = (
        (
            "App-wide subscription control",
            {
                "description": (
                    "Controls whether the subscription section is available on "
                    "login for the whole web app. Default is OFF (disabled); "
                    "turn it ON when the site is ready to accept subscriptions."
                ),
                "fields": ("subscription_enabled",),
            },
        ),
    )

    add_fieldsets = fieldsets


admin.site.register(Subscription)
admin.site.register(Transaction)
