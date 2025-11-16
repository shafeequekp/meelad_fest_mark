from django.urls import path
from . import views


app_name = "subscription"


urlpatterns = [
    path("subscribe/", views.subscribe_view, name="subscribe"),
    path("create-order/", views.create_order, name="create_order"),
    path("payment/", views.payment_success, name="payment"),
    path("success/", views.payment_success, name="success"),
    path("webhook/", views.webhook_listener, name="webhook"),
]