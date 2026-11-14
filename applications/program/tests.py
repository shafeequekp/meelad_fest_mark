from django.test import TestCase, SimpleTestCase, override_settings
from django.urls import reverse
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import json
import re
import tempfile
from io import BytesIO
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile

from PIL import Image
from openpyxl import Workbook

from applications.accounts.models import Madrasa, User
from applications.program.models import Category, Program, Student, Prize, Position, Grade, GroupPosition, GeneralPosition, Venue, Judge, Evaluation, EvaluationCriterion
from applications.program import views
from applications.program.forms import CategoryForm
from applications.scoreboard.models import Team
from applications.subscription.models import Subscription
from applications.schedule.models import FestDay, ScheduleEntry

class ResultPosterPDFTests(TestCase):
    def setUp(self):
        # Create Madrasa
        self.madrasa = Madrasa.objects.create(
            name="Test Madrasa",
            meelad_fest_name="Meelad Fest 2026",
            sadr="Test Sadr"
        )
        
        # Create User
        self.user = User.objects.create_user(
            email="sadr@test.com",
            phone_number="9876543210",
            madrasa=self.madrasa,
            password="testpassword"
        )
        
        # Create Category
        self.category = Category.objects.create(
            name="Sub Juniors",
            madrasa=self.madrasa
        )
        
        # Create Program
        self.program = Program.objects.create(
            title="Qira'at",
            is_result_published=True
        )
        # Associate category with program (M2M)
        self.category.programs.add(self.program)
        
        # Create Team
        self.team = Team.objects.create(
            name="Al Hilal",
            madrasa=self.madrasa
        )
        
        # Create Student
        self.student = Student.objects.create(
            full_name="Ahmad",
            gender="male",
            code_number=101,
            category=self.category,
            team=self.team
        )
        
        # Create Position
        self.position = Position.objects.create(
            name="first",
            mark=5.0
        )
        
        # Create Prize
        self.prize = Prize.objects.create(
            student=self.student,
            program=self.program,
            position=self.position
        )

    def test_delete_student_endpoint(self):
        self.client.force_login(self.user)

        student = Student.objects.create(
            full_name="Delete Me",
            gender="male",
            code_number=999,
            category=self.category,
            team=self.team
        )

        url = reverse('delete_student', kwargs={'student_id': student.id})
        response = self.client.post(url, {'next': reverse('category_detail', kwargs={'pk': self.category.id})})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Student.objects.filter(id=student.id).exists())

    def test_edit_team_endpoint(self):
        self.client.force_login(self.user)

        url = reverse('edit_team', kwargs={'team_id': self.team.id})
        response = self.client.post(url, {
            'name': 'Updated Team',
            'leader': 'Updated Leader',
            'assistant': 'Updated Assistant',
        })

        self.assertEqual(response.status_code, 302)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, 'Updated Team')
        self.assertEqual(self.team.leader, 'Updated Leader')
        self.assertEqual(self.team.assistant, 'Updated Assistant')

    def test_delete_program_endpoint(self):
        self.client.force_login(self.user)

        # A program without any recorded result can still be deleted.
        fresh = Program.objects.create(title="Fresh Program")
        url = reverse('delete_program', kwargs={'program_id': fresh.id})
        response = self.client.post(url, {'next': reverse('program_list')})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Program.objects.filter(id=fresh.id).exists())

    def test_delete_program_blocked_once_result_added(self):
        """Guard: once a result (prize) exists for a program it must not be
        deletable — deleting would break result history and ranking."""
        self.client.force_login(self.user)
        self.assertTrue(self.program.prize_set.exists())

        url = reverse('delete_program', kwargs={'program_id': self.program.id})
        response = self.client.post(url, {'next': reverse('program_list')}, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cannot delete')
        self.assertTrue(Program.objects.filter(id=self.program.id).exists())

    def test_download_results_poster_image_status_and_content_type(self):
        # Force login
        self.client.force_login(self.user)
        
        # Get poster download URL
        url = reverse('download_results_poster_image', kwargs={
            'program_id': self.program.id,
            'section': 'boys'
        })
        
        # Call the endpoint
        response = self.client.get(url)
        
        # Assert status and type
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/jpeg')

    def test_poster_download_blocked_until_result_published(self):
        """Only published results may be downloaded as posters; the endpoint
        answers with a JSON error the results page can toast."""
        self.client.force_login(self.user)
        self.program.is_result_published = False
        self.program.save(update_fields=['is_result_published'])

        url = reverse('download_results_poster_image', kwargs={
            'program_id': self.program.id,
            'section': 'boys'
        })
        response = self.client.get(url)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertIn('Publish', response.json()['details'])

class DeleteProgramConfirmDialogTests(TestCase):
    """Delete/remove confirmations on the program pages must use the shared
    MeeladConfirm dialog (data-confirm forms / promise-based helpers), never
    the native confirm() popup."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Test Madrasa", meelad_fest_name="Fest")
        self.user = User.objects.create_user(
            email="sadr@test.com", phone_number="9876543210",
            madrasa=self.madrasa, password="testpassword"
        )
        self.category = Category.objects.create(name="Sub Juniors", madrasa=self.madrasa)
        self.program = Program.objects.create(title="Qira'at", madrasa=self.madrasa)
        self.category.programs.add(self.program)

    def test_program_list_uses_shared_confirm_dialog(self):
        """Both delete entry points on the Programs page (card ✕ badge and the
        card's actions menu) confirm through the shared styled dialog."""
        self.client.force_login(self.user)
        response = self.client.get(reverse('program_list'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        # Banner ✕ form + actions-menu form of the rendered card both carry it.
        self.assertGreaterEqual(html.count('data-confirm="Delete this program?"'), 2)
        self.assertNotIn('return confirm(', html)
        self.assertNotIn('!confirm(', html)
        # The dialog implementation ships with the included header.
        self.assertIn('window.MeeladConfirm', html)

    def test_general_programs_uses_shared_confirm_dialog(self):
        """The general-programs page confirms program deletion (accordion item)
        and team removal (removeTeam helper) through the shared dialog."""
        Program.objects.create(title="Empty General", is_general=True,
                               section="boys", madrasa=self.madrasa)
        self.client.force_login(self.user)
        response = self.client.get(reverse('general_programs'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('data-confirm="Delete this program?"', html)
        self.assertIn('window.MeeladConfirm.show(', html)
        self.assertNotIn('return confirm(', html)
        self.assertNotIn('!confirm(', html)

    def test_venue_list_uses_shared_confirm_dialog(self):
        """Deleting a venue confirms through the shared styled dialog."""
        Venue.objects.create(name="Main Hall", madrasa=self.madrasa)
        self.client.force_login(self.user)
        response = self.client.get(reverse('venue_list'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('data-confirm="Delete venue', html)
        self.assertNotIn('return confirm(', html)


class SaveConfigMadrasaScopingTests(TestCase):
    """save_config must create/update Position, Grade, GroupPosition and
    GeneralPosition rows scoped to the logged-in madrasa, so that marks saved
    by one madrasa never leak into another madrasa's config."""

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

    def _save_config(self, user, marks):
        self.client.force_login(user)
        resp = self.client.post(reverse("save_config"), {
            "first_prize": marks["first"],
            "second_prize": marks["second"],
            "third_prize": marks["third"],
            "grade_a": marks["grade_a"],
            "grade_b": marks["grade_b"],
            "grade_c": marks["grade_c"],
            "group_first": marks["group_first"],
            "group_second": marks["group_second"],
            "group_third": marks["group_third"],
            "general_first": marks["general_first"],
            "general_second": marks["general_second"],
            "general_third": marks["general_third"],
            "max_programs": marks["max_programs"],
            "fest_type": "meelad",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.content)["status"], "success")

    def test_marks_are_isolated_per_madrasa(self):
        self._save_config(self.user_a, {
            "first": "10", "second": "8", "third": "6",
            "grade_a": "5", "grade_b": "3", "grade_c": "1",
            "group_first": "20", "group_second": "15", "group_third": "10",
            "general_first": "25", "general_second": "20", "general_third": "15",
            "max_programs": "3",
        })
        self._save_config(self.user_b, {
            "first": "7", "second": "5", "third": "3",
            "grade_a": "2", "grade_b": "1", "grade_c": "0.5",
            "group_first": "12", "group_second": "9", "group_third": "6",
            "general_first": "30", "general_second": "25", "general_third": "20",
            "max_programs": "2",
        })

        # Madrasa A keeps its own values
        self.assertEqual(Position.objects.get(name="first", madrasa=self.madrasa_a).mark, 10.0)
        self.assertEqual(Position.objects.get(name="second", madrasa=self.madrasa_a).mark, 8.0)
        self.assertEqual(Position.objects.get(name="third", madrasa=self.madrasa_a).mark, 6.0)
        self.assertEqual(Grade.objects.get(name="a_grade", madrasa=self.madrasa_a).mark, 5.0)
        self.assertEqual(Grade.objects.get(name="b_grade", madrasa=self.madrasa_a).mark, 3.0)
        self.assertEqual(Grade.objects.get(name="c_grade", madrasa=self.madrasa_a).mark, 1.0)
        self.assertEqual(GroupPosition.objects.get(name="first", madrasa=self.madrasa_a).mark, 20.0)
        self.assertEqual(GroupPosition.objects.get(name="second", madrasa=self.madrasa_a).mark, 15.0)
        self.assertEqual(GroupPosition.objects.get(name="third", madrasa=self.madrasa_a).mark, 10.0)
        self.assertEqual(GeneralPosition.objects.get(name="first", madrasa=self.madrasa_a).mark, 25.0)
        self.assertEqual(GeneralPosition.objects.get(name="second", madrasa=self.madrasa_a).mark, 20.0)
        self.assertEqual(GeneralPosition.objects.get(name="third", madrasa=self.madrasa_a).mark, 15.0)

        # Madrasa B has its own different values
        self.assertEqual(Position.objects.get(name="first", madrasa=self.madrasa_b).mark, 7.0)
        self.assertEqual(Position.objects.get(name="second", madrasa=self.madrasa_b).mark, 5.0)
        self.assertEqual(Position.objects.get(name="third", madrasa=self.madrasa_b).mark, 3.0)
        self.assertEqual(Grade.objects.get(name="a_grade", madrasa=self.madrasa_b).mark, 2.0)
        self.assertEqual(Grade.objects.get(name="b_grade", madrasa=self.madrasa_b).mark, 1.0)
        self.assertEqual(Grade.objects.get(name="c_grade", madrasa=self.madrasa_b).mark, 0.5)
        self.assertEqual(GroupPosition.objects.get(name="first", madrasa=self.madrasa_b).mark, 12.0)
        self.assertEqual(GroupPosition.objects.get(name="second", madrasa=self.madrasa_b).mark, 9.0)
        self.assertEqual(GroupPosition.objects.get(name="third", madrasa=self.madrasa_b).mark, 6.0)
        self.assertEqual(GeneralPosition.objects.get(name="first", madrasa=self.madrasa_b).mark, 30.0)
        self.assertEqual(GeneralPosition.objects.get(name="second", madrasa=self.madrasa_b).mark, 25.0)
        self.assertEqual(GeneralPosition.objects.get(name="third", madrasa=self.madrasa_b).mark, 20.0)

    def test_saving_again_does_not_duplicate_rows(self):
        self._save_config(self.user_a, {
            "first": "10", "second": "8", "third": "6",
            "grade_a": "5", "grade_b": "3", "grade_c": "1",
            "group_first": "20", "group_second": "15", "group_third": "10",
            "general_first": "25", "general_second": "20", "general_third": "15",
            "max_programs": "3",
        })
        # Save again with a changed mark -> update, not create
        self._save_config(self.user_a, {
            "first": "99", "second": "8", "third": "6",
            "grade_a": "5", "grade_b": "3", "grade_c": "1",
            "group_first": "20", "group_second": "15", "group_third": "10",
            "general_first": "25", "general_second": "20", "general_third": "15",
            "max_programs": "3",
        })
        self.assertEqual(Position.objects.filter(name="first", madrasa=self.madrasa_a).count(), 1)
        self.assertEqual(Position.objects.get(name="first", madrasa=self.madrasa_a).mark, 99.0)


class SavePrizeMadrasaScopingTests(TestCase):
    """save_prize must resolve Position/Grade records for the program's own
    madrasa. Previously the C-grade lookup ignored madrasa, which either
    crashed (MultipleObjectsReturned) or applied another madrasa's mark."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Test Madrasa", meelad_fest_name="Fest")
        self.user = User.objects.create_user(
            email="sadr@test.com", phone_number="9876543210",
            madrasa=self.madrasa, password="testpassword"
        )
        self.category = Category.objects.create(name="Sub Juniors", madrasa=self.madrasa)
        self.program = Program.objects.create(title="Qira'at")
        self.category.programs.add(self.program)
        self.team = Team.objects.create(name="Al Hilal", madrasa=self.madrasa)
        self.student = Student.objects.create(
            full_name="Ahmad", gender="male", code_number=101,
            category=self.category, team=self.team
        )

    def test_save_prize_uses_this_madrasa_c_grade(self):
        # A second madrasa also has its own c_grade -> proves scoping matters
        other_madrasa = Madrasa.objects.create(name="Other Madrasa", meelad_fest_name="Other")
        Grade.objects.create(name="c_grade", madrasa=other_madrasa, mark=999)
        Grade.objects.create(name="c_grade", madrasa=self.madrasa, mark=2.5)

        self.client.force_login(self.user)
        resp = self.client.post(
            reverse("save-prize", kwargs={"program_id": self.program.id}),
            data=json.dumps({"gradeC": self.student.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        prize = Prize.objects.get(student=self.student, program=self.program, grade__isnull=False)
        self.assertEqual(prize.grade.name, "c_grade")
        self.assertEqual(prize.grade.madrasa_id, self.madrasa.id)
        self.assertEqual(prize.grade.mark, 2.5)

    def test_save_prize_uses_program_madrasa_not_user_madrasa(self):
        # The logged-in user belongs to self.madrasa, but the program belongs
        # to a different madrasa -> prize marks must come from the program's
        # madrasa, never the user's.
        program_madrasa = Madrasa.objects.create(name="Program Madrasa", meelad_fest_name="Fest P")
        category_b = Category.objects.create(name="Cat B", madrasa=program_madrasa)
        program_b = Program.objects.create(title="Qira'at B")
        category_b.programs.add(program_b)

        Grade.objects.create(name="c_grade", madrasa=program_madrasa, mark=3.5)
        Grade.objects.create(name="c_grade", madrasa=self.madrasa, mark=999)

        self.client.force_login(self.user)
        resp = self.client.post(
            reverse("save-prize", kwargs={"program_id": program_b.id}),
            data=json.dumps({"gradeC": self.student.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        prize = Prize.objects.get(student=self.student, program=program_b, grade__isnull=False)
        self.assertEqual(prize.grade.madrasa_id, program_madrasa.id)
        self.assertEqual(prize.grade.mark, 3.5)


class SaveGeneralPrizeMadrasaScopingTests(TestCase):
    """save_general_prize must store GeneralPosition records scoped to the
    program's madrasa. Previously get_or_create(name=...) ignored madrasa,
    which either crashed (MultipleObjectsReturned) or reused another madrasa's
    general-program mark."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Test Madrasa", meelad_fest_name="Fest")
        self.user = User.objects.create_user(
            email="sadr@test.com", phone_number="9876543210",
            madrasa=self.madrasa, password="testpassword"
        )
        self.program = Program.objects.create(title="General Quiz", is_general=True)
        self.team = Team.objects.create(name="Al Hilal", madrasa=self.madrasa)

        # A second madrasa already configured its own general marks
        other_madrasa = Madrasa.objects.create(name="Other Madrasa", meelad_fest_name="Other")
        GeneralPosition.objects.create(name="first", madrasa=other_madrasa, mark=999)

    def test_save_general_prize_uses_this_madrasa_general_position(self):
        # The "add a team first" guard requires at least one participating
        # team before a team-wise result can be saved.
        self.program.general_teams.add(self.team)
        self.client.force_login(self.user)
        resp = self.client.post(
            reverse("save_general_prize", kwargs={"program_id": self.program.id}),
            data=json.dumps({"first": self.team.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        prize = Prize.objects.get(team=self.team, program=self.program, general_program_position__isnull=False)
        self.assertEqual(prize.general_program_position.name, "first")
        self.assertEqual(prize.general_program_position.madrasa_id, self.madrasa.id)
        # Must NOT have picked up the other madrasa's mark (999)
        self.assertNotEqual(prize.general_program_position.mark, 999)

    def test_save_general_prize_uses_program_madrasa_not_user_madrasa(self):
        # The logged-in user belongs to self.madrasa, but the general program's
        # teams belong to a different madrasa -> general marks must come from
        # the program's madrasa, never the user's.
        program_madrasa = Madrasa.objects.create(name="Program Madrasa", meelad_fest_name="Fest P")
        team_b = Team.objects.create(name="Team B", madrasa=program_madrasa)
        program_b = Program.objects.create(title="General Quiz B", is_general=True)
        program_b.general_teams.add(team_b)

        GeneralPosition.objects.create(name="first", madrasa=program_madrasa, mark=5)
        GeneralPosition.objects.create(name="first", madrasa=self.madrasa, mark=999)

        self.client.force_login(self.user)
        resp = self.client.post(
            reverse("save_general_prize", kwargs={"program_id": program_b.id}),
            data=json.dumps({"first": team_b.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        prize = Prize.objects.get(team=team_b, program=program_b, general_program_position__isnull=False)
        self.assertEqual(prize.general_program_position.madrasa_id, program_madrasa.id)
        self.assertEqual(prize.general_program_position.mark, 5)


class TeamLeaderboardTests(TestCase):
    """get_team_leaderboard builds the public team scoreboard used by the
    parents' sharing link (category-wise + group/general + grand totals)."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Test Madrasa", meelad_fest_name="Test Fest")
        self.red = Team.objects.create(name="Red", madrasa=self.madrasa, colour="red")
        self.blue = Team.objects.create(name="Blue", madrasa=self.madrasa, colour="blue")

        self.cat = Category.objects.create(name="Senior", madrasa=self.madrasa)
        self.prog_a = Program.objects.create(title="Tilawat", slug="tilawat")  # not published
        self.prog_a.category_set.add(self.cat)
        self.prog_b = Program.objects.create(title="Speech", slug="speech", is_result_published=True)
        self.prog_b.category_set.add(self.cat)

        self.stu1 = Student.objects.create(full_name="Stu 1", team=self.red, category=self.cat, gender="male")
        self.stu2 = Student.objects.create(full_name="Stu 2", team=self.blue, category=self.cat, gender="female")

        self.pos_first, _ = Position.objects.get_or_create(name="first", defaults={"madrasa": self.madrasa, "mark": 10})
        self.grade_a, _ = Grade.objects.get_or_create(name="a_grade", defaults={"madrasa": self.madrasa, "mark": 2})
        self.general_first, _ = GeneralPosition.objects.get_or_create(name="first", defaults={"madrasa": self.madrasa, "mark": 7})

    def test_published_only_and_breakdown(self):
        # Unpublished program prize -> must not count
        Prize.objects.create(student=self.stu1, program=self.prog_a, position=self.pos_first)
        # Published individual prize (position + grade)
        Prize.objects.create(student=self.stu2, program=self.prog_b, position=self.pos_first, grade=self.grade_a)
        # Published general (team-level) prize for blue team
        general_prog = Program.objects.create(title="General Quiz", slug="gquiz", is_general=True, is_result_published=True)
        Prize.objects.create(team=self.blue, program=general_prog, general_program_position=self.general_first)

        rows = Prize.get_team_leaderboard(self.madrasa)

        by_name = {r["team"].name: r for r in rows}
        # Red only has an unpublished prize -> 0 everywhere
        self.assertAlmostEqual(by_name["Red"]["grand_total"], 0)
        # Blue: 10 (pos) + 2 (grade) + 7 (general) = 19
        blue = by_name["Blue"]
        self.assertAlmostEqual(blue["individual_total"], 12)
        self.assertAlmostEqual(blue["general_total"], 7)
        self.assertAlmostEqual(blue["grand_total"], 19)
        self.assertEqual(blue["category_rows"][0]["girls"], 12)
        self.assertEqual(blue["category_rows"][0]["boys"], 0)
        # Sorted by grand total desc, ranks assigned
        self.assertEqual(rows[0]["team"].name, "Blue")
        self.assertEqual(rows[0]["rank"], 1)

    def test_grade_only_prize_still_counts(self):
        # A prize with only a grade (no position) must still count its mark.
        Prize.objects.create(student=self.stu1, program=self.prog_b, grade=self.grade_a)
        rows = Prize.get_team_leaderboard(self.madrasa)
        by_name = {r["team"].name: r for r in rows}
        self.assertAlmostEqual(by_name["Red"]["individual_total"], 2)
        self.assertAlmostEqual(by_name["Red"]["grand_total"], 2)

def _make_test_logo(width=2000, height=500):
    """A high-res solid-colour PNG used to exercise logo downscaling."""
    img = Image.new("RGBA", (width, height), (200, 30, 60, 255))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class LogoOptimizeTests(SimpleTestCase):
    """The result-poster fest-logo is downscaled before being embedded as a
    data URI so the poster HTML stays small (faster Chrome render)."""

    def test_downscales_large_logo(self):
        raw = _make_test_logo(2000, 500)
        data, mime = views._optimize_fest_logo_bytes(raw, "logo.png")
        self.assertEqual(mime, "image/png")
        img = Image.open(BytesIO(data))
        self.assertLessEqual(img.width, views._LOGO_MAX_WIDTH)
        self.assertLess(len(data), len(raw))

    def test_returns_fallback_on_bad_bytes(self):
        data, mime = views._optimize_fest_logo_bytes(b"not-an-image", "logo.png")
        self.assertEqual(data, b"not-an-image")
        self.assertEqual(mime, "image/png")

    def test_fest_logo_data_uri_none_without_logo(self):
        m = Madrasa(name="M")
        self.assertIsNone(views._fest_logo_data_uri(m))


class PosterCacheTests(SimpleTestCase):
    """Rendered posters are cached to disk keyed by the resolved HTML so repeat
    downloads skip the expensive headless-Chrome render."""

    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_cache_roundtrip(self):
        html_a = "POSTER_DATA A"
        html_b = "POSTER_DATA B"
        self.assertIsNone(views._poster_cached(html_a))
        views._store_poster_cache(html_a, b"JPEG-A")
        views._store_poster_cache(html_b, b"JPEG-B")
        self.assertEqual(views._poster_cached(html_a), b"JPEG-A")
        self.assertEqual(views._poster_cached(html_b), b"JPEG-B")
        # Different content -> different cache keys / distinct files.
        self.assertNotEqual(
            views._poster_cache_path(html_a), views._poster_cache_path(html_b)
        )
        root = Path(settings.MEDIA_ROOT) / views._POSTER_CACHE_DIR
        self.assertEqual(len(list(root.glob("poster_*.jpg"))), 2)
class GeneralProgramMadrasaOwnershipTests(TestCase):
    """General programs must be owned by a madrasa so they appear in the list
    even before any team is attached, and auto-include all (current + later)
    teams of that madrasa."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Test Madrasa", meelad_fest_name="Fest")
        self.user = User.objects.create_user(
            email="sadr@test.com", phone_number="9876543200",
            madrasa=self.madrasa, password="testpassword",
        )
        self.team_a = Team.objects.create(name="Alpha", madrasa=self.madrasa)
        self.team_b = Team.objects.create(name="Beta", madrasa=self.madrasa)

    def test_create_general_program_attaches_madrasa_and_all_teams(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("general_programs"), {
            "action": "add",
            "title": "New General Quiz",
            "section": "boys",
        })
        self.assertEqual(resp.status_code, 302)
        program = Program.objects.get(title="New General Quiz")
        # Owned by the madrasa and has both teams as participants by default.
        self.assertEqual(program.madrasa_id, self.madrasa.id)
        self.assertEqual(set(program.general_teams.values_list("id", flat=True)),
                         {self.team_a.id, self.team_b.id})

    def test_general_program_list_shows_program_without_any_team(self):
        self.client.force_login(self.user)
        # Manually create a general program without teams (only madrasa set).
        Program.objects.create(title="Empty General", is_general=True,
                               section="boys", madrasa=self.madrasa)
        resp = self.client.get(reverse("general_programs"))
        self.assertEqual(resp.status_code, 200)
        titles = [p.title for p in resp.context["boys_programs"]]
        self.assertIn("Empty General", titles)

    def test_new_team_auto_added_to_existing_general_program(self):
        Program.objects.create(title="Existing General", is_general=True,
                               section="boys", madrasa=self.madrasa)
        # A team created *after* the program is auto-synced into it.
        new_team = Team.objects.create(name="Gamma", madrasa=self.madrasa)
        program = Program.objects.get(title="Existing General")
        self.assertIn(new_team.id, program.general_teams.values_list("id", flat=True))

class LoadTeamStudentsSectionFilterTests(TestCase):
    """load_team_students must list only the team members of the program's
    section gender: Boys → male students, Girls → female students."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Test Madrasa", meelad_fest_name="Fest")
        self.user = User.objects.create_user(
            email="sadr@test.com", phone_number="9876543201",
            madrasa=self.madrasa, password="testpassword",
        )
        self.team = Team.objects.create(name="Alpha", madrasa=self.madrasa)
        self.boys_program = Program.objects.create(
            title="Boys General", is_general=True, section="boys", madrasa=self.madrasa,
        )
        self.girls_program = Program.objects.create(
            title="Girls General", is_general=True, section="girls", madrasa=self.madrasa,
        )
        self.male = Student.objects.create(
            full_name="Ahmad", gender="male", code_number=101, team=self.team,
        )
        self.female = Student.objects.create(
            full_name="Ayesha", gender="female", code_number=102, team=self.team,
        )

    def test_boys_section_returns_only_males(self):
        self.client.force_login(self.user)
        resp = self.client.get(
            reverse("load_team_students"),
            {"team_id": self.team.id, "section": "boys"},
        )
        self.assertEqual(resp.status_code, 200)
        ids = [s["id"] for s in resp.json()]
        self.assertIn(self.male.id, ids)
        self.assertNotIn(self.female.id, ids)

    def test_girls_section_returns_only_females(self):
        self.client.force_login(self.user)
        resp = self.client.get(
            reverse("load_team_students"),
            {"team_id": self.team.id, "section": "girls"},
        )
        self.assertEqual(resp.status_code, 200)
        ids = [s["id"] for s in resp.json()]
        self.assertIn(self.female.id, ids)
        self.assertNotIn(self.male.id, ids)

    def test_no_section_falls_back_to_all_members(self):
        self.client.force_login(self.user)
        resp = self.client.get(
            reverse("load_team_students"),
            {"team_id": self.team.id},
        )
        self.assertEqual(resp.status_code, 200)
        ids = [s["id"] for s in resp.json()]
        self.assertEqual(set(ids), {self.male.id, self.female.id})

    def test_general_programs_page_renders_boys_program(self):
        self.client.force_login(self.user)
        self.boys_program.general_teams.add(self.team)
        resp = self.client.get(reverse("general_programs"))
        self.assertEqual(resp.status_code, 200)
        titles = [p.title for p in resp.context["boys_programs"]]
        self.assertIn("Boys General", titles)


class FestTypeSectionVisibilityTests(TestCase):
    """On a girls-only fest the Boys section/tab must never render on the
    category detail page, and vice-versa for boys-only."""

    def _setup(self, fest_type):
        self.madrasa = Madrasa.objects.create(
            name="Test Madrasa", meelad_fest_name="Fest", fest_type=fest_type
        )
        self.user = User.objects.create_user(
            email="sadr@fest.com", phone_number="9876543206",
            madrasa=self.madrasa, password="testpassword",
        )
        self.category = Category.objects.create(name="Senior", madrasa=self.madrasa)
        self.client.force_login(self.user)

    def test_girls_only_hides_boys_section(self):
        self._setup(Madrasa.FEST_TYPE_GIRLS)
        resp = self.client.get(reverse("category_detail", kwargs={"pk": self.category.pk}))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertNotIn("Boys Section", html)
        self.assertNotIn("id=\"boysSection\"", html)
        self.assertIn("Girls Section", html)

    def test_boys_only_hides_girls_section(self):
        self._setup(Madrasa.FEST_TYPE_BOYS)
        resp = self.client.get(reverse("category_detail", kwargs={"pk": self.category.pk}))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertNotIn("Girls Section", html)
        self.assertNotIn("id=\"girlsSection\"", html)
        self.assertIn("Boys Section", html)


class InitialConfigFestTypeTests(TestCase):
    """save_config used to force fest_type back to 'both' whenever the
    initial-config modal didn't post the field — silently undoing the section
    chosen at signup (the config modal runs right after signup). Absent or
    invalid values must leave the existing choice untouched."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(
            name="Test Madrasa", meelad_fest_name="Fest", fest_type=Madrasa.FEST_TYPE_GIRLS
        )
        self.user = User.objects.create_user(
            email="cfg@fest.com", phone_number="9876543207",
            madrasa=self.madrasa, password="testpassword",
        )
        self.client.force_login(self.user)

    def test_save_config_without_fest_type_keeps_signup_selection(self):
        resp = self.client.post(reverse("save_config"), {"max_programs": "3"})
        self.assertEqual(resp.status_code, 200)
        self.madrasa.refresh_from_db()
        self.assertEqual(self.madrasa.fest_type, Madrasa.FEST_TYPE_GIRLS)
        self.user.refresh_from_db()
        self.assertTrue(self.user.config_done)

    def test_save_config_with_fest_type_updates_it(self):
        resp = self.client.post(reverse("save_config"), {"max_programs": "3", "fest_type": "boys"})
        self.assertEqual(resp.status_code, 200)
        self.madrasa.refresh_from_db()
        self.assertEqual(self.madrasa.fest_type, Madrasa.FEST_TYPE_BOYS)

    def test_save_config_with_invalid_fest_type_keeps_existing(self):
        resp = self.client.post(reverse("save_config"), {"fest_type": "nonsense"})
        self.assertEqual(resp.status_code, 200)
        self.madrasa.refresh_from_db()
        self.assertEqual(self.madrasa.fest_type, Madrasa.FEST_TYPE_GIRLS)


class CategoryTeamNoneCrashTests(TestCase):
    """Regression: building ``?team=None`` redirects (raw None from
    request.GET) used to 500 in CategoryView — ``Team.objects.get(id='None')``
    raises ValueError. `?team=None`, garbage, or a missing team must be
    treated as "no team", and add/edit redirects must never emit `team=None`.
    """

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Test Madrasa", meelad_fest_name="Fest")
        self.user = User.objects.create_user(
            email="sadr@cat.com", phone_number="9876543205",
            madrasa=self.madrasa, password="testpassword",
        )
        self.team = Team.objects.create(name="Alpha", madrasa=self.madrasa)
        self.client.force_login(self.user)

    def test_categories_page_with_literal_none_team_does_not_crash(self):
        resp = self.client.get(reverse("categories") + "?team=None")
        self.assertEqual(resp.status_code, 200)
        # Falls back to the madrasa's first team for the team context.
        self.assertEqual(resp.context["team"], self.team)

    def test_categories_page_with_garbage_team_does_not_crash(self):
        for bad in ("nonsense", "nulldata", "999999"):
            resp = self.client.get(reverse("categories") + f"?team={bad}")
            self.assertEqual(resp.status_code, 200, f"team={bad} crashed")

    def test_add_category_without_team_redirects_cleanly(self):
        resp = self.client.post(reverse("add_category"), {"name": "Senior", "description": "Top group"})
        self.assertRedirects(resp, reverse("categories"))
        self.assertNotIn("team=None", resp.url)

    def test_add_category_preserves_valid_team_context(self):
        resp = self.client.post(
            reverse("add_category") + f"?team={self.team.id}",
            {"name": "Senior 2"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f"team={self.team.id}", resp.url)

    def test_category_detail_with_literal_none_team_does_not_crash(self):
        category = Category.objects.create(name="Senior", madrasa=self.madrasa)
        resp = self.client.get(
            reverse("category_detail", kwargs={"pk": category.pk}) + "?team=None"
        )
        self.assertEqual(resp.status_code, 200)


class DuplicatePrizeValidationTests(TestCase):
    """The same participant/team/group cannot win more than one position (or
    grade) in the same program's result. save_prize / save_general_prize /
    save_group_prize must reject duplicate selections."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Test Madrasa", meelad_fest_name="Fest")
        self.user = User.objects.create_user(
            email="sadr@test.com", phone_number="9876543202",
            madrasa=self.madrasa, password="testpassword",
        )
        self.category = Category.objects.create(name="Sub Juniors", madrasa=self.madrasa)
        self.team_a = Team.objects.create(name="Alpha", madrasa=self.madrasa)
        self.team_b = Team.objects.create(name="Beta", madrasa=self.madrasa)
        self.s1 = Student.objects.create(
            full_name="Ahmad", gender="male", code_number=101,
            category=self.category, team=self.team_a,
        )
        self.s2 = Student.objects.create(
            full_name="Bilaal", gender="male", code_number=102,
            category=self.category, team=self.team_b,
        )

    def test_individual_same_student_two_positions_rejected(self):
        self.client.force_login(self.user)
        program = Program.objects.create(title="Individual")
        self.category.programs.add(program)
        resp = self.client.post(
            reverse("save-prize", kwargs={"program_id": program.id}),
            data=json.dumps({"first": self.s1.id, "second": self.s1.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["message"], "error")
        self.assertIn("more than one position", resp.json()["details"])
        # Nothing was persisted because the request is rejected before saving.
        self.assertFalse(Prize.objects.filter(program=program).exists())

    def test_individual_same_student_two_grades_rejected(self):
        self.client.force_login(self.user)
        program = Program.objects.create(title="Individual Grades")
        self.category.programs.add(program)
        resp = self.client.post(
            reverse("save-prize", kwargs={"program_id": program.id}),
            data=json.dumps({"gradeA": self.s1.id, "gradeB": self.s1.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["message"], "error")
        self.assertIn("more than one grade", resp.json()["details"])
        self.assertFalse(Prize.objects.filter(program=program).exists())

    def test_general_same_team_two_positions_rejected(self):
        self.client.force_login(self.user)
        program = Program.objects.create(
            title="General", is_general=True, section="boys", madrasa=self.madrasa,
        )
        program.general_teams.add(self.team_a, self.team_b)
        resp = self.client.post(
            reverse("save_general_prize", kwargs={"program_id": program.id}),
            data=json.dumps({"first": self.team_a.id, "second": self.team_a.id}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["message"], "error")
        self.assertIn("more than one position", resp.json()["details"])
        self.assertFalse(Prize.objects.filter(program=program).exists())

    def test_group_same_group_two_positions_rejected(self):
        self.client.force_login(self.user)
        program = Program.objects.create(title="Group", is_group=True)
        # A group is a Prize row whose participants are its members.
        group = Prize.objects.create(team=self.team_a, program=program)
        group.participants.add(self.s1, self.s2)
        resp = self.client.post(
            reverse("save_group_prize", kwargs={"program_id": program.id}),
            data=json.dumps({"first": str(group.id), "second": str(group.id)}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["message"], "error")
        self.assertIn("more than one position", resp.json()["details"])
class CategoryNameNormalizationTests(TestCase):
    """User-entered category names are strip()ed and Title-Cased on save."""

    def test_add_category_name_is_stripped_and_title_cased(self):
        form = CategoryForm(data={
            "name": "  SEnIoR   bOYS  ",
            "description": "",
        })
        self.assertTrue(form.is_valid(), dict(form.errors))
        category = form.save(commit=False)
        self.assertEqual(category.name, "Senior Boys")

    def test_mixed_and_all_caps_are_wiped_to_title_case(self):
        form = CategoryForm(data={"name": "SUB JUNIORS", "description": ""})
        self.assertTrue(form.is_valid(), dict(form.errors))
        self.assertEqual(form.save(commit=False).name, "Sub Juniors")

    def test_whitespace_only_name_is_invalid(self):
        # strip() should not turn "   " into an invalid empty name silently;
        # the form must still reject a blank name.
        form = CategoryForm(data={"name": "   ", "description": ""})
        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)

    def test_single_word_is_capitalized(self):
        form = CategoryForm(data={"name": "senior", "description": ""})
        self.assertTrue(form.is_valid(), dict(form.errors))
        self.assertEqual(form.save(commit=False).name, "Senior")

    def test_edit_category_name_is_normalized_too(self):
        category = Category.objects.create(name="Old Name")
        form = CategoryForm(data={"name": "  new   NAME ", "description": ""},
                            instance=category)
        self.assertTrue(form.is_valid(), dict(form.errors))
        form.save()
        category.refresh_from_db()
        self.assertEqual(category.name, "New Name")

    def test_end_to_end_add_view_saves_normalized_name(self):
        madrasa = Madrasa.objects.create(
            name="Test Madrasa", meelad_fest_name="Fest")
        user = User.objects.create_user(
            email="cat@test.com", phone_number="9876543211",
            madrasa=madrasa, password="testpassword")
        self.client.force_login(user)
        url = reverse("add_category")
        response = self.client.post(url, {
            "name": "  MIni   fOOTBALL  ", "description": "",
        })
        self.assertEqual(response.status_code, 302)  # redirects on success
        saved = Category.objects.get(madrasa=madrasa)
        self.assertEqual(saved.name, "Mini Football")


class ProgramUploadCategoryMappingTests(TestCase):
    """Program bulk upload must link each program to its own category.

    Regression: the view used to re-fetch created programs by title, so when
    two programs shared a title in different categories, both categories ended
    up linked to a single program (or the wrong one).
    """

    _HEADERS = ["Title", "Type", "Section", "Category", "Non-Stage", "Description"]

    def setUp(self):
        self.madrasa = Madrasa.objects.create(
            name="Upload Madrasa", meelad_fest_name="Fest",
            fest_type=Madrasa.FEST_TYPE_BOTH,
        )
        self.user = User.objects.create_user(
            email="upload@test.com", phone_number="9876543222",
            madrasa=self.madrasa, password="testpassword",
        )
        self.alpha = Category.objects.create(name="Alpha", madrasa=self.madrasa)
        self.beta = Category.objects.create(name="Beta", madrasa=self.madrasa)

    def _excel(self, rows):
        wb = Workbook()
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(self._HEADERS)
        for row in rows:
            ws.append(row)
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        return SimpleUploadedFile("programs.xlsx", buf.read())

    def test_same_title_programs_link_to_their_own_category(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("upload-programs"), {
            "file": self._excel([
                ["Debate", "individual", "boys", "Alpha", "no", ""],
                ["Debate", "individual", "boys", "Beta", "no", ""],
            ]),
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["created"], 2, data["errors"])
        self.assertEqual(data["skipped"], 0, data["errors"])
        # Two distinct programs were created...
        programs = list(Program.objects.filter(
            title="Debate", madrasa=self.madrasa))
        self.assertEqual(len(programs), 2)
        # ...and each category is linked to exactly one of them (its own).
        self.assertEqual(self.alpha.programs.count(), 1)
        self.assertEqual(self.beta.programs.count(), 1)
        self.assertNotEqual(
            self.alpha.programs.first().id, self.beta.programs.first().id)

    def test_girls_row_links_via_programs_for_girls(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("upload-programs"), {
            "file": self._excel([
                ["Recitation", "individual", "girls", "Alpha", "no", ""],
            ]),
        })
        data = response.json()
        self.assertEqual(data["created"], 1, data["errors"])
        self.assertEqual(self.alpha.programs_for_girls.count(), 1)
        self.assertEqual(self.alpha.programs.count(), 0)

    def test_general_program_auto_includes_all_teams(self):
        self.client.force_login(self.user)
        Team.objects.create(name="Al Hilal", madrasa=self.madrasa)
        Team.objects.create(name="Al Fath", madrasa=self.madrasa)
        response = self.client.post(reverse("upload-programs"), {
            "file": self._excel([
                ["Pentathlon", "general", "boys", "", "no", ""],
            ]),
        })
        data = response.json()
        self.assertEqual(data["created"], 1, data["errors"])
        prog = Program.objects.get(title="Pentathlon", madrasa=self.madrasa)
        self.assertEqual(prog.general_teams.count(), 2)

    def test_missing_category_for_individual_is_skipped(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("upload-programs"), {
            "file": self._excel([
                ["Solo", "individual", "boys", "", "no", ""],
            ]),
        })
        data = response.json()
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["skipped"], 1)
        self.assertIn("Category is required", data["errors"][0])


class ProgramListAddProgramTests(TestCase):
    """Expandable 'Add Program' form on the Programs Dashboard."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(
            name="Dashboard Madrasa", meelad_fest_name="Fest",
            fest_type=Madrasa.FEST_TYPE_BOTH,
        )
        self.user = User.objects.create_user(
            email="addprog@test.com", phone_number="9876543233",
            madrasa=self.madrasa, password="testpassword",
        )
        self.cat = Category.objects.create(name="Sub Juniors", madrasa=self.madrasa)

    def test_add_individual_program_links_category(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("add_program"), {
            "title": "  Arabic Speech  ", "type": "individual", "section": "boys",
            "category_id": self.cat.id, "non_stage": "on", "description": "Test",
        })
        self.assertEqual(resp.status_code, 302)
        prog = Program.objects.get(title="Arabic Speech", madrasa=self.madrasa)
        self.assertIn(prog, self.cat.programs.all())
        self.assertTrue(prog.non_stage)
        self.assertEqual(prog.section, None)

    def test_add_girls_program_links_via_programs_for_girls(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("add_program"), {
            "title": "Recitation", "type": "individual", "section": "girls",
            "category_id": self.cat.id,
        })
        self.assertEqual(resp.status_code, 302)
        prog = Program.objects.get(title="Recitation", madrasa=self.madrasa)
        self.assertIn(prog, self.cat.programs_for_girls.all())
        self.assertNotIn(prog, self.cat.programs.all())

    def test_add_general_program_sets_section_and_teams(self):
        self.client.force_login(self.user)
        team = Team.objects.create(name="Alpha", madrasa=self.madrasa)
        resp = self.client.post(reverse("add_program"), {
            "title": "Pentathlon", "type": "general", "section": "boys",
            "category_id": "",
        })
        self.assertEqual(resp.status_code, 302)
        prog = Program.objects.get(title="Pentathlon", madrasa=self.madrasa)
        self.assertTrue(prog.is_general)
        self.assertEqual(prog.section, Program.SECTION_BOYS)
        self.assertEqual(list(prog.general_teams.all()), [team])

    def test_missing_category_for_individual_is_rejected(self):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("add_program"), {
            "title": "Solo", "type": "individual", "section": "boys",
            "category_id": "",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Program.objects.filter(title="Solo").exists())

    def test_duplicate_title_is_rejected(self):
        self.client.force_login(self.user)
        self.client.post(reverse("add_program"), {
            "title": "Debate", "type": "individual", "section": "boys",
            "category_id": self.cat.id,
        })
        resp = self.client.post(reverse("add_program"), {
            "title": "debate", "type": "individual", "section": "boys",
            "category_id": self.cat.id,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Program.objects.filter(title__iexact="Debate").count(), 1)


class JudgeModuleTests(TestCase):
    """Judge management, digital evaluation and auto-result publishing."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Judge Madrasa", fest_type="both")
        self.user = User.objects.create_superuser(
            email="judgeadmin@t.loc", password="xxxxxxxxxxxx", madrasa=self.madrasa
        )
        self.team = Team.objects.create(name="Alpha", madrasa=self.madrasa)
        self.cat = Category.objects.create(name="Senior", madrasa=self.madrasa)
        self.program = Program.objects.create(title="Speech", madrasa=self.madrasa)
        self.cat.programs.add(self.program)
        self.s1 = Student.objects.create(full_name="Ahmed", gender="male", code_number=1, team=self.team, category=self.cat)
        self.s2 = Student.objects.create(full_name="Bilal", gender="male", code_number=2, team=self.team, category=self.cat)
        self.program.participants.add(self.s1, self.s2)
        self.client.force_login(self.user)

    def _add_judge(self, **extra):
        post = {"name": "Judge Ahmad", "expertise": "Speech", "programs": [self.program.id], "is_active": "on"}
        post.update(extra)
        return self.client.post(reverse("judges"), post, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_judge_add_ajax(self):
        r = self._add_judge()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        judge = Judge.objects.get(name="Judge Ahmad")
        self.assertEqual(judge.madrasa, self.madrasa)
        self.assertEqual(list(judge.programs.all()), [self.program])

    def test_judge_add_requires_name(self):
        r = self.client.post(reverse("judges"), {"name": ""}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 400)
        self.assertIn("required", r.json()["error"].lower())

    def test_judges_page_lists(self):
        self._add_judge()
        r = self.client.get(reverse("judges"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Judge Ahmad")

    def test_judge_edit_ajax(self):
        judge = Judge.objects.create(madrasa=self.madrasa, name="Old")
        r = self.client.post(
            reverse("edit_judge", args=[judge.id]),
            {"name": "New Name", "expertise": "Recitation", "is_active": "off"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        judge.refresh_from_db()
        self.assertEqual(judge.name, "New Name")
        self.assertFalse(judge.is_active)

    def test_judge_delete_ajax(self):
        judge = Judge.objects.create(madrasa=self.madrasa, name="Temp")
        r = self.client.post(reverse("delete_judge", args=[judge.id]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertFalse(Judge.objects.filter(id=judge.id).exists())

    def test_judge_scoped_to_madrasa(self):
        other = Madrasa.objects.create(name="Other", fest_type="both")
        judge = Judge.objects.create(madrasa=other, name="Other Judge")
        r = self.client.post(reverse("delete_judge", args=[judge.id]))
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Judge.objects.filter(id=judge.id).exists())

    def test_save_criteria_ajax(self):
        r = self.client.post(
            reverse("save_program_criteria", args=[self.program.id]),
            {"criterion_name": ["Content", "Pronunciation"], "criterion_max": ["25", "20"]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        crits = list(self.program.evaluation_criteria.order_by("id"))
        self.assertEqual(len(crits), 2)
        self.assertEqual(crits[0].name, "Content")
        self.assertEqual(crits[0].max_marks, 25)

    def test_judge_login_portal(self):
        judge_user = User.objects.create_user(email="judge@t.loc", password="secret123", madrasa=None)
        judge = Judge.objects.create(madrasa=self.madrasa, name="Linked", user=judge_user)
        judge.programs.add(self.program)
        self.client.force_login(judge_user)
        r = self.client.get(reverse("judge_portal"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Speech")

    def test_save_evaluation_and_rankings(self):
        judge = Judge.objects.create(madrasa=self.madrasa, name="Ahmad")
        judge.programs.add(self.program)
        c1 = EvaluationCriterion.objects.create(program=self.program, name="Content", max_marks=25)
        url = reverse("judge_save_evaluation", args=[judge.id, self.program.id])
        r = self.client.post(url, {
            "contestant_kind": "student", "contestant_id": self.s1.id,
            f"score_{c1.id}": "20",
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["total"], 20)

        self.client.post(url, {
            "contestant_kind": "student", "contestant_id": self.s2.id,
            f"score_{c1.id}": "10",
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        ranked = Evaluation.rankings(self.program, self.madrasa)
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["student"], self.s1)
        self.assertEqual(ranked[0]["avg"], 20)

    def test_evaluation_upsert_overwrites(self):
        judge = Judge.objects.create(madrasa=self.madrasa, name="Ahmad")
        judge.programs.add(self.program)
        c1 = EvaluationCriterion.objects.create(program=self.program, name="Content", max_marks=25)
        url = reverse("judge_save_evaluation", args=[judge.id, self.program.id])
        for score in ("10", "18"):
            self.client.post(url, {
                "contestant_kind": "student", "contestant_id": self.s1.id,
                f"score_{c1.id}": score,
            }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(Evaluation.objects.filter(judge=judge, student=self.s1).count(), 1)
        self.assertEqual(Evaluation.objects.get(judge=judge, student=self.s1).total_marks, 18)

    def test_rankings_average_across_judges(self):
        j1 = Judge.objects.create(madrasa=self.madrasa, name="J1")
        j2 = Judge.objects.create(madrasa=self.madrasa, name="J2")
        for j in (j1, j2):
            j.programs.add(self.program)
        c1 = EvaluationCriterion.objects.create(program=self.program, name="Content", max_marks=25)
        url1 = reverse("judge_save_evaluation", args=[j1.id, self.program.id])
        url2 = reverse("judge_save_evaluation", args=[j2.id, self.program.id])
        self.client.post(url1, {"contestant_kind": "student", "contestant_id": self.s1.id, f"score_{c1.id}": "20"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.client.post(url2, {"contestant_kind": "student", "contestant_id": self.s1.id, f"score_{c1.id}": "10"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        ranked = Evaluation.rankings(self.program, self.madrasa)
        self.assertEqual(ranked[0]["avg"], 15)
        self.assertEqual(ranked[0]["evaluations_count"], 2)

    def test_evaluation_requires_assignment(self):
        judge = Judge.objects.create(madrasa=self.madrasa, name="J")
        judge.programs.add(self.program)
        juser = User.objects.create_user(email="j@t.loc", password="x", madrasa=None)
        judge.user = juser
        judge.save()
        self.client.force_login(juser)
        prog2 = Program.objects.create(title="Other", madrasa=self.madrasa)
        r = self.client.get(reverse("judge_program_evaluation", args=[judge.id, prog2.id]))
        self.assertEqual(r.status_code, 404)

    def test_publish_rankings_creates_prizes(self):
        j1 = Judge.objects.create(madrasa=self.madrasa, name="J1")
        j1.programs.add(self.program)
        c1 = EvaluationCriterion.objects.create(program=self.program, name="C", max_marks=100)
        url = reverse("judge_save_evaluation", args=[j1.id, self.program.id])
        self.client.post(url, {"contestant_kind": "student", "contestant_id": self.s1.id, f"score_{c1.id}": "80"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.client.post(url, {"contestant_kind": "student", "contestant_id": self.s2.id, f"score_{c1.id}": "70"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        r = self.client.post(reverse("judge_publish_rankings", args=[self.program.id]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Prize.objects.filter(program=self.program).count(), 2)
        self.assertEqual(Prize.objects.get(student=self.s1).position.name, "first")
        self.assertEqual(Prize.objects.get(student=self.s2).position.name, "second")

    def test_rankings_page_renders(self):
        judge = Judge.objects.create(madrasa=self.madrasa, name="J")
        judge.programs.add(self.program)
        c1 = EvaluationCriterion.objects.create(program=self.program, name="C", max_marks=100)
        self.client.post(
            reverse("judge_save_evaluation", args=[judge.id, self.program.id]),
            {"contestant_kind": "student", "contestant_id": self.s1.id, f"score_{c1.id}": "50"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        r = self.client.get(reverse("judge_program_rankings", args=[self.program.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Ahmed")

    def tearDown(self):
        self.client.logout()

    def test_judge_cannot_access_management(self):
        """A linked judge login gets 404 on admin judge CRUD (portal-only)."""
        judge_user = User.objects.create_user(email="jmg@t.loc", password="secret123", madrasa=None)
        judge = Judge.objects.create(madrasa=self.madrasa, name="Mgmt", user=judge_user)
        judge.programs.add(self.program)
        self.client.force_login(judge_user)
        self.assertEqual(self.client.get(reverse("judges")).status_code, 404)
        self.assertEqual(self.client.post(reverse("delete_judge", args=[judge.id])).status_code, 404)


class JudgeCodeAutoFillTests(TestCase):
    """Judge codes auto-generate per madrasa from 1000; student codes stay
    user-provided (no auto-fill)."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Judge Code Madrasa")
        self.user = User.objects.create_user(
            email="judgecode@t.loc",
            phone_number="9000000002",
            madrasa=self.madrasa,
            password="secret123",
        )
        self.url = reverse("judges")
        self.client.force_login(self.user)

    def _add(self, code=None, name="New Judge", ajax=True):
        data = {"name": name}
        if code is not None:
            data["code"] = code
        kwargs = {}
        if ajax:
            kwargs["HTTP_X_REQUESTED_WITH"] = "XMLHttpRequest"
        return self.client.post(self.url, data, **kwargs)

    def test_next_code_helper_starts_at_1000(self):
        self.assertEqual(views._next_judge_code(self.madrasa), "1000")
        self.assertEqual(views._next_judge_code(None), "1000")

    def test_next_code_helper_skips_used_and_ignores_non_numeric(self):
        Judge.objects.create(madrasa=self.madrasa, name="A", code="1000")
        Judge.objects.create(madrasa=self.madrasa, name="B", code="J01")
        Judge.objects.create(madrasa=self.madrasa, name="C", code=None)
        self.assertEqual(views._next_judge_code(self.madrasa), "1001")

    def test_blank_code_auto_assigned_from_1000(self):
        resp = self._add(code=None)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        judge = Judge.objects.get(name="New Judge")
        self.assertEqual(judge.code, "1000")
        # The assigned code is surfaced in the toast (the form no longer
        # shows a code field).
        self.assertIn("1000", data["message"])

    def test_next_code_advances_for_consecutive_adds(self):
        self._add(code=None, name="First")
        resp = self._add(code=None, name="Second")
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(Judge.objects.get(name="Second").code, "1001")

    def test_edit_without_code_keeps_existing_code(self):
        """The form no longer posts a code — editing must not wipe the
        backend-assigned code."""
        j = Judge.objects.create(madrasa=self.madrasa, name="Keep", code="1000")
        resp = self.client.post(
            f"/program/judges/{j.id}/edit/",
            {"name": "Renamed", "expertise": "Hifz"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        j.refresh_from_db()
        self.assertEqual(j.name, "Renamed")
        self.assertEqual(j.code, "1000")

    def test_explicit_code_is_respected(self):
        resp = self._add(code="J01")
        self.assertTrue(resp.json()["ok"])
        self.assertEqual(Judge.objects.get(name="New Judge").code, "J01")

    def test_duplicate_explicit_code_rejected(self):
        Judge.objects.create(madrasa=self.madrasa, name="Taken", code="1000")
        resp = self._add(code="1000")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("already assigned", resp.json()["error"])
        self.assertFalse(Judge.objects.filter(name="New Judge").exists())

    def test_non_ajax_post_redirects_and_assigns(self):
        resp = self._add(code=None, ajax=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Judge.objects.get(name="New Judge").code, "1000")


class CategoryDetailDispatchTests(TestCase):
    """The add-student / add-program modals on category detail are submitted
    via AJAX FormData, which drops submit-button name/values — so the forms
    must carry their dispatch keys (student_form / program_form) as hidden
    inputs for CategoryDetailView.post to route them."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Dispatch Madrasa")
        self.user = User.objects.create_user(
            email="dispatch@t.loc",
            phone_number="9000000003",
            madrasa=self.madrasa,
            password="secret123",
        )
        self.team = Team.objects.create(name="Team D", madrasa=self.madrasa)
        self.category = Category.objects.create(name="Hifz", madrasa=self.madrasa)
        self.url = reverse("category_detail", kwargs={"pk": self.category.pk}) + f"?team={self.team.pk}"
        self.client.force_login(self.user)

    def test_modals_embed_hidden_dispatch_inputs(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('name="student_form"', html)
        self.assertIn('name="program_form"', html)

    def test_post_with_hidden_dispatch_key_adds_student(self):
        """Browser-shaped AJAX payload: the dispatch key comes from the
        hidden input, not from the (dropped) submit button."""
        resp = self.client.post(
            self.url,
            {"student_form": "1", "full_name": "AJAX Kid", "gender": "male"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertTrue(Student.objects.filter(full_name="AJAX Kid").exists())

    def test_post_with_hidden_dispatch_key_adds_program(self):
        resp = self.client.post(
            self.url,
            {
                "program_form": "1",
                "title": "AJAX Program",
                "description": "",
                "non_stage": "False",
                "is_group": "False",
                "is_general": "False",
                "gender": "male",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        self.assertTrue(Program.objects.filter(title="AJAX Program").exists())

    def test_missing_dispatch_key_falls_back_to_page_render(self):
        """No dispatch key at all → the view re-renders the page (no crash)."""
        resp = self.client.post(
            self.url, {"full_name": "X"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)


class AjaxDoubleSubmitGuardTests(SimpleTestCase):
    """Regression: every ``data-ajax-form`` submission was POSTed twice.

    header.html ships its own AJAX submit interceptor (capture phase) AND
    staticfiles/program/js/_ajax_forms.js registered a second one (bubble
    phase). Both fired a fetch for the same submit event, so adding a student
    or program on the category detail page created it twice. The JS listener
    must defer to any interceptor that already claimed the event
    (``e.defaultPrevented``) — header.html's ``MeeladAjax.submit`` is the
    single owner (it is a superset: modal close, collapse, undo, redirect
    soft-refresh), and _ajax_forms.js is only loaded together with header.
    """

    def test_ajax_forms_listener_defers_to_already_handled_submits(self):
        js = (
            Path(settings.BASE_DIR) / "staticfiles" / "program" / "js" / "_ajax_forms.js"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "if (e.defaultPrevented) return;", js,
            "_ajax_forms.js must skip submits already handled by header.html's "
            "AJAX interceptor — otherwise every data-ajax-form form POSTs twice "
            "and students/programs are created in duplicates.",
        )

    def test_header_ajax_interceptor_is_the_single_owner(self):
        """header.html must own data-ajax-form submits (capture phase) and the
        confirm interceptor must stop propagation so no second handler runs."""
        header = (
            Path(settings.BASE_DIR) / "templates" / "header.html"
        ).read_text(encoding="utf-8")
        self.assertIn("window.MeeladAjax.submit(form, e.submitter)", header)
        # The confirm interceptor stops other listeners before its async flow
        self.assertIn("e.stopImmediatePropagation()", header)


class CategoryDetailAjaxRefreshTests(TestCase):
    """Regression: on category detail an added program never showed up, and
    assigning programs to a student left the modal stuck open.

    Both came from the same two gaps:
      * the boys/girls PROGRAMS lists were not ``[data-ajax-list]`` containers,
        so the soft refresh after a submit replaced only the student lists and
        the newly added program never rendered;
      * the student modals live INSIDE the refreshed student lists, and
        ``openPanel()`` teleports an open modal to ``<body>``. After the swap
        the teleported copy lingered as a duplicate id, so
        ``getElementById(id)`` returned the fresh (closed) copy and the visible
        modal could never be closed.
    """

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Refresh Madrasa")
        self.user = User.objects.create_user(
            email="refresh@t.loc",
            phone_number="9000000004",
            madrasa=self.madrasa,
            password="secret123",
        )
        self.team = Team.objects.create(name="Team R", madrasa=self.madrasa)
        self.category = Category.objects.create(name="Hifz", madrasa=self.madrasa)
        self.program = Program.objects.create(
            title="Refresh Program", madrasa=self.madrasa
        )
        self.category.programs.add(self.program)
        self.url = (
            reverse("category_detail", kwargs={"pk": self.category.pk})
            + f"?team={self.team.pk}"
        )
        self.client.force_login(self.user)

    def test_program_lists_are_ajax_refresh_targets(self):
        """Every program list must be a refresh target with a unique key, so a
        soft refresh actually re-renders the added/edited program."""
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        for key in (
            'data-ajax-list="boys-stage-programs"',
            'data-ajax-list="boys-nonstage-programs"',
            'data-ajax-list="girls-stage-programs"',
            'data-ajax-list="girls-nonstage-programs"',
        ):
            self.assertIn(
                key, html,
                f"{key} is missing — the soft refresh would skip the program "
                "lists and the added program would stay invisible.",
            )
        # Keys must be unique or the refresh matcher would swap the wrong list.
        self.assertEqual(html.count('data-ajax-list="boys-stage-programs"'), 1)
        self.assertEqual(html.count('data-ajax-list="girls-stage-programs"'), 1)
        # Program rows carry data-program-id so the refresh can scroll to and
        # highlight the freshly added program.
        self.assertIn(f'data-program-id="{self.program.pk}"', html)

    def test_student_lists_keep_their_refresh_keys(self):
        """The student lists (which hold the student modals) stay refresh
        targets keyed by section."""
        html = self.client.get(self.url).content.decode()
        self.assertIn('data-ajax-list="boys"', html)
        self.assertIn('data-ajax-list="girls"', html)

    def test_header_drops_orphaned_teleported_modals_after_refresh(self):
        """header.html must remove the teleported copy of an open modal whose
        id now exists inside a refreshed list — otherwise the visible modal can
        never be closed (duplicate id)."""
        header = (
            Path(settings.BASE_DIR) / "templates" / "header.html"
        ).read_text(encoding="utf-8")
        self.assertIn("const refreshedIds = [];", header)
        self.assertIn("node.classList.contains('modal-shell')", header)
        self.assertIn("refreshedIds.indexOf(node.id) !== -1", header)
        self.assertIn("node.remove();", header)
        # highlight() must search the whole page: the new program row lives in
        # the programs list, not in the first [data-ajax-list] (student list).
        self.assertIn("highlight(document, data.program", header)


class TemplateCommentGuardTests(SimpleTestCase):
    """Regression: Django's ``{# ... #}`` comments cannot span multiple lines.

    A multi-line ``{# ... #}`` block is not parsed as a comment at all — the
    raw text (including the trailing ``#}``) renders on the page. This bit the
    shared ``_head_meta.html`` partial, printing its doc comment on the public
    student result portal and program register-link pages. Any multi-line
    comment must use ``{% comment %} ... {% endcomment %}`` instead.
    """

    def test_no_multiline_hash_comments_in_templates(self):
        offenders = []
        for path in (Path(settings.BASE_DIR) / "templates").rglob("*.html"):
            src = path.read_text(encoding="utf-8")
            for m in re.finditer(r"\{#(?!#)", src):
                close = src.find("#}", m.start())
                if close == -1:
                    continue
                if "\n" in src[m.start():close]:
                    offenders.append(f"{path.name}:{src[:m.start()].count(chr(10)) + 1}")
        self.assertEqual(
            offenders, [],
            "Multi-line {# ... #} blocks render as literal page text. Use "
            "{% comment %} ... {% endcomment %} for comments spanning lines: "
            f"{offenders}",
        )


class ResultPageHeaderStatsTests(TestCase):
    """The results page header shows published / unpublished result counts.

    ``category_program_list`` computes them over exactly the programs listed in
    the tables below (both sections combined, de-duplicated) and they follow the
    category filter, so the numbers always describe what is on screen.
    """

    def setUp(self):
        self.madrasa = Madrasa.objects.create(
            name="Stats Madrasa",
            meelad_fest_name="Meelad Fest 2026",
            sadr="Test Sadr",
        )
        self.user = User.objects.create_user(
            email="stats@test.com",
            phone_number="9876500000",
            madrasa=self.madrasa,
            password="testpassword",
        )
        self.client.force_login(self.user)

        self.category = Category.objects.create(name="Sub Juniors", madrasa=self.madrasa)
        self.other_category = Category.objects.create(name="Seniors", madrasa=self.madrasa)

        self.team = Team.objects.create(name="Al Hilal", madrasa=self.madrasa)
        self.student = Student.objects.create(
            full_name="Ahmad", gender="male", code_number=101,
            category=self.category, team=self.team,
        )
        self.position = Position.objects.create(name="first", mark=5.0)

        # One category holds three states: published / entered-not-published /
        # nothing entered yet.
        self.published = self._program(
            "Published Qira'at", self.category, published=True, with_prize=True)
        self.awaiting = self._program(
            "Awaiting Speech", self.category, published=False, with_prize=True)
        self.empty = self._program(
            "Empty Essay", self.category, published=False, with_prize=False)
        # A second category, used by the filter test.
        self.other_published = self._program(
            "Seniors Debate", self.other_category, published=True, with_prize=True)

    def _program(self, title, category, published, with_prize):
        program = Program.objects.create(title=title, is_result_published=published)
        category.programs.add(program)
        if with_prize:
            Prize.objects.create(student=self.student, program=program, position=self.position)
        return program

    def test_header_stats_are_computed_for_all_listed_programs(self):
        resp = self.client.get(reverse('results'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['result_total_programs'], 4)
        self.assertEqual(resp.context['result_published'], 2)
        self.assertEqual(resp.context['result_unpublished'], 2)
        self.assertEqual(resp.context['result_awaiting'], 1)
        self.assertEqual(resp.context['result_not_entered'], 1)

    def test_header_stats_follow_the_category_filter(self):
        resp = self.client.get(reverse('results'), {'category': self.category.id})
        self.assertEqual(resp.context['result_total_programs'], 3)
        self.assertEqual(resp.context['result_published'], 1)
        self.assertEqual(resp.context['result_unpublished'], 2)
        self.assertEqual(resp.context['result_awaiting'], 1)
        self.assertEqual(resp.context['result_not_entered'], 1)

    def test_shared_program_is_counted_once(self):
        """A program linked to both the boys and the girls M2M sets is listed by
        two table sections — the header must still count it a single time."""
        shared = Program.objects.create(title="Shared Tilawat", is_result_published=True)
        self.category.programs.add(shared)
        self.category.programs_for_girls.add(shared)

        resp = self.client.get(reverse('results'), {'category': self.category.id})
        self.assertEqual(resp.context['result_total_programs'], 4)  # 3 + 1, not 5
        self.assertEqual(resp.context['result_published'], 2)

    def test_single_section_fest_only_counts_the_active_section(self):
        madrasa = Madrasa.objects.create(
            name="Boys Madrasa", sadr="Test Sadr", fest_type=Madrasa.FEST_TYPE_BOYS)
        user = User.objects.create_user(
            email="boys@test.com", phone_number="9876500001",
            madrasa=madrasa, password="testpassword")
        category = Category.objects.create(name="Juniors", madrasa=madrasa)

        boys_program = Program.objects.create(title="Boys Only", is_result_published=True)
        category.programs.add(boys_program)
        girls_program = Program.objects.create(title="Girls Only")
        category.programs_for_girls.add(girls_program)

        team = Team.objects.create(name="Team B", madrasa=madrasa)
        student = Student.objects.create(
            full_name="Boy", gender="male", code_number=1,
            category=category, team=team)
        position = Position.objects.create(name="first", mark=5.0, madrasa=madrasa)
        Prize.objects.create(student=student, program=boys_program, position=position)

        self.client.force_login(user)
        resp = self.client.get(reverse('results'))
        self.assertEqual(resp.context['result_total_programs'], 1)
        self.assertEqual(resp.context['result_published'], 1)
        self.assertEqual(resp.context['result_awaiting'], 0)
        self.assertEqual(resp.context['result_not_entered'], 0)

    def test_stats_strip_is_a_live_refresh_target(self):
        html = self.client.get(reverse('results')).content.decode()
        self.assertIn('data-live-section="result-stats"', html)
        for label in (
            'Total Programs', 'Published', 'Unpublished',
            'Awaiting Publish', 'No Results Yet', 'Fest',
        ):
            self.assertIn(label, html)
        # The result tables keep their own live-refresh targets.
        self.assertIn('data-live-section="boys"', html)
        self.assertIn('data-live-section="girls"', html)

    def test_header_uses_the_shared_gradient_layout(self):
        html = self.client.get(reverse('results')).content.decode()
        self.assertIn('bg-gradient-to-r from-indigo-600 to-purple-600', html)
        self.assertIn('Program Results', html)
        self.assertIn('Download All Results (PDF)', html)


class GlobalSearchEndpointTests(TestCase):
    """The /program/search/ JSON endpoint powering the Ctrl+K command palette.

    It must require login, ignore very short queries, find each entity type by
    name/code, and never leak another madrasa's records.
    """

    def setUp(self):
        self.madrasa = Madrasa.objects.create(
            name="Search Madrasa", meelad_fest_name="Meelad Fest 2026", sadr="Test Sadr")
        self.user = User.objects.create_user(
            email="search@test.com", phone_number="9876500010",
            madrasa=self.madrasa, password="testpassword")

        self.category = Category.objects.create(name="Juniors", madrasa=self.madrasa)
        self.team = Team.objects.create(name="Al Hilal", madrasa=self.madrasa)
        self.student = Student.objects.create(
            full_name="Muhammed Ali", gender="male", code_number=7,
            category=self.category, team=self.team)
        self.program = Program.objects.create(title="Qirat Competition")
        self.category.programs.add(self.program)
        self.venue = Venue.objects.create(name="Main Stage", madrasa=self.madrasa)
        self.judge = Judge.objects.create(madrasa=self.madrasa, name="Ustad Abdul")

        # A second madrasa with its own records — none of these may appear.
        self.other = Madrasa.objects.create(name="Other Madrasa", sadr="Other Sadr")
        self.other_user = User.objects.create_user(
            email="other@test.com", phone_number="9876500011",
            madrasa=self.other, password="testpassword")
        self.other_team = Team.objects.create(name="Other Team", madrasa=self.other)
        self.other_student = Student.objects.create(
            full_name="Muhammed Hidden", gender="male", code_number=99,
            category=Category.objects.create(name="Hidden Cat", madrasa=self.other),
            team=self.other_team)
        Venue.objects.create(name="Hidden Venue", madrasa=self.other)
        Judge.objects.create(madrasa=self.other, name="Hidden Judge")
        hidden_program = Program.objects.create(title="Hidden Program")
        Category.objects.filter(madrasa=self.other).first().programs.add(hidden_program)

        self.url = reverse("global_search")

    def _search(self, q):
        return self.client.get(self.url, {"q": q})

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get(self.url, {"q": "qirat"})
        self.assertEqual(resp.status_code, 302)

    def test_short_queries_return_empty_payload(self):
        self.client.force_login(self.user)
        for q in ("", "a", "  x "):
            data = self._search(q).json()
            self.assertEqual(data["total"], 0)
            self.assertEqual(data["students"], [])

    def test_finds_each_entity_type(self):
        self.client.force_login(self.user)
        data = self._search("qirat").json()
        self.assertEqual([p["title"] for p in data["programs"]], ["Qirat Competition"])
        # Program links go into the results page filtered on its category.
        self.assertIn(f"?category={self.category.id}", data["programs"][0]["url"])

        data = self._search("muhammed").json()
        self.assertEqual(len(data["students"]), 1)
        self.assertEqual(data["students"][0]["title"], "Muhammed Ali")
        self.assertIn(str(self.student.id), data["students"][0]["url"])

        data = self._search("main stage").json()
        self.assertEqual([v["title"] for v in data["venues"]], ["Main Stage"])
        self.assertIn(str(self.venue.id), data["venues"][0]["url"])

        data = self._search("ustad").json()
        self.assertEqual([j["title"] for j in data["judges"]], ["Ustad Abdul"])

    def test_code_number_lookup(self):
        self.client.force_login(self.user)
        data = self._search("7").json()
        self.assertEqual(len(data["students"]), 1)
        self.assertEqual(data["students"][0]["title"], "Muhammed Ali")

    def test_no_cross_madrasa_leakage(self):
        """Both sides: our search never shows other madrasa records, and their
        user never sees ours."""
        self.client.force_login(self.user)
        data = self._search("hidden").json()
        self.assertEqual(data["total"], 0)

        self.client.force_login(self.other_user)
        data = self._search("muhammed").json()
        self.assertEqual([s["title"] for s in data["students"]], ["Muhammed Hidden"])
        data = self._search("main stage").json()
        self.assertEqual(data["total"], 0)


class HomeCommandCenterStatsTests(TestCase):
    """The home page's Fest Command Center tiles count programs per result
    state (published / awaiting publish / nothing entered), unscheduled
    programs, and active judges — scoped to the caller's madrasa section."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(
            name="Home Madrasa", meelad_fest_name="Meelad Fest 2026", sadr="Test Sadr")
        self.user = User.objects.create_user(
            email="home@test.com", phone_number="9876500012",
            madrasa=self.madrasa, password="testpassword")
        # The home page is behind the subscription gate.
        Subscription.objects.create(
            institution=self.madrasa,
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=30), active=True)
        self.client.force_login(self.user)

        self.category = Category.objects.create(name="Seniors", madrasa=self.madrasa)
        self.team = Team.objects.create(name="Al Hilal", madrasa=self.madrasa)
        self.student = Student.objects.create(
            full_name="Zayd", gender="male", code_number=5,
            category=self.category, team=self.team)
        self.position = Position.objects.create(name="first", mark=5.0)
        self.day = FestDay.objects.create(
            madrasa=self.madrasa, name="Day 1",
            date=timezone.now().date() + timedelta(days=1))
        self.venue = Venue.objects.create(name="Stage 1", madrasa=self.madrasa)

    def _program(self, title, published=False, with_prize=False, scheduled=False):
        program = Program.objects.create(title=title, is_result_published=published)
        self.category.programs.add(program)
        if with_prize:
            Prize.objects.create(student=self.student, program=program, position=self.position)
        if scheduled:
            ScheduleEntry.objects.create(
                program=program, fest_day=self.day,
                venue=self.venue, start_time="09:00", duration_minutes=10)
        return program

    def _home_context(self):
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        return resp.context

    def test_result_state_counts(self):
        self._program("Pub A", published=True, with_prize=True)
        self._program("Pub B", published=True, with_prize=True)
        self._program("Awaiting", published=False, with_prize=True)
        self._program("Empty 1", published=False)
        self._program("Empty 2", published=False)

        ctx = self._home_context()
        self.assertEqual(ctx["cc_total_programs"], 5)
        self.assertEqual(ctx["cc_published"], 2)
        self.assertEqual(ctx["cc_awaiting"], 1)
        self.assertEqual(ctx["cc_not_entered"], 2)

    def test_unscheduled_and_infra_counts(self):
        self._program("Scheduled One", scheduled=True)
        self._program("Floating One")

        ctx = self._home_context()
        self.assertEqual(ctx["cc_unscheduled"], 1)
        self.assertEqual(ctx["cc_venues"], 1)
        self.assertEqual(ctx["cc_days"], 1)
        self.assertEqual(ctx["cc_judges"], 0)
        Judge.objects.create(madrasa=self.madrasa, name="Active Judge", is_active=True)
        Judge.objects.create(madrasa=self.madrasa, name="Inactive Judge", is_active=False)
        ctx = self._home_context()
        self.assertEqual(ctx["cc_judges"], 1)

    def test_counts_exclude_other_madrasa(self):
        other = Madrasa.objects.create(name="Other Home", sadr="Other Sadr")
        other_cat = Category.objects.create(name="Other Cat", madrasa=other)
        other_program = Program.objects.create(title="Other Program", is_result_published=True)
        other_cat.programs.add(other_program)
        Venue.objects.create(name="Other Venue", madrasa=other)

        ctx = self._home_context()
        self.assertEqual(ctx["cc_total_programs"], 0)
        # The caller's own setUp venue ("Stage 1") is counted; the other
        # madrasa's "Other Venue" is not.
        self.assertEqual(ctx["cc_venues"], 1)

    def test_home_does_not_repeat_a_metric(self):
        """Home renders every metric once: the four Quick Stats tiles count
        teams/students/programs/categories, and the Result-readiness strip only
        carries counts those tiles do not show — so the programs count can
        never appear twice (the removed Command Center repeated it)."""
        self._program("Pub A", published=True, with_prize=True)
        self._program("Awaiting B", with_prize=True)
        html = self.client.get(reverse("home")).content.decode()
        self.assertEqual(html.count("data-count-to="), 4)
        self.assertEqual(html.count('data-readiness="'), 5)
        self.assertIn("Result readiness", html)
        self.assertNotIn("Command Center", html)

    def test_quick_access_band_repeats_no_quick_stats_destination(self):
        html = self.client.get(reverse("home")).content.decode()
        band = html.split("Quick Access", 1)[1].split("Team Standings", 1)[0]
        for href in (reverse("teams"), reverse("program_list"),
                     reverse("upload-students"), reverse("categories")):
            self.assertNotIn(
                f'href="{href}"', band,
                f"{href} is already a Quick Stats tile — Quick Access must not repeat it.")
        for href in (reverse("schedule_dashboard"), reverse("judges"),
                     reverse("results"), reverse("general_programs"),
                     reverse("venue_list"), reverse("statistics")):
            self.assertEqual(band.count(f'href="{href}"'), 1, href)
class ListingPaginationMarkupTests(TestCase):
    """Batch A pagination: programs, judges, students and results listings all
    expose the hooks the shared client-side pager needs to show 10 items per
    page (``static/program/js/_pager.js``).

    The pager resolves a ``data-pager`` container, reads its items from
    ``data-pager-items`` when they are not the container's direct children
    (table rows, list items, card grids), skips ``data-pager-ignore``
    placeholders such as the empty state, and ignores ``result-row-hidden``
    rows so the results find-box keeps cooperating with paging.
    """

    def setUp(self):
        self.madrasa = Madrasa.objects.create(
            name="Pager Madrasa", meelad_fest_name="Meelad Fest 2026",
            sadr="Test Sadr", fest_type=Madrasa.FEST_TYPE_BOTH)
        self.user = User.objects.create_user(
            email="pager@test.com", phone_number="9876500002",
            madrasa=self.madrasa, password="testpassword")
        Subscription.objects.create(
            institution=self.madrasa,
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=30), active=True)
        self.client.force_login(self.user)

        self.category = Category.objects.create(name="Seniors", madrasa=self.madrasa)
        self.team = Team.objects.create(name="Al Hilal", madrasa=self.madrasa)
        self.student = Student.objects.create(
            full_name="Zayd", gender="male", code_number=11,
            category=self.category, team=self.team)
        self.position = Position.objects.create(name="first", mark=5.0)

        # 12 published programs in one category — more than one page of 10.
        for index in range(12):
            program = Program.objects.create(
                title=f"Pager Program {index}", is_result_published=True)
            self.category.programs.add(program)
            Prize.objects.create(student=self.student, program=program,
                                 position=self.position)
        stage_program = Program.objects.create(title="Pager Stage Program")
        self.category.programs.add(stage_program)
        non_stage_program = Program.objects.create(
            title="Pager Non Stage Program", non_stage=True)
        self.category.programs.add(non_stage_program)
        Judge.objects.create(madrasa=self.madrasa, name="Pager Judge", is_active=True)

    def test_program_list_grids_are_pageable(self):
        """Boys stage + non-stage card grids are pager containers. The grid is
        the container and every program card a direct child, so 10 cards show
        per page without any extra selector."""
        html = self.client.get(reverse("program_list")).content.decode()
        self.assertEqual(html.count("data-pager>"), 2)
        self.assertIn("Pager Stage Program", html)
        self.assertIn("Pager Non Stage Program", html)

    def test_judges_grid_is_pageable(self):
        html = self.client.get(reverse("judges")).content.decode()
        self.assertIn("data-ajax-list data-pager", html)

    def test_results_sections_page_their_table_rows(self):
        """Result tables page by row: the section wrapper owns the pager and
        resolves rows through the row selector."""
        html = self.client.get(reverse("results")).content.decode()
        self.assertEqual(html.count('data-pager-items="tbody tr"'), 2)
        for section in ("boys", "girls"):
            self.assertIn(
                f'data-live-section="{section}" data-pager'
                ' data-pager-items="tbody tr"', html)

    def test_student_lists_page_their_list_items(self):
        url = (reverse("category_detail", kwargs={"pk": self.category.pk})
               + f"?team={self.team.pk}")
        html = self.client.get(url).content.decode()
        self.assertEqual(html.count('data-pager-items="ul > li"'), 2)

    def test_empty_state_placeholder_is_ignored_by_the_pager(self):
        empty = (Path(settings.BASE_DIR) / "templates" / "_empty_state.html")
        self.assertIn("data-pager-ignore", empty.read_text(encoding="utf-8"))

    def test_pager_engine_is_shipped_and_included_once(self):
        from django.contrib.staticfiles import finders
        base = (Path(settings.BASE_DIR) / "templates" / "program" / "base.html")
        self.assertEqual(base.read_text(encoding="utf-8").count("program/js/_pager.js"), 1)
        pager = finders.find("program/js/_pager.js")
        self.assertIsNotNone(
            pager, "the shared pager script is not discoverable by staticfiles")
        script = Path(pager).read_text(encoding="utf-8")
        for needle in ("PAGE_SIZE = 10", "data-pager-items", "data-pager-ignore",
                       "result-row-hidden", "MutationObserver", "MeeladPager"):
            self.assertIn(needle, script)


class ConsistentPageHeadersTests(TestCase):
    """Batch A header consistency: statistics and student_profile now use the
    same gradient band + stat-tile header as venues/programs/results/judges,
    with the duplicated metric blocks removed from both pages."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(
            name="Header Madrasa", meelad_fest_name="Meelad Fest 2026",
            sadr="Test Sadr", fest_type=Madrasa.FEST_TYPE_BOTH)
        self.user = User.objects.create_user(
            email="headers@test.com", phone_number="9876500003",
            madrasa=self.madrasa, password="testpassword")
        Subscription.objects.create(
            institution=self.madrasa,
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=30), active=True)
        self.client.force_login(self.user)
        self.category = Category.objects.create(name="Seniors", madrasa=self.madrasa)
        self.team = Team.objects.create(name="Al Hilal", madrasa=self.madrasa)
        self.student = Student.objects.create(
            full_name="Amir", gender="male", code_number=7,
            category=self.category, team=self.team)
        # The statistics band only renders the charts download button when the
        # fest has points; give Amir some so the band appears in its real state.
        self.student.total_point = 12.5
        self.student.save(update_fields=["total_point"])

    def test_statistics_page_uses_standard_header_band(self):
        html = self.client.get(reverse("statistics")).content.decode()
        self.assertIn("bg-gradient-to-r from-indigo-600 to-purple-600", html)
        self.assertIn("Meelad Fest 2026", html)
        # The charts download action lives in the band exactly once — the
        # duplicate floating header button was removed with the old header.
        self.assertEqual(html.count('id="download-all-charts"'), 1)

    def test_student_profile_uses_standard_header_band(self):
        html = self.client.get(
            reverse("student_profile", kwargs={"student_id": self.student.pk})
        ).content.decode()
        self.assertIn("bg-gradient-to-r from-indigo-600 to-purple-600", html)
        self.assertIn("Code 7", html)
        self.assertIn("Boys Section", html)
        # Four header tiles (incl. fest name) and no duplicated stats row below.
        self.assertIn("sm:grid-cols-4 divide-x", html)
        self.assertNotIn("sm:grid-cols-3 mb-6", html)

    def test_student_profile_scoping_unchanged(self):
        """The header refactor must not weaken madrasa scoping: another
        madrasa's student is still a 404."""
        other = Madrasa.objects.create(
            name="Other Header Madrasa", sadr="X",
            fest_type=Madrasa.FEST_TYPE_BOTH)
        other_team = Team.objects.create(name="Away", madrasa=other)
        stranger = Student.objects.create(
            full_name="Outsider", gender="male", code_number=9, team=other_team)
        response = self.client.get(
            reverse("student_profile", kwargs={"student_id": stranger.pk}))
        self.assertEqual(response.status_code, 404)


class BulkCertificatesPdfTests(TestCase):
    """Batch B: one-click bulk certificate generation.

    download_certificates_pdf merges one A4-landscape page per award into a
    single PDF: Top-3 winners (individual, group and general/team-wise) plus
    grade certificates, for the requesting user's madrasa only and only from
    published program results.
    """

    def setUp(self):
        self.madrasa = Madrasa.objects.create(
            name="Cert Fest Madrasa", meelad_fest_name="Meelad Fest 2026",
            sadr="Sadr", fest_type=Madrasa.FEST_TYPE_BOTH)
        self.user = User.objects.create_user(
            email="certs@test.com", phone_number="9876500008",
            madrasa=self.madrasa, password="testpassword")
        Subscription.objects.create(
            institution=self.madrasa,
            start_date=timezone.now() - timedelta(days=1),
            end_date=timezone.now() + timedelta(days=30), active=True)
        self.client.force_login(self.user)

        self.team = Team.objects.create(name="Al Hilal", madrasa=self.madrasa)
        self.category = Category.objects.create(name="Seniors", madrasa=self.madrasa)
        self.first = Position.objects.create(name="first", mark=5.0, madrasa=self.madrasa)
        self.second = Position.objects.create(name="second", mark=3.0, madrasa=self.madrasa)
        self.a_grade = Grade.objects.create(name="a_grade", mark=1.0, madrasa=self.madrasa)

        self.prog = Program.objects.create(
            title="Recitation", madrasa=self.madrasa, is_result_published=True)
        self.category.programs.add(self.prog)
        self.s1 = Student.objects.create(
            full_name="Cert Winner", gender="male", code_number=21,
            category=self.category, team=self.team)
        self.s2 = Student.objects.create(
            full_name="Cert Runner", gender="male", code_number=22,
            category=self.category, team=self.team)
        self.s3 = Student.objects.create(
            full_name="Cert Graded", gender="male", code_number=23,
            category=self.category, team=self.team)
        Prize.objects.create(student=self.s1, program=self.prog, position=self.first)
        Prize.objects.create(student=self.s2, program=self.prog, position=self.second)
        Prize.objects.create(student=self.s3, program=self.prog, grade=self.a_grade)

        self.url = reverse("download_certificates_pdf")

    def _pdf_pages(self, response):
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(response.content))
        return reader, [page.extract_text() or "" for page in reader.pages]

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertIn(resp.status_code, (302, 401))

    def test_valid_pdf_with_one_page_per_award(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/pdf")
        self.assertTrue(resp["Content-Disposition"].startswith("attachment"))
        self.assertTrue(resp.content.startswith(b"%PDF"))
        reader, texts = self._pdf_pages(resp)
        # 3 prizes -> 3 certificate pages.
        self.assertEqual(len(reader.pages), 3)

    def test_certificate_pages_carry_award_details(self):
        resp = self.client.get(self.url)
        _, texts = self._pdf_pages(resp)
        joined = "\n".join(texts)
        self.assertIn("Cert Winner", joined)
        self.assertIn("Cert Runner", joined)
        self.assertIn("Cert Graded", joined)
        self.assertIn("Recitation", joined)
        self.assertIn("First Prize", joined)
        self.assertIn("A Grade", joined)
        self.assertIn("Meelad Fest 2026", joined)

    def test_unpublished_results_are_excluded(self):
        prog2 = Program.objects.create(
            title="Hidden Program", madrasa=self.madrasa,
            is_result_published=False)
        self.category.programs.add(prog2)
        Prize.objects.create(
            student=self.s1, program=prog2, position=self.first)
        resp = self.client.get(self.url)
        _, texts = self._pdf_pages(resp)
        joined = "\n".join(texts)
        self.assertNotIn("Hidden Program", joined)
        reader, _ = self._pdf_pages(resp)
        self.assertEqual(len(reader.pages), 3)  # still only the published ones

    def test_other_madrasa_results_are_excluded(self):
        other = Madrasa.objects.create(
            name="Away Madrasa", sadr="X", fest_type=Madrasa.FEST_TYPE_BOTH)
        other_team = Team.objects.create(name="Away Team", madrasa=other)
        other_cat = Category.objects.create(name="Away Cat", madrasa=other)
        other_prog = Program.objects.create(
            title="Foreign Program", madrasa=other, is_result_published=True)
        other_cat.programs.add(other_prog)
        stranger = Student.objects.create(
            full_name="Stranger Winner", gender="male", code_number=31,
            category=other_cat, team=other_team)
        other_pos = Position.objects.create(name="first", mark=5.0, madrasa=other)
        Prize.objects.create(
            student=stranger, program=other_prog, position=other_pos)

        resp = self.client.get(self.url)
        _, texts = self._pdf_pages(resp)
        joined = "\n".join(texts)
        self.assertNotIn("Foreign Program", joined)
        self.assertNotIn("Stranger Winner", joined)

    def test_group_certificate_lists_participants(self):
        group_prog = Program.objects.create(
            title="Group Mappilappattu", madrasa=self.madrasa, is_group=True,
            is_result_published=True)
        self.category.programs.add(group_prog)
        group_pos = GroupPosition.objects.create(
            name="first", mark=10.0, madrasa=self.madrasa)
        group_prize = Prize.objects.create(
            team=self.team, program=group_prog,
            group_program_position=group_pos)
        group_prize.participants.add(self.s1, self.s2)

        resp = self.client.get(self.url)
        _, texts = self._pdf_pages(resp)
        joined = "\n".join(texts)
        self.assertIn("Group Mappilappattu", joined)
        self.assertIn("Cert Winner & Cert Runner", joined)
        self.assertIn("Al Hilal", joined)

    def test_no_published_results_gives_friendly_page(self):
        Prize.objects.all().delete()
        self.prog.is_result_published = False
        self.prog.save()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content.startswith(b"%PDF"))
        _, texts = self._pdf_pages(resp)
        self.assertIn("No published results yet", "\n".join(texts))

    def test_results_page_shows_certificate_button(self):
        html = self.client.get(reverse("results")).content.decode()
        self.assertIn('href="%s"' % self.url, html)
        self.assertIn("Certificates (PDF)", html)

