from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from applications.accounts.models import Madrasa, User
from applications.program.models import Position, Grade, GroupPosition, GeneralPosition, Judge
from applications.scoreboard.models import Team
from applications.subscription.models import Subscription


class MarkViewMadrasaScopingTests(TestCase):
    """The scoreboard home page must display marks configured by the logged-in
    madrasa only. Position/Grade/GroupPosition/GeneralPosition rows are scoped
    per madrasa, so unfiltered lookups would leak another madrasa's marks."""

    def setUp(self):
        self.madrasa_a = Madrasa.objects.create(name="Madrasa A", meelad_fest_name="Fest A")
        self.madrasa_b = Madrasa.objects.create(name="Madrasa B", meelad_fest_name="Fest B")

        self.user_a = User.objects.create_user(
            email="a@test.com", phone_number="9000000001",
            madrasa=self.madrasa_a, password="testpassword"
        )
        self.user_b = User.objects.create_user(
            email="b@test.com", phone_number="9000000002",
            madrasa=self.madrasa_b, password="testpassword"
        )

        # Each madrasa configures its own (different) marks
        Position.objects.create(name="first", madrasa=self.madrasa_a, mark=10)
        Position.objects.create(name="first", madrasa=self.madrasa_b, mark=7)
        Grade.objects.create(name="c_grade", madrasa=self.madrasa_a, mark=1)
        Grade.objects.create(name="c_grade", madrasa=self.madrasa_b, mark=0.5)
        GroupPosition.objects.create(name="first", madrasa=self.madrasa_a, mark=20)
        GroupPosition.objects.create(name="first", madrasa=self.madrasa_b, mark=12)
        GeneralPosition.objects.create(name="first", madrasa=self.madrasa_a, mark=25)
        GeneralPosition.objects.create(name="first", madrasa=self.madrasa_b, mark=30)

        for madrasa in (self.madrasa_a, self.madrasa_b):
            Subscription.objects.create(
                institution=madrasa,
                active=True,
                start_date=timezone.now(),
                end_date=timezone.now() + timedelta(days=30),
            )

    def test_home_shows_own_madrasa_marks(self):
        self.client.force_login(self.user_a)
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["first"], 10.0)
        self.assertEqual(resp.context["c_grade"], 1.0)
        self.assertEqual(resp.context["group_first"], 20.0)
        self.assertEqual(resp.context["gen_first"], 25.0)

        self.client.force_login(self.user_b)
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["first"], 7.0)
        self.assertEqual(resp.context["c_grade"], 0.5)
        self.assertEqual(resp.context["group_first"], 12.0)
        self.assertEqual(resp.context["gen_first"], 30.0)
class TeamAddViewTests(TestCase):
    """The Add Team / Edit Team modals submit a hex colour from their
    <input type='color'> picker, but Team.colour stores named keys
    (blue/green/indigo/...). Adding/editing must map the hex back to its key,
    and invalid submissions / bare GET must redirect back to the list —
    never render the missing ``teams/add_team.html`` template.
    """

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Test Madrasa")
        self.user = User.objects.create_user(
            email="sadr@teams.com", phone_number="9876543210",
            madrasa=self.madrasa, password="testpassword"
        )
        self.client.force_login(self.user)

    def test_add_team_maps_hex_colour_and_redirects(self):
        resp = self.client.post(reverse("add_team"), {
            "name": "Al Hilal",
            "leader": "Leader A",
            "colour": "#4f46e5",  # indigo hex from the modal colour picker
        })
        self.assertRedirects(resp, reverse("teams"))
        team = Team.objects.filter(madrasa=self.madrasa, name="Al Hilal").get()
        self.assertEqual(team.colour, "indigo")
        self.assertEqual(team.leader, "Leader A")

    def test_add_team_rejects_missing_name_without_500(self):
        resp = self.client.post(reverse("add_team"), {"leader": "X"})
        self.assertRedirects(resp, reverse("teams"))
        self.assertFalse(Team.objects.filter(leader="X").exists())

    def test_add_team_get_redirects_instead_of_rendering_missing_template(self):
        resp = self.client.get(reverse("add_team"))
        self.assertRedirects(resp, reverse("teams"))

    def test_edit_team_maps_hex_colour(self):
        team = Team.objects.create(name="Old", madrasa=self.madrasa, colour="blue")
        resp = self.client.post(reverse("edit_team", args=[team.pk]), {
            "name": "New",
            "leader": "L",
            "colour": "#dc2626",  # red hex
        })
        self.assertRedirects(resp, reverse("teams"))
        team.refresh_from_db()
        self.assertEqual(team.name, "New")
        self.assertEqual(team.colour, "red")


    def test_add_team_stores_full_staff_details(self):
        resp = self.client.post(reverse("add_team"), {
            "name": "Al Hilal",
            "leader": "Leader A",
            "assistant": "Assistant B",
            "mentor": "Mentor C",
            "assistant_mentor": "Asst Mentor D",
            "girls_leader": "Girls E",
            "girls_leader_assistant": "Girls Asst F",
            "colour": "green",
        })
        self.assertRedirects(resp, reverse("teams"))
        team = Team.objects.get(madrasa=self.madrasa, name="Al Hilal")
        self.assertEqual(team.assistant, "Assistant B")
        self.assertEqual(team.mentor, "Mentor C")
        self.assertEqual(team.assistant_mentor, "Asst Mentor D")
        self.assertEqual(team.girls_leader, "Girls E")
        self.assertEqual(team.girls_leader_assistant, "Girls Asst F")
        self.assertEqual(team.colour, "green")

    def test_edit_team_preserves_non_submitted_staff_fields(self):
        """The old edit modal only posted name/leader/colour, which made the
        ModelForm clear assistant/mentor etc. The full modal posts them all."""
        team = Team.objects.create(
            name="Old", madrasa=self.madrasa, colour="blue",
            assistant="Asst A", mentor="Ment B", girls_leader="GL C",
        )
        resp = self.client.post(reverse("edit_team", args=[team.pk]), {
            "name": "New Name",
            "leader": "Leader X",
            "assistant": "Asst A",
            "mentor": "Ment B",
            "assistant_mentor": "",
            "girls_leader": "GL C",
            "girls_leader_assistant": "",
            "colour": "teal",
        })
        self.assertRedirects(resp, reverse("teams"))
        team.refresh_from_db()
        self.assertEqual(team.name, "New Name")
        self.assertEqual(team.assistant, "Asst A")
        self.assertEqual(team.mentor, "Ment B")
        self.assertEqual(team.girls_leader, "GL C")
        self.assertEqual(team.colour, "teal")

    def test_add_team_maps_arbitrary_hex_to_nearest_palette_colour(self):
        resp = self.client.post(reverse("add_team"), {
            "name": "Custom Colour Team",
            "colour": "#ff9900",  # not in the palette → nearest is yellow #eab308
        })
        self.assertRedirects(resp, reverse("teams"))
        team = Team.objects.get(madrasa=self.madrasa, name="Custom Colour Team")
        self.assertEqual(team.colour, "yellow")

    def test_teams_page_collapses_staff_details_behind_toggle(self):
        """Staff details live in a hidden panel revealed by the card's
        chevron toggle instead of always being expanded."""
        Team.objects.create(
            name="Delta", madrasa=self.madrasa, leader="L",
            assistant="Asst B", mentor="Ment C",
        )
        html = self.client.get(reverse("teams")).content.decode()
        self.assertIn("toggleTeamDetails(", html)
        self.assertIn('id="team-details-', html)
        self.assertIn("hidden mt-2 pt-2", html)  # panel collapsed by default
        self.assertIn("Assistant</dt>", html)    # content present, just hidden

    def test_teams_page_hides_girls_staff_on_boys_only_fest(self):
        self.madrasa.fest_type = "boys"
        self.madrasa.save()
        Team.objects.create(name="Echo", madrasa=self.madrasa, girls_leader="GL X")
        html = self.client.get(reverse("teams")).content.decode()
        self.assertNotIn("Girls Leader", html)


