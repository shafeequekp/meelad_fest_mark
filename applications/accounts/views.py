from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from applications.subscription.models import SubscriptionSettings

from io import BytesIO

from .forms import LoginForm, SignupForm, MadrasaForm
from .models import User


# def login_view(request):
#     if request.user.is_authenticated:
#         return redirect("home")  # already logged in
#
#     if request.method == "POST":
#         form = LoginForm(request, data=request.POST)
#         if form.is_valid():
#             user = form.get_user()
#             login(request, user)
#             return redirect("home")
#         else:
#             messages.error(request, "Invalid login credentials")
#     else:
#         form = LoginForm()
#
#     signup_form = SignupForm()  # for combined template
#     return render(request, "auth/login_signup.html", {"login_form": form, "signup_form": signup_form})

def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")  # already logged in

    if request.method == "POST":
        form = LoginForm(request.POST)  # ✅ only POST data

        if form.is_valid():
            email = form.cleaned_data["email"]
            password = form.cleaned_data["password"]
            user = authenticate(request, username=email, password=password)
            if user is not None:
                login(request, user)
                # "Remember me" — unchecked keeps a browser-session cookie
                # (expires on close); checked keeps the login for two weeks
                # (Django's default SESSION_COOKIE_AGE).
                if request.POST.get("remember"):
                    request.session.set_expiry(1209600)
                else:
                    request.session.set_expiry(0)
                # Linked judge accounts are fest staff, not customers: send
                # them straight to their portal, never to the paywall.
                from applications.program.models import Judge

                if Judge.objects.filter(user=user, is_active=True).exists():
                    return redirect("judge_portal")

                # The global toggle (settings.SUBSCRIPTION_ENABLED) controls
                # whether the subscription section is visible on login for
                # everyone. The ``subscribed`` flag records if the user has
                # already paid or not.
                if SubscriptionSettings.is_enabled() and not user.subscribed:
                    return redirect("subscription:subscribe")
                return redirect("home")
            # Detailed error attached to the form so the template renders it
            # inline in the login panel instead of a generic flash message.
            form.add_error(
                None,
                "Invalid email or password. Please check your credentials and try again.",
            )
        # Field errors (and the invalid-credentials error above) are rendered
        # inline next to each input by the template on the shared render below.
    else:
        form = LoginForm()

    signup_form = SignupForm()
    return render(
        request,
        "auth/login_signup.html",
        {"login_form": form, "signup_form": signup_form},
    )



# def signup_view(request):
#     if request.user.is_authenticated:
#         return redirect("home")
#
#     if request.method == "POST":
#         form = SignupForm(request.POST)
#         if form.is_valid():
#             user = form.save()
#             login(request, user)  # auto login after signup
#             return redirect("home")
#         else:
#             messages.error(request, "Signup failed, please fix errors")
#     else:
#         form = SignupForm()
#
#     login_form = LoginForm(request)  # for combined template
#     return render(request, "auth/login_signup.html", {"signup_form": form, "login_form": login_form})


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        form = SignupForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save()
            login(request, user)  # auto login after signup
            madrasa = getattr(user, "madrasa", None)
            fest_label = madrasa.get_fest_type_display() if madrasa else ""
            messages.success(
                request,
                "Account created successfully." + (f" Fest type: {fest_label}." if fest_label else ""),
            )
            return redirect("home")
        # No generic flash message: every field's errors are rendered inline
        # next to its input by the template.
    else:
        form = SignupForm()

    login_form = LoginForm(request.POST or None)
    return render(request, "auth/login_signup.html", {
        "signup_form": form,
        "login_form": login_form
    })



def logout_view(request):
    logout(request)
    return redirect("login")


