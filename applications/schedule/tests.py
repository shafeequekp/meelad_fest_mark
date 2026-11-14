"""Tests for the fest program-scheduling board.

Covers the conflict-detection helpers in ``services.py`` plus the board
views: fest-day CRUD, schedule-entry CRUD and the live conflict-check API.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path

from django.contrib.messages import get_messages
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from applications.accounts.models import Madrasa, User
from applications.program.models import Category, Program, Student, Venue
from applications.scoreboard.models import Team

from .models import FestDay, ScheduleEntry
from .services import (
    check_schedule_conflicts,
    compute_day_conflicts,
    interval_overlaps,
    program_units,
)


class ScheduleDataMixin:
    """Shared fixtures: a madrasa, coordinator, students, team and venues."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name='Schedule Madrasa')
        self.user = User.objects.create_user(
            email='coordinator@test.com',
            phone_number='9876543210',
            madrasa=self.madrasa,
            password='testpass123',
        )
        self.student_1 = Student.objects.create(full_name='Ahmad')
        self.student_2 = Student.objects.create(full_name='Zayd')
        self.team = Team.objects.create(name='Al Hilal', madrasa=self.madrasa)
        self.venue_main = Venue.objects.create(name='Main Hall', madrasa=self.madrasa)
        self.venue_annex = Venue.objects.create(name='Annex Hall', madrasa=self.madrasa)
        self.day = FestDay.objects.create(
            madrasa=self.madrasa, name='Day 1', date=date(2026, 9, 10),
        )

    def make_program(self, title, participants=None, teams=None,
                     is_group=False, is_general=False):
        program = Program.objects.create(
            title=title,
            madrasa=self.madrasa,
            is_group=is_group,
            is_general=is_general,
        )
        for student in participants or []:
            program.participants.add(student)
        for team in teams or []:
            program.general_teams.add(team)
        return program

    def make_entry(self, program, start, duration=60, venue=None, day=None):
        return ScheduleEntry.objects.create(
            program=program,
            fest_day=day or self.day,
            start_time=start,
            duration_minutes=duration,
            venue=venue,
        )


class ProgramUnitsTests(ScheduleDataMixin, TestCase):
    def test_individual_program_units_are_students(self):
        program = self.make_program('Recitation', participants=[self.student_1])
        self.assertEqual(
            program_units(program),
            {('student', self.student_1.pk, 'Ahmad')},
        )

    def test_group_program_units_include_students_and_teams(self):
        program = self.make_program(
            'Group Song', participants=[self.student_1],
            teams=[self.team], is_group=True,
        )
        self.assertEqual(
            program_units(program),
            {
                ('student', self.student_1.pk, 'Ahmad'),
                ('team', self.team.pk, 'Al Hilal'),
            },
        )

    def test_general_program_units_are_teams_only(self):
        program = self.make_program('Quiz', teams=[self.team], is_general=True)
        self.assertEqual(
            program_units(program),
            {('team', self.team.pk, 'Al Hilal')},
        )


class IntervalOverlapTests(SimpleTestCase):
    def test_overlapping_ranges_are_detected(self):
        base = datetime(2026, 9, 10, 10, 0)
        self.assertTrue(
            interval_overlaps(base, 60, base + timedelta(minutes=30), 60)
        )

    def test_touching_ranges_do_not_overlap(self):
        base = datetime(2026, 9, 10, 10, 0)
        self.assertFalse(
            interval_overlaps(base, 60, base + timedelta(minutes=60), 60)
        )

    def test_disjoint_ranges_do_not_overlap(self):
        base = datetime(2026, 9, 10, 10, 0)
        self.assertFalse(
            interval_overlaps(base, 60, base + timedelta(minutes=120), 60)
        )

    def test_contained_range_overlaps(self):
        base = datetime(2026, 9, 10, 10, 0)
        self.assertTrue(
            interval_overlaps(base, 120, base + timedelta(minutes=30), 15)
        )

    def test_zero_duration_range_never_overlaps(self):
        base = datetime(2026, 9, 10, 10, 0)
        self.assertFalse(interval_overlaps(base, 0, base, 60))


class CheckScheduleConflictsTests(ScheduleDataMixin, TestCase):
    def test_disjoint_times_do_not_conflict(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_1])
        self.make_entry(prog_a, time(10, 0), duration=60)
        conflicts = check_schedule_conflicts(prog_b, self.day, time(11, 0), 60)
        self.assertEqual(conflicts, [])

    def test_same_student_overlapping_conflicts(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_1])
        self.make_entry(prog_a, time(10, 0), duration=60)
        conflicts = check_schedule_conflicts(prog_b, self.day, time(10, 30), 60)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]['kind'], 'participant')
        self.assertEqual(conflicts[0]['shared'], ['Ahmad'])

    def test_different_students_do_not_conflict(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_2])
        self.make_entry(prog_a, time(10, 0), duration=60)
        conflicts = check_schedule_conflicts(prog_b, self.day, time(10, 30), 60)
        self.assertEqual(conflicts, [])

    def test_touching_slots_do_not_conflict(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_1])
        self.make_entry(prog_a, time(10, 0), duration=60)
        conflicts = check_schedule_conflicts(prog_b, self.day, time(11, 0), 60)
        self.assertEqual(conflicts, [])

    def test_general_programs_sharing_a_team_conflict(self):
        prog_a = self.make_program('Quiz', teams=[self.team], is_general=True)
        prog_b = self.make_program('Soccer', teams=[self.team], is_general=True)
        self.make_entry(prog_a, time(10, 0), duration=60)
        conflicts = check_schedule_conflicts(prog_b, self.day, time(10, 45), 30)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]['kind'], 'participant')
        self.assertEqual(conflicts[0]['shared'], ['Al Hilal'])

    def test_same_venue_overlapping_conflicts(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_2])
        self.make_entry(prog_a, time(10, 0), duration=60, venue=self.venue_main)
        conflicts = check_schedule_conflicts(
            prog_b, self.day, time(10, 30), 60, venue=self.venue_main,
        )
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]['kind'], 'venue')

    def test_different_venues_do_not_conflict(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_2])
        self.make_entry(prog_a, time(10, 0), duration=60, venue=self.venue_main)
        conflicts = check_schedule_conflicts(
            prog_b, self.day, time(10, 30), 60, venue=self.venue_annex,
        )
        self.assertEqual(conflicts, [])

    def test_no_venue_conflict_when_proposed_venue_missing(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_2])
        self.make_entry(prog_a, time(10, 0), duration=60, venue=self.venue_main)
        conflicts = check_schedule_conflicts(prog_b, self.day, time(10, 30), 60)
        self.assertEqual(conflicts, [])

    def test_exclude_pk_skips_the_entry_being_edited(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_1])
        entry_b = self.make_entry(prog_b, time(10, 0), duration=60)
        conflicts = check_schedule_conflicts(prog_a, self.day, time(10, 30), 60)
        self.assertEqual(len(conflicts), 1)
        conflicts = check_schedule_conflicts(
            prog_a, self.day, time(10, 30), 60, exclude_pk=entry_b.pk,
        )
        self.assertEqual(conflicts, [])

    def test_entries_on_another_day_do_not_conflict(self):
        day_two = FestDay.objects.create(
            madrasa=self.madrasa, name='Day 2', date=date(2026, 9, 11),
        )
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_1])
        self.make_entry(prog_a, time(10, 0), duration=60, day=day_two)
        conflicts = check_schedule_conflicts(prog_b, self.day, time(10, 0), 60)
        self.assertEqual(conflicts, [])


