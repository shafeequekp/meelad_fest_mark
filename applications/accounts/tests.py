from django.test import TestCase, override_settings
from django.urls import reverse
from django.template import Context, Engine
from django.core.files.uploadedfile import SimpleUploadedFile
import re
import tempfile

from applications.accounts.models import Madrasa, User


def _make_rules_pdf(text):
    """Build a small real PDF (in memory) containing ``text`` via reportlab."""
    from io import BytesIO
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    p = canvas.Canvas(buf)
    y = 800
    for line in text.splitlines():
        p.drawString(50, y, line)
        y -= 18
    p.save()
    return buf.getvalue()


class FestRulesUploadTests(TestCase):
    """Uploading the fest rules PDF must extract its text so the AI assistant
    can answer rules questions from this madrasa's own document."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Rules Madrasa", reg_number="R1")
        self.user = User.objects.create_user(
            email="a@b.com", password="pass", madrasa=self.madrasa)
        # Fresh media root per test so uploads never collide with files left
        # by previous tests (which would rename the stored PDF).
        self._media_override = override_settings(MEDIA_ROOT=tempfile.mkdtemp())
        self._media_override.enable()

    def tearDown(self):
        self._media_override.disable()
        super().tearDown()

    def _post(self, *args, **kwargs):
        return self.client.post(reverse("upload_fest_rules"), *args, **kwargs)

    def test_upload_requires_login(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 401)

    def test_upload_requires_a_madrasa(self):
        User.objects.create_user(email="nom@b.com", password="pass")
        self.client.force_login(User.objects.get(email="nom@b.com"))
        resp = self._post({"fest_rules": SimpleUploadedFile(
            "rules.pdf", _make_rules_pdf("Rule one: be kind."),
            content_type="application/pdf")})
        self.assertEqual(resp.status_code, 400)

    def test_upload_extracts_text_and_stores_metadata(self):
        self.client.force_login(self.user)
        pdf = _make_rules_pdf(
            "Fest Rules and Regulations\n"
            "Tie breaking: a coin toss by the chief judge decides the winner.\n"
            "Protests must be written within thirty minutes.")
        resp = self._post({"fest_rules": SimpleUploadedFile(
            "rules.pdf", pdf, content_type="application/pdf")})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])

        self.madrasa.refresh_from_db()
        self.assertTrue(self.madrasa.fest_rules)
        self.assertIn("coin toss", self.madrasa.fest_rules_text)
        self.assertIn("thirty minutes", self.madrasa.fest_rules_text)
        self.assertIsNotNone(self.madrasa.fest_rules_updated_at)

        data = resp.json()["rules"]
        self.assertTrue(data["has_rules"])
        self.assertEqual(data["file_name"], "rules.pdf")
        self.assertGreater(data["chars"], 0)

    def test_replacement_deletes_previous_file(self):
        self.client.force_login(self.user)
        first = SimpleUploadedFile("rules.pdf", _make_rules_pdf("Rule: v1."),
                                   content_type="application/pdf")
        self._post({"fest_rules": first})
        old_path = Madrasa.objects.get(pk=self.madrasa.pk).fest_rules.path

        second = SimpleUploadedFile("rules.pdf", _make_rules_pdf("Rule: v2."),
                                    content_type="application/pdf")
        resp = self._post({"fest_rules": second})
        self.assertEqual(resp.status_code, 200)

        import os
        self.assertFalse(os.path.exists(old_path))
        self.madrasa.refresh_from_db()
        self.assertIn("v2", self.madrasa.fest_rules_text)
        self.assertNotEqual(
            old_path, Madrasa.objects.get(pk=self.madrasa.pk).fest_rules.path)

    def test_non_pdf_rejected(self):
        self.client.force_login(self.user)
        resp = self._post({"fest_rules": SimpleUploadedFile(
            "rules.txt", b"not a pdf", content_type="text/plain")})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("PDF", resp.json()["errors"]["__all__"][0])

    def test_scanned_pdf_without_text_rejected(self):
        self.client.force_login(self.user)
        # A blank page yields no extractable text — the AI would have nothing
        # to answer from, so the upload is rejected with a clear message.
        resp = self._post({"fest_rules": SimpleUploadedFile(
            "scan.pdf", _make_rules_pdf(""), content_type="application/pdf")})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("scanned", resp.json()["errors"]["__all__"][0])

    def test_remove_clears_document_and_text(self):
        self.client.force_login(self.user)
        self._post({"fest_rules": SimpleUploadedFile(
            "rules.pdf", _make_rules_pdf("Rule: remove me."),
            content_type="application/pdf")})
        resp = self.client.post(reverse("remove_fest_rules"))
        self.assertEqual(resp.status_code, 200)
        self.madrasa.refresh_from_db()
        self.assertFalse(self.madrasa.fest_rules)
        self.assertFalse(self.madrasa.fest_rules_text)
        self.assertFalse(resp.json()["rules"]["has_rules"])


class UpdateMadrasaTests(TestCase):
    """The profile modal's madrasa editor must update the user's madrasa."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Old Name", reg_number="R1")
        self.user = User.objects.create_user(email="a@b.com", password="pass", madrasa=self.madrasa)
        self.client.login(username="a@b.com", password="pass")

    def test_signup_persists_selected_fest_type(self):
        self.client.logout()
        before = User.objects.filter(email="new@fest.com").count()
        resp = self.client.post(reverse("signup"), {
            "email": "new@fest.com",
            "phone_number": "9000000000",
            "password1": "pass1234",
            "password2": "pass1234",
            "madrasa_name": "Girls Madrasa",
            "meelad_fest_name": "Girls Fest 2026",
            "fest_type": "girls",
        })
        self.assertEqual(resp.status_code, 302, f"signup failed: {resp.context['signup_form'].errors if resp.context else 'no context'}")
        new_user = User.objects.get(email="new@fest.com")
        self.assertIsNotNone(new_user.madrasa)
        self.assertEqual(new_user.madrasa.fest_type, "girls")

    def test_update_madrasa_all_fields(self):
        resp = self.client.post(reverse("update_madrasa"), {
            "name": "New Name",
            "reg_number": "R2",
            "sadr": "Sadr X",
            "committee_name": "Committee Y",
            "meelad_fest_name": "New Fest",
            "convenor_name_1": "Conv A",
            "convenor_name_2": "Conv B",
            "fest_type": "girls",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        self.madrasa.refresh_from_db()
        self.assertEqual(self.madrasa.fest_type, "girls")
        self.assertEqual(self.madrasa.name, "New Name")
        self.assertEqual(self.madrasa.reg_number, "R2")
        self.assertEqual(self.madrasa.sadr, "Sadr X")
        self.assertEqual(self.madrasa.committee_name, "Committee Y")
        self.assertEqual(self.madrasa.meelad_fest_name, "New Fest")
        self.assertEqual(self.madrasa.convenor_name_1, "Conv A")
        self.assertEqual(self.madrasa.convenor_name_2, "Conv B")

    def test_update_madrasa_missing_name_rejected(self):
        resp = self.client.post(reverse("update_madrasa"), {"reg_number": "R2"})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["success"])
        self.assertIn("name", resp.json()["errors"])

    def test_update_madrasa_requires_login(self):
        self.client.logout()
        resp = self.client.post(reverse("update_madrasa"), {"name": "X"})
        self.assertEqual(resp.status_code, 401)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_update_madrasa_profile_pic(self):
        from io import BytesIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (80, 80), (0, 100, 200)).save(buf, format="PNG")
        buf.seek(0)
        photo = SimpleUploadedFile("profile.png", buf.getvalue(), content_type="image/png")

        resp = self.client.post(reverse("update_madrasa"), {
            "name": "New Name",
            "madrasa_profile_pic": photo,
            "fest_type": "both",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        self.madrasa.refresh_from_db()
        self.assertTrue(self.madrasa.madrasa_profile_pic)  # field persisted
        self.assertTrue(self.madrasa.madrasa_profile_pic.name.endswith(".png"))
        self.assertEqual(self.madrasa.madrasa_profile_pic.field.upload_to, "madrasa_profile_pics/")


class HeaderProfilePicRenderTests(TestCase):
    """The header profile avatar must fall back to the default image when the
    madrasa has no uploaded profile photo, and show the uploaded photo when set."""

    def _render(self, madrasa):
        engine = Engine.get_default()
        tpl = engine.get_template("header.html")
        request = type("R", (), {
            "user": type("U", (), {"is_authenticated": True, "get_full_name": lambda: "Prof",
                                   "email": "p@x.com", "phone_number": "999", "country_code": "+91",
                                   "permanent_address": "Addr"}),
            "resolver_match": type("RM", (), {"url_name": "home"}),
        })()
        return tpl.render(Context({
            "request": request,
            "profile_madrasa": madrasa,
            "csrf_token": "test-token",
            "meelad_fest_name": "Fest",
        }))

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_default_image_shown_without_pic(self):
        m = Madrasa(name="M")
        html = self._render(m)
        self.assertIn("images/profile.png", html)
        self.assertNotIn("madrasa_profile_pics/", html)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_uploaded_pic_used_when_present(self):
        from io import BytesIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (10, 10), (10, 200, 30)).save(buf, format="PNG")
        m = Madrasa(name="M")
        m.madrasa_profile_pic.save(
            "mypic.png", SimpleUploadedFile("mypic.png", buf.getvalue(), "image/png"), save=False
        )
        html = self._render(m)
        self.assertIn("madrasa_profile_pics/", html)
        self.assertNotIn("images/profile.png", html)


class HeaderBrandTests(TestCase):
    """The header brand bar shows the fest name plus the fest emblem.

    Guards three regressions:
    * the madrasa *name* used to be printed in the brand bar as a badge; the
      brand must carry only the fest name (the madrasa name is still available
      in the profile modal, which is where it is actually edited),
    * the brand icon must always be the trophy emblem — the same mark the
      index page hero uses. The uploaded ``fest_logo`` file is deliberately
      NOT used here: its storage URL can be unreachable, which rendered a
      blank box in the brand bar, and
    * anonymous pages (no ``profile_madrasa``) must still render the brand.
    """

    TROPHY = "M16.5 18.75h-9"

    def _render(self, madrasa, fest_name="Meelad Fest 2026"):
        engine = Engine.get_default()
        tpl = engine.get_template("header.html")
        request = type("R", (), {
            "user": type("U", (), {"is_authenticated": True, "get_full_name": lambda: "Prof",
                                   "email": "p@x.com", "phone_number": "999", "country_code": "+91",
                                   "permanent_address": "Addr"}),
            "resolver_match": type("RM", (), {"url_name": "home"}),
        })()
        return tpl.render(Context({
            "request": request,
            "profile_madrasa": madrasa,
            "csrf_token": "test-token",
            "meelad_fest_name": fest_name,
        }))

    @staticmethod
    def _brand(html):
        """Brand bar only: opening <header> up to the nav — not the profile modal."""
        return html[html.index("<header"):html.index("<!-- Right: Navigation")]

    def test_trophy_emblem_always_shown(self):
        """The trophy emblem renders even when a fest_logo is uploaded."""
        m = Madrasa(name="Darul Huda")
        brand = self._brand(self._render(m))
        self.assertIn(self.TROPHY, brand)
        self.assertIn("Meelad Fest 2026", brand)

        # An uploaded fest_logo must NOT swap the emblem out (its URL can be
        # unreachable, which used to leave a blank box in the brand bar)
        m.fest_logo = "madrasa_logos/fest.png"
        brand = self._brand(self._render(m))
        self.assertIn(self.TROPHY, brand)
        self.assertNotIn("<img", brand)

    def test_madrasa_name_never_shown_in_brand(self):
        m = Madrasa(name="Darul Huda")
        brand = self._brand(self._render(m))
        self.assertNotIn("Darul Huda", brand)
        self.assertNotIn("You are viewing", brand)
        # ...but the fest name is always there
        self.assertIn("Meelad Fest 2026", brand)

    def test_brand_falls_back_for_public_pages(self):
        """Anonymous pages have no ``profile_madrasa`` — the brand must still render."""
        html = Engine.get_default().get_template("header.html").render(Context({
            "request": type("R", (), {
                "user": type("U", (), {"is_authenticated": False})(),
                "resolver_match": type("RM", (), {"url_name": "login"}),
            })(),
            "csrf_token": "t",
        }))
        self.assertIn(self.TROPHY, self._brand(html))

    def test_brand_markup_is_balanced(self):
        """No stray tags: unbalanced markup silently swallows the rest of the page."""
        html = self._render(Madrasa(name="Darul Huda"))
        header = html[html.index("<header"):html.index("</header>") + len("</header>")]
        for tag in ("span", "a", "div"):
            opened = len(re.findall(r"<%s[\s>]" % tag, header))
            closed = len(re.findall(r"</%s>" % tag, header))
            self.assertEqual(
                opened, closed,
                f"unbalanced <{tag}> in the header: {opened} open / {closed} close",
            )


class AvatarUploadTests(TestCase):
    """The avatar camera button must render in the modal, and the dedicated
    upload endpoint must replace the madrasa's profile photo for logged-in
    users only."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="M", reg_number="R1")
        self.user = User.objects.create_user(email="a@b.com", password="pass", madrasa=self.madrasa)
        self.client.login(username="a@b.com", password="pass")

    def _render(self, madrasa):
        engine = Engine.get_default()
        tpl = engine.get_template("header.html")
        request = type("R", (), {
            "user": type("U", (), {"is_authenticated": True,
                                   "get_full_name": lambda: "Prof", "email": "p@x.com",
                                   "phone_number": "999", "country_code": "+91",
                                   "permanent_address": "Addr"}),
            "resolver_match": type("RM", (), {"url_name": "home"}),
        })()
        return tpl.render(Context({
            "request": request, "profile_madrasa": madrasa,
            "csrf_token": "test-token", "meelad_fest_name": "Fest",
        }))

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_avatar_upload_button_present(self):
        html = self._render(Madrasa(name="M"))
        self.assertIn("avatar-upload-btn", html)
        self.assertIn("avatarUploadInput", html)
        self.assertIn("/accounts/madrasa/avatar/upload/", html)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_avatar_upload_requires_login(self):
        self.client.logout()
        resp = self.client.post(reverse("update_madrasa"), {"name": "X"})
        self.assertEqual(resp.status_code, 401)

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_upload_profile_pic_endpoint(self):
        from io import BytesIO
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        buf = BytesIO()
        Image.new("RGB", (40, 40), (1, 2, 3)).save(buf, format="PNG")
        buf.seek(0)

        resp = self.client.post(reverse("upload_madrasa_profile_pic"), {
            "profile_pic": SimpleUploadedFile("pic.png", buf.getvalue(), "image/png"),
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertIn("profile_pic_url", data)

        self.madrasa.refresh_from_db()
        self.assertTrue(self.madrasa.madrasa_profile_pic)
        self.assertTrue(self.madrasa.madrasa_profile_pic.name.startswith("madrasa_profile_pics/"))

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_upload_profile_pic_empty_rejected(self):
        resp = self.client.post(reverse("upload_madrasa_profile_pic"), {})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["success"])


class JudgeLoginRedirectTests(TestCase):
    """Linked judge logins are fest staff, not subscribers: they must land on
    their judge portal directly, never on the subscription paywall."""

    def test_active_judge_login_redirects_to_portal(self):
        from applications.program.models import Judge
        madrasa = Madrasa.objects.create(name="Judge Madrasa", reg_number="JM1")
        judge_user = User.objects.create_user(
            email="jredir@t.loc", password="secret123", madrasa=None)
        judge_user.subscribed = False
        judge_user.save()
        Judge.objects.create(madrasa=madrasa, name="Redirect Judge", user=judge_user)

        resp = self.client.post(
            reverse("login"), {"email": "jredir@t.loc", "password": "secret123"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("judge_portal"))

    def test_inactive_judge_login_falls_back_to_subscription(self):
        from applications.program.models import Judge

        madrasa = Madrasa.objects.create(name="Inactive Judge M", reg_number="IJ1")
        judge_user = User.objects.create_user(
            email="jinact@t.loc", password="secret123", madrasa=None)
        # The default is subscription disabled; the admin toggle must be ON
        # for the subscription paywall to be reachable on login.
        judge_user.subscribed = False
        judge_user.save()

        # Also enable the global subscription settings flag (the admin toggle
        # that controls the whole app).
        from applications.subscription.models import SubscriptionSettings
        sub_settings = SubscriptionSettings.get_global()
        sub_settings.subscription_enabled = True
        sub_settings.save()
        Judge.objects.create(madrasa=madrasa, name="Off Judge",
                             user=judge_user, is_active=False)

        resp = self.client.post(
            reverse("login"), {"email": "jinact@t.loc", "password": "secret123"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], reverse("subscription:subscribe"))
