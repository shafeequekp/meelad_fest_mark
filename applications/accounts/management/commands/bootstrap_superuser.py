"""
Ensure the initial superuser exists.

Runs automatically during the Render build (see render.yaml) because the
Render free tier has no shell access. Idempotent: safe to run on every deploy.

Environment variables (set in .env locally, in the Render dashboard there):
  DJANGO_SUPERUSER_EMAIL      required -- login email of the superuser
  DJANGO_SUPERUSER_PASSWORD   required to create the user
  BOOTSTRAP_SUPERUSER_RESET   optional "1" to also reset an existing
                              superuser's password on this run

Notes:
- The Meelad user model logs in with EMAIL (User.USERNAME_FIELD == 'email').
- Existing users are only upgraded to staff/superuser; their password is left
  untouched unless BOOTSTRAP_SUPERUSER_RESET=1.
"""
import logging
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Create or ensure the initial superuser from DJANGO_SUPERUSER_* "
        "environment variables (idempotent, safe for every deploy)."
    )

    def handle(self, *args, **options):
        User = get_user_model()
        email = os.getenv("DJANGO_SUPERUSER_EMAIL", "").strip().lower()
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD", "")
        reset = os.getenv("BOOTSTRAP_SUPERUSER_RESET", "") == "1"

        if not email:
            self.stdout.write(
                "bootstrap_superuser: DJANGO_SUPERUSER_EMAIL not set -- skipping."
            )
            return

        # ---- existing user: promote / optionally reset password -------------
        user = User.objects.filter(email=email).first()
        if user is not None:
            changed = []
            if not user.is_staff:
                user.is_staff = True
                changed.append("is_staff")
            if not user.is_superuser:
                user.is_superuser = True
                changed.append("is_superuser")
            if reset and password:
                user.set_password(password)
                changed.append("password")
            if changed:
                user.save()
                logger.info("bootstrap_superuser: updated %s (%s)", email, ", ".join(changed))
                self.stdout.write(self.style.SUCCESS(
                    f"bootstrap_superuser: updated existing superuser '{email}' "
                    f"({', '.join(changed)})."
                ))
            else:
                self.stdout.write(
                    f"bootstrap_superuser: superuser '{email}' already exists "
                    "-- nothing to do."
                )
            return

        # ---- create ----------------------------------------------------------
        if not password:
            self.stdout.write(self.style.WARNING(
                "bootstrap_superuser: DJANGO_SUPERUSER_PASSWORD not set -- "
                "cannot create the superuser, skipping."
            ))
            return

        User.objects.create_superuser(email=email, password=password)
        logger.info("bootstrap_superuser: created superuser %s", email)
        self.stdout.write(self.style.SUCCESS(
            f"bootstrap_superuser: created superuser '{email}'."
        ))