class ComputeDayConflictsTests(ScheduleDataMixin, TestCase):
    def test_participant_and_venue_conflicts_are_reported(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program(
            'Essay Writing', participants=[self.student_1, self.student_2],
        )
        entry_a = self.make_entry(prog_a, time(10, 0), venue=self.venue_main)
        entry_b = self.make_entry(prog_b, time(10, 30), venue=self.venue_main)
        conflicts, entry_map = compute_day_conflicts([entry_a, entry_b])
        self.assertEqual(
            sorted(c['kind'] for c in conflicts), ['participant', 'venue'],
        )
        self.assertEqual(len(entry_map[entry_a.pk]), 2)
        self.assertEqual(len(entry_map[entry_b.pk]), 2)

    def test_non_overlapping_entries_are_clean(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_1])
        entry_a = self.make_entry(prog_a, time(10, 0), duration=60)
        entry_b = self.make_entry(prog_b, time(11, 0), duration=60)
        conflicts, entry_map = compute_day_conflicts([entry_a, entry_b])
        self.assertEqual(conflicts, [])
        self.assertEqual(entry_map[entry_a.pk], [])
        self.assertEqual(entry_map[entry_b.pk], [])

    def test_shared_participant_names_are_listed(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_1])
        entry_a = self.make_entry(prog_a, time(10, 0))
        entry_b = self.make_entry(prog_b, time(10, 30))
        conflicts, _ = compute_day_conflicts([entry_a, entry_b])
        self.assertEqual(conflicts[0]['shared'], ['Ahmad'])