def forgot_password_view(request):
    """Interim password reset with NO verification (owner's request).

    The user identifies the account by email and simply sets a new password.
    A verification step (email OTP / token link) will be added later — swap
    this flow out before exposing it beyond trusted users.
    """
    if request.user.is_authenticated:
        return redirect("home")

    email_value = ""
    if request.method == "POST":
        email_value = (request.POST.get("email") or "").strip()
        password1 = request.POST.get("password1") or ""
        password2 = request.POST.get("password2") or ""

        errors = {}
        if not email_value:
            errors["email"] = "Email is required."
        if len(password1) < 4:
            errors["password1"] = "Password must be at least 4 characters."
        if password1 != password2:
            errors["password2"] = "Passwords do not match."

        user = None
        if not errors:
            user = User.objects.filter(email__iexact=email_value).first()
            if user is None:
                errors["email"] = "No account found with this email."

        if errors:
            return render(
                request,
                "auth/forgot_password.html",
                {"errors": errors, "email_value": email_value},
                status=400,
            )

        user.set_password(password1)
        user.save()
        messages.success(
            request,
            "Password updated successfully. Please login with your new password.",
        )
        return redirect("login")

    return render(request, "auth/forgot_password.html", {"email_value": email_value})


@require_POST
def update_madrasa(request):
    """Update the logged-in user's madrasa details from the profile modal.

    Handles multipart form data so the logo / signature image fields can also be
    replaced. Returns JSON so the modal can stay open and show validation errors
    without a full page reload.
    """
    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "errors": {"__all__": ["Authentication required."]}},
            status=401,
        )

    madrasa = getattr(request.user, "madrasa", None)
    if not madrasa:
        return JsonResponse(
            {"success": False, "errors": {"__all__": ["No madrasa is linked to this account."]}},
            status=400,
        )

    form = MadrasaForm(request.POST, request.FILES, instance=madrasa)
    if form.is_valid():
        form.save()
        return JsonResponse(
            {"success": True, "message": "Madrasa details updated successfully."}
        )

    return JsonResponse({"success": False, "errors": form.errors}, status=400)


@require_POST
def upload_madrasa_profile_pic(request):
    """Replace just the madrasa profile photo (triggered from the avatar button
    in the profile popup modal). Returns JSON so the caller can refresh the
    avatar immediately without reloading the whole page.
    """

    if not request.user.is_authenticated:
        return JsonResponse(
            {"success": False, "errors": {"__all__": ["Authentication required."]}},
            status=401,
        )

    madrasa = getattr(request.user, "madrasa", None)
    if not madrasa:
        return JsonResponse(
            {"success": False, "errors": {"__all__": ["No madrasa is linked to this account."]}},
            status=400,
        )

    uploaded = request.FILES.get("profile_pic")
    if not uploaded:
        return JsonResponse(
            {"success": False, "errors": {"__all__": ["No image file was provided."]}},
            status=400,
        )

    madrasa.madrasa_profile_pic = uploaded
    madrasa.save(update_fields=["madrasa_profile_pic"])

    return JsonResponse(
        {"success": True, "message": "Profile photo updated.",
         "profile_pic_url": madrasa.madrasa_profile_pic.url}
    )


# ---------------------------------------------------------------------------
# Fest rules & regulations document (per madrasa)
# ---------------------------------------------------------------------------
FEST_RULES_MAX_BYTES = 10 * 1024 * 1024  # 10 MB — plenty for a rules booklet


def _fest_rules_payload(madrasa):
    """Serialise the madrasa's current rules document for the profile modal."""
    if not madrasa.fest_rules:
        return {"has_rules": False}
    return {
        "has_rules": True,
        "file_name": madrasa.fest_rules.name.rsplit("/", 1)[-1],
        "file_url": madrasa.fest_rules.url,
        "updated_at": (madrasa.fest_rules_updated_at.isoformat()
                       if madrasa.fest_rules_updated_at else None),
        "chars": len(madrasa.fest_rules_text or ""),
    }