class MarkViewJudgeMadrasaTests(TestCase):
    """A linked judge's homepage must be their madrasa's homepage, resolved
    through the Judge instance (Judge.madrasa) — judge login accounts have
    madrasa=None, so the classic per-user resolution would crash or show an
    empty page. Madrasa users keep the classic resolution."""

    def setUp(self):
        self.judge_madrasa = Madrasa.objects.create(
            name="Judge Madrasa", meelad_fest_name="Fest J")
        self.user_madrasa = Madrasa.objects.create(
            name="User Madrasa", meelad_fest_name="Fest U")

        Position.objects.create(name="first", madrasa=self.judge_madrasa, mark=9)
        Position.objects.create(name="first", madrasa=self.user_madrasa, mark=3)

        self.team_j = Team.objects.create(name="Team J", madrasa=self.judge_madrasa)
        self.team_u = Team.objects.create(name="Team U", madrasa=self.user_madrasa)

        for madrasa in (self.judge_madrasa, self.user_madrasa):
            Subscription.objects.create(
                institution=madrasa,
                active=True,
                start_date=timezone.now(),
                end_date=timezone.now() + timedelta(days=30),
            )

    def _judge_user(self, email, phone, login_madrasa=None):
        user = User.objects.create_user(
            email=email, phone_number=phone,
            madrasa=login_madrasa, password="testpassword")
        Judge.objects.create(
            madrasa=self.judge_madrasa, name=email.split("@")[0], user=user)
        return user

    def test_judge_without_login_madrasa_sees_judge_madrasa_home(self):
        user = self._judge_user("judge1@test.com", "9111111111")
        self.client.force_login(user)
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["meelad_fest_name"], "Fest J")
        self.assertEqual(resp.context["first"], 9.0)
        teams = list(resp.context["teams"])
        self.assertEqual(teams, [self.team_j])

    def test_judge_instance_wins_over_login_madrasa(self):
        user = self._judge_user(
            "judge2@test.com", "9111111112", login_madrasa=self.user_madrasa)
        self.client.force_login(user)
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["meelad_fest_name"], "Fest J")
        self.assertEqual(resp.context["first"], 9.0)
        teams = list(resp.context["teams"])
        self.assertEqual(teams, [self.team_j])

    def test_madrasa_user_home_unchanged(self):
        user = User.objects.create_user(
            email="sadr@test.com", phone_number="9111111113",
            madrasa=self.user_madrasa, password="testpassword")
        self.client.force_login(user)
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["meelad_fest_name"], "Fest U")
        self.assertEqual(resp.context["first"], 3.0)
        teams = list(resp.context["teams"])
        self.assertEqual(teams, [self.team_u])