class ScheduleBoardViewTests(ScheduleDataMixin, TestCase):
    def test_dashboard_requires_login(self):
        response = self.client.get(reverse('schedule_dashboard'))
        self.assertEqual(response.status_code, 302)

    def test_dashboard_renders_for_madrasa_user(self):
        prog = self.make_program('Recitation', participants=[self.student_1])
        self.make_entry(prog, time(10, 0), venue=self.venue_main)
        self.client.force_login(self.user)
        response = self.client.get(reverse('schedule_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recitation')
        self.assertEqual(response.context['total_conflicts'], 0)
        self.assertEqual(response.context['scheduled_count'], 1)
        # Delete/removal forms use the shared confirm dialog, not native confirm()
        html = response.content.decode()
        self.assertNotIn('return confirm(', html)
        self.assertIn('data-confirm="Delete this fest day', html)
        self.assertIn('data-confirm="Remove', html)

    def test_dashboard_counts_conflicts(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_1])
        self.make_entry(prog_a, time(10, 0), duration=60)
        self.make_entry(prog_b, time(10, 30), duration=60)
        self.client.force_login(self.user)
        response = self.client.get(reverse('schedule_dashboard'))
        self.assertEqual(response.context['total_conflicts'], 1)

    def test_dashboard_groups_pool_by_category_stage_first(self):
        category = Category.objects.create(name='Arts', madrasa=self.madrasa)
        stage = self.make_program('Qirath', participants=[self.student_1])
        category.programs.add(stage)
        non_stage = self.make_program('Quiz Prep', participants=[self.student_2])
        non_stage.non_stage = True
        non_stage.save()
        category.programs.add(non_stage)
        group = self.make_program('Group Song', is_group=True)
        category.programs.add(group)
        general = self.make_program('Team Quiz', is_general=True, teams=[self.team])
        self.client.force_login(self.user)
        response = self.client.get(reverse('schedule_dashboard'))
        groups = {g['key']: g for g in response.context['pool_categories']}
        arts = groups[f'cat-{category.pk}']
        self.assertEqual(arts['name'], 'Arts')
        # Stage list holds stage individual + stage group programs
        # (titles arrive in alphabetical order from the pool queryset).
        self.assertEqual([p.title for p in arts['stage']], ['Group Song', 'Qirath'])
        self.assertEqual([p.title for p in arts['non_stage']], ['Quiz Prep'])
        # Team-wise general programs without a category get their own bucket.
        self.assertEqual(groups['general']['name'], 'General (Team-wise)')
        self.assertIn(general, groups['general']['stage'])
        # Categories sort alphabetically before the general bucket.
        self.assertEqual(
            [g['key'] for g in response.context['pool_categories']],
            [f'cat-{category.pk}', 'general'],
        )

    def test_pool_lists_scheduled_programs_with_disabled_button(self):
        scheduled = self.make_program('Recitation', participants=[self.student_1])
        waiting = self.make_program('Solo Song', participants=[self.student_2])
        self.make_entry(scheduled, time(10, 0), venue=self.venue_main)
        # The scheduling UI (incl. pool buttons) is unlocked only after consent.
        self.madrasa.schedule_consent_confirmed = True
        self.madrasa.save(update_fields=['schedule_consent_confirmed'])
        self.client.force_login(self.user)
        response = self.client.get(reverse('schedule_dashboard'))
        self.assertEqual(response.status_code, 200)
        groups = {g['key']: g for g in response.context['pool_categories']}
        stage_titles = [p.title for p in groups['general']['stage']]
        self.assertEqual(stage_titles, ['Solo Song', 'Recitation'])
        for program in groups['general']['stage']:
            if program.title == 'Recitation':
                self.assertIsNotNone(program.scheduled_entry)
            else:
                self.assertIsNone(program.scheduled_entry)
        html = response.content.decode()
        self.assertNotIn(f'openAddScheduleModal({scheduled.pk}', html)
        self.assertIn(f'openAddScheduleModal({waiting.pk}', html)
        self.assertIn('Already scheduled', html)
        self.assertContains(response, '✓ Scheduled')
        self.assertEqual(response.context['pool_count'], 1)
        self.assertEqual(response.context['pool_total'], 2)

    def test_venue_detail_lists_scheduled_programs(self):
        program = self.make_program('Recitation', participants=[self.student_1])
        self.make_entry(program, time(10, 0), duration=60, venue=self.venue_main)
        self.client.force_login(self.user)
        response = self.client.get(reverse('venue_detail', args=[self.venue_main.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recitation')
        self.assertContains(response, 'Day 1')
        self.assertContains(response, '10:00 AM')
        self.assertContains(response, '11:00 AM')
        rows = response.context['scheduled_rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['entry'].program, program)
        self.assertEqual(rows[0]['end_time'], time(11, 0))

    def test_venue_detail_only_lists_its_own_schedule(self):
        program = self.make_program('Recitation', participants=[self.student_1])
        self.make_entry(program, time(10, 0), venue=self.venue_main)
        self.client.force_login(self.user)
        response = self.client.get(reverse('venue_detail', args=[self.venue_annex.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['scheduled_rows'], [])
        self.assertNotContains(response, '10:00 AM – 11:00 AM')

    def test_venue_detail_has_no_add_program_ui(self):
        self.make_program('Recitation', participants=[self.student_1])
        self.client.force_login(self.user)
        response = self.client.get(reverse('venue_detail', args=[self.venue_main.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Add Program to Venue')
        self.assertNotContains(response, 'programModal')
        self.assertContains(response, 'PDF Report')

    def test_venue_programs_pdf_downloads_with_schedule_details(self):
        program = self.make_program('Recitation', participants=[self.student_1])
        self.make_entry(program, time(10, 0), duration=60, venue=self.venue_main)
        self.client.force_login(self.user)
        response = self.client.get(reverse('download-venue-programs', args=[self.venue_main.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('Main Hall_programs.pdf', response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_dashboard_search_filters_pool_and_board(self):
        recitation = self.make_program('Recitation', participants=[self.student_1])
        self.make_program('Essay Writing', participants=[self.student_2])
        self.make_entry(recitation, time(10, 0))
        self.client.force_login(self.user)

        response = self.client.get(reverse('schedule_dashboard'), {'q': 'essay'})
        self.assertEqual(response.context['search_query'], 'essay')
        self.assertContains(response, 'Essay Writing')
        self.assertNotContains(response, 'Recitation')
        board_titles = [
            wrap['entry'].program.title
            for day in response.context['days'] for wrap in day['entries']
        ]
        self.assertEqual(board_titles, [])

        response = self.client.get(reverse('schedule_dashboard'), {'q': 'recitation'})
        board_titles = [
            wrap['entry'].program.title
            for day in response.context['days'] for wrap in day['entries']
        ]
        self.assertEqual(board_titles, ['Recitation'])

    def test_dashboard_inline_scripts_are_valid_javascript(self):
        """Guard: a single JS syntax error kills the whole inline script block.

        That would silently disable every button on the board (schedule/edit
        modals, day tabs). Validate the rendered page's inline scripts with
        ``node --check`` when Node.js is available.
        """
        if shutil.which('node') is None:
            self.skipTest('Node.js is not available')
        self.make_program('Recitation', participants=[self.student_1])
        self.client.force_login(self.user)
        response = self.client.get(reverse('schedule_dashboard'))
        self.assertEqual(response.status_code, 200)
        scripts = re.findall(br'<script>(.*?)</script>', response.content, re.S)
        self.assertTrue(scripts, 'No inline <script> blocks found on the dashboard')
        with tempfile.NamedTemporaryFile('wb', suffix='.js', delete=False) as handle:
            handle.write(b'\n'.join(scripts))
            path = handle.name
        try:
            result = subprocess.run(
                ['node', '--check', path],
                capture_output=True, text=True, timeout=30,
            )
        finally:
            os.unlink(path)
        self.assertEqual(
            result.returncode, 0,
            'Inline dashboard script has a JavaScript syntax error:\n'
            f'{result.stderr}',
        )

    def test_modal_elements_reach_the_rendered_dom(self):
        """Guard: malformed markup must not swallow modal elements.

        A tag missing its closing ``>`` merges with the next tag in the
        browser's parser, silently discarding the elements in between — the
        schedule modal would then crash with "Cannot set properties of null".
        Render a data-rich board (venues, entries, conflicts, pool) and verify
        every id the scripts look up survives into the parsed DOM.
        """
        stage = self.make_program('Recitation', participants=[self.student_1])
        group = self.make_program('Group Song', is_general=True, teams=[self.team])
        unscheduled = self.make_program('Solo Song', participants=[self.student_2])
        self.make_entry(stage, time(10, 0), venue=self.venue_main)
        self.make_entry(group, time(10, 30), venue=self.venue_main)
        self.client.force_login(self.user)
        response = self.client.get(reverse('schedule_dashboard'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()

        class IdCollector(HTMLParser):
            def __init__(self):
                super().__init__()
                self.ids = set()

            def handle_starttag(self, tag, attrs):
                for key, value in attrs:
                    if key == 'id':
                        self.ids.add(value)

        collector = IdCollector()
        collector.feed(html)
        referenced = set(re.findall(r"getElementById\('([^']+)'\)", html))
        missing = sorted(referenced - collector.ids)
        self.assertEqual(
            missing, [],
            'Elements referenced by the dashboard scripts are missing from '
            f'the parsed DOM (likely malformed markup): {missing}',
        )

    def test_template_has_no_truncated_tags(self):
        """Guard: no tag may be left without its closing ``>`` at line end."""
        template_path = Path(__file__).resolve().parents[2] / 'templates' / 'schedule' / 'schedule_dashboard.html'
        lines = template_path.read_text(encoding='utf-8').splitlines()
        truncated = [
            f'line {i}: {line.strip()[:80]}'
            for i, line in enumerate(lines, 1)
            if re.search(r'</[a-zA-Z][a-zA-Z0-9]*\s*$', line)
        ]
        self.assertEqual(
            truncated, [],
            'Tags missing their closing ">" (they merge with the next tag '
            f'in the browser parser and discard elements): {truncated}',
        )

    def test_category_list_has_edit_option(self):
        """Guard: every category card must expose its edit button + modal."""
        from applications.program.models import Category as CategoryModel

        category = CategoryModel.objects.create(name='Senior', madrasa=self.madrasa)
        self.client.force_login(self.user)
        response = self.client.get(f"{reverse('categories')}?team={self.team.id}")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        # Edit button emitted for the category
        self.assertIn(f"openEditModal('{category.id}')", html)
        self.assertIn(f'id="editModal-{category.id}"', html)
        self.assertIn("function openEditModal(id)", html)
        self.assertIn("function closeEditModal(id)", html)
        # Edit form posts to the edit endpoint with the team preserved
        self.assertIn(
            f"action=\"{reverse('edit_category', kwargs={'pk': category.id})}?team={self.team.id}\"",
            html,
        )
        # Standard category folder SVG icon (same as the detail page)
        self.assertIn('M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9', html)
        self.assertNotIn('📂 Categories', html)
        # Team filter only — no "All" chip, and card links carry the team
        self.assertNotIn('>All</a>', html)
        self.assertIn(
            f'href="{reverse("category_detail", kwargs={"pk": category.id})}?team={self.team.id}"',
            html,
        )
        # Standard page shell: plain background + sticky fixed header
        self.assertIn('class="bg-gray-100 font-sans"', html)
        self.assertIn('fixed top-0 w-full z-[140]', html)
        self.assertIn('max-w-7xl mx-auto p-4 sm:p-6 pt-24 sm:pt-28 pb-16', html)

    def test_category_page_defaults_to_first_team_without_query_param(self):
        """Guard: the categories page must always carry a team context.

        Category links append ``?team=`` so the detail page saves new
        students into that team — a missing team context was the root cause
        of students silently landing in no team.
        """
        from applications.program.models import Category as CategoryModel

        category = CategoryModel.objects.create(name='Junior', madrasa=self.madrasa)
        self.client.force_login(self.user)
        response = self.client.get(reverse('categories'))  # no ?team= param
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['current_team_id'], self.team.id)
        html = response.content.decode()
        self.assertIn(f'?team={self.team.id}', html)
        # Every category card link must carry the team through
        links = re.findall(r'href="([^"]*/category/\d+/[^"]*)"', html)
        self.assertTrue(links, 'No category links found on the categories page')
        for link in links:
            self.assertIn('?team=', link)

    def test_add_student_assigns_team_and_category(self):
        """Regression: students added from the detail page must land in the
        team and category shown on the page."""
        from applications.program.models import Category as CategoryModel, Student

        category = CategoryModel.objects.create(name='Senior', madrasa=self.madrasa)
        self.client.force_login(self.user)
        url = reverse('category_detail', kwargs={'pk': category.pk})
        response = self.client.post(f'{url}?team={self.team.id}', {
            'student_form': '1',
            'full_name': 'New Kid',
            'gender': 'male',
            'code_number': '101',
        })
        self.assertEqual(response.status_code, 302)
        student = Student.objects.get(full_name='New Kid')
        self.assertEqual(student.team_id, self.team.id)
        self.assertEqual(student.category_id, category.id)
        # And the student shows up in that team's boys list on the page
        page = self.client.get(f'{url}?team={self.team.id}')
        self.assertContains(page, 'New Kid')

    def test_category_detail_link_modals_scope_correctly(self):
        """Guard: the Reg/Results link modals bind to their own Alpine scopes.

        Regression: the Results modal was accidentally placed OUTSIDE the
        ``parentLinkModal()`` scope, so clicking "Results Link" did nothing
        while "Reg Link" opened BOTH stacked modals.
        """
        from applications.program.models import Category as CategoryModel, Program, Student

        category = CategoryModel.objects.create(name='Senior', madrasa=self.madrasa)
        # Add a boy + girl so the student cards (and their avatars) render
        Student.objects.create(
            full_name='Amin', category=category, team=self.team, gender='male'
        )
        Student.objects.create(
            full_name='Aisha', category=category, team=self.team, gender='female'
        )
        # And a program so the program cards (and their delete forms) render
        program = Program.objects.create(title='Recitation', madrasa=self.madrasa)
        category.programs.add(program)
        self.client.force_login(self.user)
        url = reverse('category_detail', kwargs={'pk': category.pk})
        response = self.client.get(f'{url}?team={self.team.id}')
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()

        # Back button removed (team-wise filter makes it redundant)
        self.assertNotIn('← Back', html)
        self.assertNotIn('Back to Categories', html)
        # Standard category SVG icon replaces the emoji in the header
        self.assertIn('M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9', html)
        # Standard page shell: plain background + fixed header + standard container
        self.assertIn('class="bg-gray-100 font-sans"', html)
        self.assertIn('fixed top-0 w-full z-[140]', html)
        self.assertIn('max-w-7xl mx-auto p-4 sm:p-6 pt-24 sm:pt-28 pb-16', html)
        self.assertNotIn('max-w-6xl mx-auto', html)
        self.assertNotIn('bg-gradient-to-r from-indigo-50 to-purple-50', html)
        # Both triggers present
        self.assertIn('>Reg Link<', html)
        self.assertIn('>Results Link<', html)
        # Results modal must sit INSIDE the parentLinkModal() scope (between
        # the scope-open and the outer-scope program modal)
        scope_start = html.index('x-data="parentLinkModal()"')
        results_modal = html.index('Students &amp; Results Link', scope_start)
        program_modal = html.index('Program Registration Link', scope_start)
        self.assertLess(scope_start, results_modal)
        self.assertLess(results_modal, program_modal)
        # Exactly one program modal and one results modal heading
        self.assertEqual(html.count('Program Registration Link'), 1)

        # Toast system replaces native alert() (header.html provides it)
        self.assertIn('id="toast-container"', html)
        self.assertIn('window.MeeladToast', html)
        self.assertIn('window.showToast', html)
        # No active alert() CALL remains (the comment "replaces native
        # alert()" in header.html legitimately contains `alert(`, so match
        # on the call form only)
        self.assertNotIn('alert("', html)
        # Gendered student avatars render as SVG icons, not bare initials
        self.assertIn('from-blue-500 to-indigo-600', html)
        self.assertIn('from-pink-500 to-rose-500', html)
        self.assertIn('M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z', html)
        # Custom confirmation dialog replaces native confirm() popups
        self.assertIn('window.MeeladConfirm', html)
        self.assertIn('async revokeLink() {', html)
        self.assertIn('data-confirm="Delete this student?"', html)
        self.assertIn('data-confirm="Delete this program?"', html)
        self.assertNotIn('return confirm(', html)
        self.assertNotIn('!confirm(', html)
        # Logout asks for confirmation and uses the standard SVG icons
        self.assertIn('window.confirmLogout', html)
        self.assertIn('onclick="return confirmLogout(event, this.href)"', html)
        self.assertIn('M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1', html)
        self.assertNotIn('🔓', html)
        self.assertNotIn('✖', html)
        self.assertNotIn('student.full_name|slice:', html)

        # Inline scripts must be syntactically valid JS (a single error kills
        # the whole block and silently disables every Alpine handler).
        if shutil.which('node') is None:
            self.skipTest('Node.js is not available')
        scripts = re.findall(br'<script>(.*?)</script>', response.content, re.S)
        with tempfile.NamedTemporaryFile('wb', suffix='.js', delete=False) as handle:
            handle.write(b'\n'.join(scripts))
            path = handle.name
        try:
            result = subprocess.run(
                ['node', '--check', path],
                capture_output=True, text=True, timeout=30,
            )
        finally:
            os.unlink(path)
        self.assertEqual(
            result.returncode, 0,
            'Category detail inline script has a JavaScript syntax error:\n'
            f'{result.stderr}',
        )

    def test_category_detail_link_js_gets_madrasa_id_without_team_filter(self):
        """Regression: link generation failed with "Missing madrasa_id".

        ``madrasa_id`` was only injected into the template context inside the
        ``?team=`` lookup block. Opening the category detail page without a
        team filter rendered ``madrasaId = ""``, so the generate/revoke API
        calls returned "Missing madrasa_id". The view must fall back to the
        logged-in user's madrasa id.
        """
        from applications.program.models import Category as CategoryModel

        category = CategoryModel.objects.create(name='Senior', madrasa=self.madrasa)
        self.client.force_login(self.user)
        url = reverse('category_detail', kwargs={'pk': category.pk})
        response = self.client.get(url)  # no ?team= filter
        self.assertEqual(response.status_code, 200)
        # The fallback branch must provide the institution id to the template
        self.assertEqual(response.context.get('madrasa_id'), self.madrasa.id)
        html = response.content.decode()
        self.assertIn(f'const madrasaId = "{self.madrasa.id}";', html)
        # And the actual link endpoint must succeed with that id
        gen = self.client.post(
            reverse('generate_program_link'),
            data='{"institution_id": %d}' % self.madrasa.id,
            content_type='application/json',
        )
        self.assertEqual(gen.status_code, 200)
        self.assertIn('link', gen.json())

    def test_portal_pages_use_full_width_layout_with_footer(self):
        """Guard: public Reg-link & Results-link pages must not break when the
        shared footer is included.

        They previously used ``flex items-center justify-center`` on the
        body, so the footer became a second flex item (breaking centering and
        clipping the card top on mobile). They must use ``flex flex-col`` with
        ``m-auto`` on the card so the footer flows full-width below.
        """
        from applications.program.models import ProgramRule
        from applications.program.views import encode_base62

        ProgramRule.objects.create(
            madrasa=self.madrasa,
            parent_view_link_active=True,
            program_reg_link_active=True,
        )
        code = encode_base62(self.madrasa.id)

        reg = self.client.get(
            reverse('student_registration') + f'?institution_id={self.madrasa.id}'
        )
        self.assertEqual(reg.status_code, 200)
        reg_html = reg.content.decode()
        self.assertIn('min-h-screen flex flex-col', reg_html)
        self.assertIn('m-auto', reg_html)
        self.assertNotIn('<body class="bg-gray-50 flex items-center justify-center', reg_html)

        portal = self.client.get(reverse('parents_portal', kwargs={'code': code}))
        self.assertEqual(portal.status_code, 200)
        portal_html = portal.content.decode()
        self.assertIn('min-h-screen flex flex-col', portal_html)
        self.assertIn('m-auto', portal_html)
        self.assertNotIn(
            '<body class="bg-gradient-to-br from-indigo-50 via-purple-50 to-pink-50 '
            'min-h-screen flex items-center justify-center',
            portal_html,
        )

    def test_add_fest_day(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('add_fest_day'), {
            'name': 'Day 2', 'date': '2026-09-11',
        })
        self.assertRedirects(response, reverse('schedule_dashboard'))
        self.assertTrue(
            FestDay.objects.filter(name='Day 2', date=date(2026, 9, 11)).exists()
        )

    def test_add_fest_day_rejects_invalid_date(self):
        self.client.force_login(self.user)
        self.client.post(reverse('add_fest_day'), {'name': 'Bad', 'date': 'not-a-date'})
        self.assertFalse(FestDay.objects.filter(name='Bad').exists())

    def test_add_schedule_creates_entry_and_resyncs_program(self):
        prog = self.make_program('Recitation', participants=[self.student_1])
        self.client.force_login(self.user)
        response = self.client.post(reverse('add_schedule'), {
            'program': prog.pk,
            'fest_day': self.day.pk,
            'start_time': '10:00',
            'duration_minutes': '60',
            'venue': self.venue_main.pk,
            'notes': 'bring the mic',
        })
        self.assertRedirects(response, reverse('schedule_dashboard'))
        entry = ScheduleEntry.objects.get(program=prog)
        self.assertEqual(entry.start_time, time(10, 0))
        self.assertEqual(entry.duration_minutes, 60)
        self.assertEqual(entry.venue, self.venue_main)
        self.assertEqual(entry.notes, 'bring the mic')
        prog.refresh_from_db()
        self.assertEqual(prog.scheduled_time, timezone.make_aware(datetime(2026, 9, 10, 10, 0)))
        self.assertEqual(prog.venue, self.venue_main)

    def test_add_schedule_warns_on_conflict(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_1])
        self.make_entry(prog_a, time(10, 0), duration=60)
        self.client.force_login(self.user)
        response = self.client.post(reverse('add_schedule'), {
            'program': prog_b.pk, 'fest_day': self.day.pk,
            'start_time': '10:30', 'duration_minutes': '30',
        })
        entry = ScheduleEntry.objects.get(program=prog_b)  # slot is still saved
        self.assertEqual(entry.start_time, time(10, 30))
        storage = [str(m).lower() for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('conflict' in text for text in storage))

    def test_add_schedule_rejects_double_booking_of_a_program(self):
        prog = self.make_program('Recitation', participants=[self.student_1])
        self.make_entry(prog, time(10, 0), duration=60)
        self.client.force_login(self.user)
        self.client.post(reverse('add_schedule'), {
            'program': prog.pk, 'fest_day': self.day.pk,
            'start_time': '15:00', 'duration_minutes': '30',
        })
        self.assertEqual(ScheduleEntry.objects.filter(program=prog).count(), 1)

    def test_add_schedule_requires_valid_fields(self):
        prog = self.make_program('Recitation', participants=[self.student_1])
        self.client.force_login(self.user)
        self.client.post(reverse('add_schedule'), {'program': prog.pk})
        self.assertEqual(ScheduleEntry.objects.count(), 0)


    def test_edit_schedule_moves_entry_and_resyncs_program(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_2])
        entry = self.make_entry(prog_a, time(10, 0), venue=self.venue_main)
        self.make_entry(prog_b, time(12, 0), duration=60)
        self.client.force_login(self.user)
        response = self.client.post(reverse('edit_schedule', args=[entry.pk]), {
            'fest_day': self.day.pk,
            'start_time': '12:00',
            'duration_minutes': '45',
            'venue': self.venue_annex.pk,
        })
        entry.refresh_from_db()
        self.assertEqual(entry.start_time, time(12, 0))
        self.assertEqual(entry.duration_minutes, 45)
        self.assertEqual(entry.venue, self.venue_annex)
        prog_a.refresh_from_db()
        self.assertEqual(prog_a.scheduled_time, timezone.make_aware(datetime(2026, 9, 10, 12, 0)))
        self.assertEqual(prog_a.venue, self.venue_annex)
        storage = [str(m).lower() for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('no conflicts' in text for text in storage))

    def test_edit_schedule_warns_when_moved_into_a_conflict(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_1])
        entry = self.make_entry(prog_a, time(10, 0), duration=60)
        self.make_entry(prog_b, time(12, 0), duration=60)
        self.client.force_login(self.user)
        response = self.client.post(reverse('edit_schedule', args=[entry.pk]), {
            'fest_day': self.day.pk,
            'start_time': '12:30',
            'duration_minutes': '30',
        })
        storage = [str(m).lower() for m in get_messages(response.wsgi_request)]
        self.assertTrue(any('conflict' in text for text in storage))

    def test_delete_schedule_clears_the_program(self):
        prog = self.make_program('Recitation', participants=[self.student_1])
        entry = self.make_entry(prog, time(10, 0), venue=self.venue_main)
        prog.scheduled_time = timezone.make_aware(datetime(2026, 9, 10, 10, 0))
        prog.venue = self.venue_main
        prog.save()
        self.client.force_login(self.user)
        response = self.client.post(reverse('delete_schedule', args=[entry.pk]))
        self.assertRedirects(response, reverse('schedule_dashboard'))
        self.assertFalse(ScheduleEntry.objects.filter(pk=entry.pk).exists())
        prog.refresh_from_db()
        self.assertIsNone(prog.scheduled_time)
        self.assertIsNone(prog.venue)

    def test_delete_fest_day_clears_scheduled_programs(self):
        prog = self.make_program('Recitation', participants=[self.student_1])
        entry = self.make_entry(prog, time(10, 0), venue=self.venue_main)
        prog.scheduled_time = timezone.make_aware(datetime(2026, 9, 10, 10, 0))
        prog.venue = self.venue_main
        prog.save()
        # The scheduling UI is unlocked only after consent.
        self.madrasa.schedule_consent_confirmed = True
        self.madrasa.save(update_fields=['schedule_consent_confirmed'])
        self.client.force_login(self.user)

        # Pool shows it as scheduled before deletion (disabled button).
        before = self.client.get(reverse('schedule_dashboard'))
        self.assertIn('Already scheduled', before.content.decode())

        response = self.client.post(reverse('delete_fest_day', args=[self.day.pk]))
        self.assertRedirects(response, reverse('schedule_dashboard'))
        self.assertFalse(ScheduleEntry.objects.filter(pk=entry.pk).exists())
        prog.refresh_from_db()
        self.assertIsNone(prog.scheduled_time)
        self.assertIsNone(prog.venue)

        # The pool now re-offers the program for scheduling.
        after = self.client.get(reverse('schedule_dashboard'))
        html = after.content.decode()
        self.assertIn(f'openAddScheduleModal({prog.pk},', html)
        self.assertNotIn('Already scheduled', html)

    def test_delete_fest_day_via_orm_also_reverts_programs(self):
        """Admin/ORM day deletion triggers the pre_delete signal, so programs
        never keep a stale mirrored schedule."""
        prog = self.make_program('Recitation', participants=[self.student_1])
        self.make_entry(prog, time(10, 0), venue=self.venue_main)
        prog.scheduled_time = timezone.make_aware(datetime(2026, 9, 10, 10, 0))
        prog.venue = self.venue_main
        prog.save()

        # Bare ORM delete (what Django admin does) — no view involved.
        self.day.delete()

        self.assertFalse(ScheduleEntry.objects.filter(program=prog).exists())
        prog.refresh_from_db()
        self.assertIsNone(prog.scheduled_time)
        self.assertIsNone(prog.venue)

    def test_delete_entry_via_orm_also_reverts_program(self):
        """Removing a single ScheduleEntry directly (admin path) also clears
        the mirrored program fields."""
        prog = self.make_program('Recitation', participants=[self.student_1])
        entry = self.make_entry(prog, time(10, 0), venue=self.venue_main)
        prog.scheduled_time = timezone.make_aware(datetime(2026, 9, 10, 10, 0))
        prog.venue = self.venue_main
        prog.save()

        entry.delete()

        prog.refresh_from_db()
        self.assertIsNone(prog.scheduled_time)
        self.assertIsNone(prog.venue)


class ScheduleConsentTests(ScheduleDataMixin, TestCase):
    """Schedule-ready consent gate + registration-link locking."""

    def make_team_student(self, name='Fathima'):
        """A student that belongs to the test madrasa via its team."""
        return Student.objects.create(
            full_name=name, team=self.team, category=None
        )

    def test_dashboard_gate_locks_pool_when_not_confirmed(self):
        prog = self.make_program('Recitation', participants=[self.student_1])
        self.client.force_login(self.user)
        html = self.client.get(reverse('schedule_dashboard')).content.decode()

        # Gate banner + consent modal are rendered.
        self.assertIn('Confirm programs & participation to start scheduling', html)
        self.assertIn('id="consentModal"', html)
        # The pool Schedule button is locked (opens the consent modal, not the
        # real schedule modal).
        self.assertIn('onclick="openConsentModal()"', html)
        self.assertNotIn(
            f'openAddScheduleModal({prog.pk},', html
        )
        self.assertNotIn('Schedule-ready — programs & participation confirmed', html)

    def test_confirm_consent_records_timestamp_and_unlocks(self):
        prog = self.make_program('Recitation', participants=[self.student_1])
        self.client.force_login(self.user)
        response = self.client.post(reverse('set_schedule_consent'), {'agree': '1'})
        self.assertRedirects(response, reverse('schedule_dashboard'))

        self.madrasa.refresh_from_db()
        self.assertTrue(self.madrasa.schedule_consent_confirmed)
        self.assertIsNotNone(self.madrasa.schedule_consent_confirmed_at)

        html = self.client.get(reverse('schedule_dashboard')).content.decode()
        self.assertIn('Schedule-ready — programs & participation confirmed', html)
        self.assertIn(
            f'openAddScheduleModal({prog.pk},', html
        )
        self.assertNotIn('onclick="openConsentModal()"', html)
        self.assertNotIn('Confirm programs & participation to start scheduling', html)

    def test_revoke_consent_resets_flag_and_relocks(self):
        self.client.force_login(self.user)
        self.client.post(reverse('set_schedule_consent'), {'agree': '1'})
        self.madrasa.refresh_from_db()
        self.assertTrue(self.madrasa.schedule_consent_confirmed)

        response = self.client.post(reverse('set_schedule_consent'), {'revoke': '1'})
        self.assertRedirects(response, reverse('schedule_dashboard'))
        self.madrasa.refresh_from_db()
        self.assertFalse(self.madrasa.schedule_consent_confirmed)
        self.assertIsNone(self.madrasa.schedule_consent_confirmed_at)

    def test_register_program_rejected_when_consent_confirmed(self):
        student = self.make_team_student()
        prog = self.make_program('Recitation', participants=[self.student_1])
        self.madrasa.schedule_consent_confirmed = True
        self.madrasa.save(update_fields=['schedule_consent_confirmed'])

        response = self.client.post(
            reverse('register_program'),
            {'student': student.pk, 'programs': [prog.pk]},
        )
        data = response.json()
        self.assertEqual(data['message'], 'error')
        self.assertIn('closed', data['details'].lower())
        self.assertFalse(student.program_set.filter(pk=prog.pk).exists())

    def test_register_program_allowed_before_consent(self):
        student = self.make_team_student()
        prog = self.make_program('Recitation', participants=[self.student_1])

        response = self.client.post(
            reverse('register_program'),
            {'student': student.pk, 'programs': [prog.pk]},
        )
        data = response.json()
        self.assertEqual(data['message'], 'success')
        self.assertTrue(student.program_set.filter(pk=prog.pk).exists())

    def test_registration_form_shows_locked_notice_when_consent_confirmed(self):
        self.madrasa.schedule_consent_confirmed = True
        self.madrasa.save(update_fields=['schedule_consent_confirmed'])

        response = self.client.get(
            reverse('student_registration') + f'?institution_id={self.madrasa.id}'
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('Program registration is closed', html)
        self.assertNotIn('id="multiStepForm"', html)

    def test_registration_form_renders_when_not_confirmed(self):
        response = self.client.get(
            reverse('student_registration') + f'?institution_id={self.madrasa.id}'
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertNotIn('Program registration is closed', html)
        self.assertIn('id="multiStepForm"', html)


class ConflictCheckApiTests(ScheduleDataMixin, TestCase):
    def post_payload(self, payload):
        return self.client.post(
            reverse('check_schedule_conflicts'),
            data=json.dumps(payload),
            content_type='application/json',
        )

    def test_requires_post(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('check_schedule_conflicts'))
        self.assertEqual(response.status_code, 405)

    def test_reports_participant_conflict(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_1])
        self.make_entry(prog_a, time(10, 0), duration=60)
        self.client.force_login(self.user)
        response = self.post_payload({
            'program': prog_b.pk, 'fest_day': self.day.pk,
            'start_time': '10:30', 'duration_minutes': 30,
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['ok'])
        self.assertEqual(len(data['conflicts']), 1)
        self.assertEqual(data['conflicts'][0]['kind'], 'participant')
        self.assertEqual(data['conflicts'][0]['shared'], ['Ahmad'])

    def test_reports_venue_conflict(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_2])
        self.make_entry(prog_a, time(10, 0), duration=60, venue=self.venue_main)
        self.client.force_login(self.user)
        response = self.post_payload({
            'program': prog_b.pk, 'fest_day': self.day.pk,
            'start_time': '10:30', 'duration_minutes': 30,
            'venue': self.venue_main.pk,
        })
        data = response.json()
        self.assertFalse(data['ok'])
        self.assertEqual(data['conflicts'][0]['kind'], 'venue')

    def test_clear_slot_is_ok(self):
        prog_a = self.make_program('Recitation', participants=[self.student_1])
        prog_b = self.make_program('Essay Writing', participants=[self.student_1])
        self.make_entry(prog_a, time(10, 0), duration=60)
        self.client.force_login(self.user)
        response = self.post_payload({
            'program': prog_b.pk, 'fest_day': self.day.pk,
            'start_time': '12:00', 'duration_minutes': 30,
        })
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['conflicts'], [])

    def test_invalid_time_is_reported_cleanly(self):
        prog = self.make_program('Recitation', participants=[self.student_1])
        self.client.force_login(self.user)
        response = self.post_payload({
            'program': prog.pk, 'fest_day': self.day.pk,
            'start_time': '25:99', 'duration_minutes': 30,
        })
        data = response.json()
        self.assertFalse(data['ok'])
        self.assertEqual(data['conflicts'], [])

    def test_unknown_program_is_ignored(self):
        self.client.force_login(self.user)
        response = self.post_payload({
            'program': 999999, 'fest_day': self.day.pk,
            'start_time': '10:00', 'duration_minutes': 30,
        })
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['conflicts'], [])

    def test_user_without_madrasa_gets_400(self):
        other_user = User.objects.create_user(
            email='nomadrasa@test.com', phone_number='9999999999',
            password='testpass123',
        )
        self.client.force_login(other_user)
        response = self.post_payload({})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])

class MobileHeaderLayoutTests(TestCase):
    """Guard: the fixed header's brand row must never push the mobile
    hamburger off-screen.

    Regression: the fest-name span had no truncation and the brand anchor
    could not shrink (flex items default to ``min-width: auto``), so a long
    ``meelad_fest_name`` overflowed the header row on phones and the
    ``justify-between`` layout pushed the hamburger past the right edge of
    the viewport — invisible until the page was panned sideways.
    """

    LONG_NAME = 'Majlisu Miladi Sharif Mega Annual Fest 2026 Edition'

    def test_brand_row_shrinks_instead_of_overflowing(self):
        from applications.subscription.models import Subscription

        madrasa = Madrasa.objects.create(
            name='Header Madrasa', meelad_fest_name=self.LONG_NAME,
        )
        user = User.objects.create_user(
            email='header@test.com', phone_number='9600000001',
            madrasa=madrasa, password='testpass123',
        )
        Subscription.objects.create(
            institution=madrasa, active=True,
            start_date=timezone.now(), end_date=timezone.now() + timedelta(days=30),
        )
        self.client.force_login(user)
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()

        # The mobile hamburger is present exactly once.
        self.assertEqual(html.count('id="menu-toggle"'), 1)
        # The brand anchor is shrinkable (defeats flex min-width:auto) and
        # the fest name truncates with an ellipsis instead of overflowing.
        self.assertRegex(
            html, r'<a href="[^"]*"\s+class="[^"]*\bmin-w-0\b[^"]*"')
        self.assertRegex(html, r'<span\s+class="min-w-0 truncate [^"]*"')
        # The right-hand cluster keeps its size so the hamburger stays put.
        self.assertIn('class="flex items-center space-x-4 shrink-0"', html)