def _madrasa_or_error(request):
    """Shared guard for the rules endpoints: JSON error responses."""
    if not request.user.is_authenticated:
        return None, JsonResponse(
            {"success": False, "errors": {"__all__": ["Authentication required."]}},
            status=401)
    madrasa = getattr(request.user, "madrasa", None)
    if not madrasa:
        return None, JsonResponse(
            {"success": False, "errors": {"__all__": ["No madrasa is linked to this account."]}},
            status=400)
    return madrasa, None


def _extract_pdf_text(django_file):
    """Extract text from an uploaded PDF; returns (text, pages).

    Raises ValueError when the PDF has no extractable text layer (scanned
    images only) — such a file would make the AI rules answers useless.
    """
    from pypdf import PdfReader

    data = django_file.read()
    django_file.seek(0)  # leave the stream usable for the storage backend
    reader = PdfReader(BytesIO(data))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - a single broken page must not kill the upload
            pages.append("")
    text = "\n\n".join(p.strip() for p in pages if p and p.strip())
    if not text.strip():
        raise ValueError(
            "No selectable text was found in this PDF. It looks like a scanned "
            "document — the AI assistant can only answer from PDFs that "
            "contain a text layer.")
    return text, len(reader.pages)


@require_POST
def upload_fest_rules(request):
    """Upload/replace this madrasa's fest rules PDF.

    The extracted text is stored alongside the file so the AI assistant's
    knowledge base (RAG) can answer rules questions without parsing PDFs.
    """
    madrasa, err = _madrasa_or_error(request)
    if err:
        return err

    uploaded = request.FILES.get("fest_rules")
    if not uploaded:
        return JsonResponse(
            {"success": False, "errors": {"__all__": ["No PDF file was provided."]}},
            status=400)

    name = (uploaded.name or "").lower()
    if not name.endswith(".pdf") or (uploaded.content_type or "") not in (
            "application/pdf", "application/x-pdf", "binary/octet-stream", ""):
        return JsonResponse(
            {"success": False,
             "errors": {"__all__": ["Only PDF files are accepted (.pdf)."]}},
            status=400)
    if uploaded.size > FEST_RULES_MAX_BYTES:
        return JsonResponse(
            {"success": False,
             "errors": {"__all__": ["The PDF is too large (10 MB maximum)."]}},
            status=400)

    try:
        text, pages = _extract_pdf_text(uploaded)
    except ValueError as exc:
        return JsonResponse({"success": False, "errors": {"__all__": [str(exc)]}},
                            status=400)
    except Exception:  # noqa: BLE001 - corrupt/encrypted PDFs land here
        return JsonResponse(
            {"success": False,
             "errors": {"__all__": ["This PDF could not be read. It may be "
                                    "corrupted or password-protected."]}},
            status=400)

    # Replace any previous document (and delete its stored file).
    old = madrasa.fest_rules
    madrasa.fest_rules = uploaded
    madrasa.fest_rules_text = text
    madrasa.fest_rules_updated_at = timezone.now()
    madrasa.save(update_fields=["fest_rules", "fest_rules_text",
                                "fest_rules_updated_at"])
    if old and old != madrasa.fest_rules:
        old.delete(save=False)

    return JsonResponse({
        "success": True,
        "message": f"Fest rules uploaded — {pages} page{'s' if pages != 1 else ''} "
                   "indexed for the AI assistant.",
        "rules": _fest_rules_payload(madrasa),
    })


@require_POST
def remove_fest_rules(request):
    """Delete this madrasa's fest rules document and its extracted text."""
    madrasa, err = _madrasa_or_error(request)
    if err:
        return err

    if madrasa.fest_rules:
        madrasa.fest_rules.delete(save=False)
    madrasa.fest_rules = None
    madrasa.fest_rules_text = None
    madrasa.fest_rules_updated_at = None
    madrasa.save(update_fields=["fest_rules", "fest_rules_text",
                                "fest_rules_updated_at"])
    return JsonResponse({"success": True, "message": "Fest rules removed.",
                         "rules": _fest_rules_payload(madrasa)})
