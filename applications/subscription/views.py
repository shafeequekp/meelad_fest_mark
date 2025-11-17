import json
import uuid
import hmac, hashlib, base64

from django.conf import settings
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import render

import requests

from .models import Transaction, Subscription
from applications.accounts.models import Madrasa
from django.utils import timezone

SUBSCRIPTION_FEE = 299.00  # INR


@login_required
def subscribe_view(request):
    # show subscription page where user clicks "Proceed to payment"
    return render(request, "subscription/subscription.html", {"amount": SUBSCRIPTION_FEE})


@login_required
def create_order(request):
    """
    POST endpoint (or GET) that creates a Cashfree order and redirects to the hosted checkout page.
    """
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid method")
    
    user = request.user
    if not getattr(user, "phone_number", "9544443981"):
        return HttpResponseBadRequest("Phone number is required before payment")

    # Create a unique order id for your system
    order_id = f"meelad_{request.user.madrasa.id}_{int(timezone.now().timestamp())}"
    amount = SUBSCRIPTION_FEE
    currency = "INR"

    # need to use this for prod
    return_url = request.build_absolute_uri("/subscription/success/?order_id=" + order_id)
    notify_url = request.build_absolute_uri("/subscription/webhook/")

    # payload = {
    #     "order_id": order_id,
    #     "order_amount": f"{amount:.2f}",
    #     "order_currency": currency,
    #     # return_url: user will be redirected after payment (frontend). Include order_id to query later.
    #     "return_url": f"https://wanted-chigger-radically.ngrok-free.app/subscription/success/?order_id={order_id}",
    # #      "return_url": {
    # #     "return_url": f"https://wanted-chigger-radically.ngrok-free.app/subscription/success/",
    # #     "enable": True
    # # },
    #     # notify_url: Cashfree will call this webhook (server -> server)
    #     "notify_url": f"https://wanted-chigger-radically.ngrok-free.app//subscription/webhook/",
    #     "customer_details": {
    #         "customer_id": str(request.user.id),
    #         "customer_email": request.user.email or "",
    #         "customer_phone": getattr(request.user, "phone", "") or "9544443981"
    #     },
    #     # optional: tags/cart etc
    # }

    payload = {
    "order_id": order_id,
    "order_amount": f"{amount:.2f}",
    "order_currency": currency,

    "order_meta": {
    "return_url": return_url,
    "notify_url": notify_url
  },

    # ✔ REQUIRED for hosted checkout
    "payment_method": {
        "upi": {
            "channel": "collect"
        },
        "card": {},
        "netbanking": {}
    },

    "customer_details": {
        "customer_id": str(request.user.id),
        "customer_email": request.user.email or "",
        "customer_phone": getattr(request.user, "phone_number", "") or "9544443981"
    }
}


    headers = {
        "Content-Type": "application/json",
        "x-api-version": settings.CASHFREE_API_VERSION,
        "x-client-id": settings.CASHFREE_CLIENT_ID,
        "x-client-secret": settings.CASHFREE_CLIENT_SECRET,
    }

    create_url = f"{settings.CASHFREE_API_BASE}/orders"
    resp = requests.post(create_url, json=payload, headers=headers, timeout=15)
    if resp.status_code not in (200, 201):
        print(resp.status_code, resp.text)
        return HttpResponse("Failed to create order with payment gateway", status=500)
    
    # # debug logs
    # print("Create URL:", create_url)
    # print("Outgoing headers:", getattr(resp.request, "headers", None))
    # print("Outgoing body:", getattr(resp.request, "body", None))
    # print("Response code:", resp.status_code)
    # print("Response text:", resp.text)

    data = resp.json()
    # `payment_session_id` (or payment link) will be in response (docs say payment_session_id)
    payment_session_id = data.get("payment_session_id") or data.get("payment_link") or data.get("data", {}).get("payment_session_id")
    # print("Payment session id =>", payment_session_id)

    # Save Transaction
    Transaction.objects.create(
        institution=request.user.madrasa,
        order_id=order_id,
        amount=amount,
        currency=currency,
        raw_response=data,
        status="PENDING"
    )

    # Redirect user to a payment page that will use the payment_session_id to open hosted checkout
    return render(request, "subscription/payment.html", {"payment_session_id": payment_session_id, "order_id": order_id})


@csrf_exempt
def webhook_listener(request):
    """
    Cashfree will POST payment events here. We MUST verify signature per Cashfree docs:
    signature = base64encode( HMAC_SHA256( timestamp + raw_body, client_secret ) )
    The headers are: x-webhook-timestamp and x-webhook-signature
    (Docs: use raw request body and timestamp concatenated).
    """
    # read raw body bytes (important)
    raw_body = request.body  # bytes
    ts = request.headers.get("x-webhook-timestamp") or request.META.get("HTTP_X_WEBHOOK_TIMESTAMP")
    signature = request.headers.get("x-webhook-signature") or request.META.get("HTTP_X_WEBHOOK_SIGNATURE")

    if not ts or not signature:
        return HttpResponseBadRequest("Missing signature headers")

    secret = settings.CASHFREE_WEBHOOK_SECRET.encode()

    # verify signature (timestamp + raw_body)
    to_sign = ts.encode() + raw_body
    hm = hmac.new(secret, to_sign, hashlib.sha256).digest()
    computed_signature = base64.b64encode(hm).decode()

    if not hmac.compare_digest(computed_signature, signature):
        return HttpResponse("Invalid signature", status=400)

    # signature valid -> parse JSON
    payload = json.loads(raw_body.decode("utf-8"))
    # payload structure usually: { "data": { "order": { "order_id": ... }, "payment": {...}, "customer_details": {...} } }
    data = payload.get("data", {})
    order = data.get("order", {})
    payment = data.get("payment", {})

    order_id = order.get("order_id")
    payment_status = payment.get("payment_status") or payment.get("status")  # example "SUCCESS"
    cf_payment_id = payment.get("cf_payment_id") or payment.get("gateway_payment_id") or None

    try:
        tx = Transaction.objects.get(order_id=order_id)
    except Transaction.DoesNotExist:
        # unknown order - log and return 200 to avoid retries or return 404
        return HttpResponse("Order not found", status=200)

    tx.raw_response = payload
    if payment_status and payment_status.upper() in ("SUCCESS", "PAID"):
        tx.status = "PAID"
        tx.cf_payment_id = cf_payment_id
        tx.save()
        # activate subscription for the institution (example)
        sub = Subscription.objects.filter(institution=tx.institution).last()
        if not sub:
            sub = Subscription.objects.create(institution=tx.institution)
        sub.activate_for_year()
    else:
        tx.status = "FAILED"
        tx.save()

    return HttpResponse("ok", status=200)


def payment_success(request):
    order_id = request.GET.get("order_id")
    tx = None
    if order_id:
        tx = Transaction.objects.filter(order_id=order_id).first()
        if tx:
            madrasa = Madrasa.objects.filter(id=tx.institution.id).last()
            if madrasa:
                subcription = Subscription.objects.filter(institution=madrasa).last()
                # if not subcription:
                #     subcription = Subscription.objects.create(institution=madrasa)
                user = madrasa.user
                if user:
                    user.subscribed = True
                    user.save()
    return render(request, "subscription/success.html", {"tx": tx})

