from django.contrib import admin

from applications.subscription.models import Subscription, Transaction


admin.site.register(Subscription)
admin.site.register(Transaction)
