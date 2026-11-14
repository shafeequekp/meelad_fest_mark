import base64
import hashlib
import json
import csv
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import time
from io import BytesIO
from pathlib import Path

from PIL import Image as PILImage

from django.conf import settings
from django.contrib.staticfiles import finders

from django.utils.html import escape
from django.utils import timezone
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

from datetime import datetime, timedelta

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl import load_workbook

# from xhtml2pdf import pisa

from io import BytesIO
from django.shortcuts import render, get_object_or_404, redirect
from django.views import generic, View
from django.http import HttpResponseRedirect, FileResponse, HttpResponse, JsonResponse, Http404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.template.loader import get_template
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Case, When, Value, BooleanField, Q, Sum, FloatField, Count
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.views.decorators.http import require_GET
from django.shortcuts import redirect, get_object_or_404 
from django.db.models.functions import Coalesce

from applications.scoreboard.models import Team


def _is_ajax(request):
    """True for browser fetch() calls (all Meelad AJAX posts send this header).

    Views branch on this to return compact JSON instead of a full redirect,
    so forms can update the page in place without a reload. Every form still
    works without JS: the redirect fallback below is unchanged.
    """
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"
from applications.schedule.models import ScheduleEntry
from applications.program.models import Category, Program, Student, Prize, Position, Grade, GroupPosition, GeneralPosition, \
    ProgramRule, Venue, program_section_q, Judge, Evaluation, EvaluationCriterion, TrashItem
from .forms import CategoryForm, ProgramForm, StudentForm, EditStudentForm
from applications.accounts.models import Madrasa


def _fest_section(madrasa):
    """Return the madrasa's active fest section mode ('both'/'boys'/'girls').

    Existing institutions that predate the fest_type setting default to 'both'.
    """
    if madrasa is None:
        return Madrasa.FEST_TYPE_BOTH
    return madrasa.fest_type or Madrasa.FEST_TYPE_BOTH


def _fest_active_genders(madrasa):
    """List of Student.gender values that participate in this madrasa's fest."""
    return madrasa.active_genders() if madrasa else ['male', 'female']


def _is_fest_section_active(madrasa, section):
    """Return True when ``section`` ('boys'/'girls') may be shown/used."""
    return section in madrasa.active_fest_sections


def _safe_team_id(value):
    """Normalize a `?team=` query value to a usable id string (or None).

    Some flows build redirect URLs with ``?team=None`` (the raw ``None``
    from ``request.GET.get('team')``), and a stale link/bookmark may carry
    ``None`` too. Passing that through ``Team.objects.get(id="None")`` raises
    ``ValueError`` (500) instead of being treated as “no team”.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in ('none', 'null'):
        return None
    return s


@csrf_exempt
def register_program(request):
    if request.method == 'POST':
        student_id = request.POST.get('student')
        program_ids = request.POST.getlist('programs[]') or request.POST.getlist('programs')

        if not student_id or not program_ids:
            return JsonResponse({"message": "error", "details": "Missing student or programs"})

        try:
            student = Student.objects.get(id=student_id)
        except Student.DoesNotExist:
            return JsonResponse({"message": "error", "details": "Invalid student"})

        # Schedule-ready consent: once the coordinator confirms all programs and
        # participation are final, the generated registration link is locked so
        # no new student → program registrations can change conflict data mid-
        # scheduling.
        madrasa = student.team.madrasa if student.team_id else None
        if madrasa and madrasa.schedule_consent_confirmed:
            return JsonResponse({
                "message": "error",
                "details": (
                    "Program registration is closed — the coordinator has "
                    "confirmed the schedule. Please contact the coordinator "
                    "if a change is needed."
                ),
            })

        programs = Program.objects.filter(id__in=program_ids)

        # for program in programs:
        #     program.participants.add(student)
        student.program_set.set(programs)

        program_names = list(student.program_set.values_list('title', flat=True))

        return JsonResponse({"message": "success", "programs": program_names})
    return JsonResponse({"message": "error", "details": "Invalid request"})


def generate_program_reg_link(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            madrasa_id = data.get('institution_id')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        if not madrasa_id:
            return JsonResponse({'error': 'Missing madrasa_id'}, status=400)
        
        madrasa = Madrasa.objects.get(id=madrasa_id)
        rule, _ = ProgramRule.objects.get_or_create(madrasa=madrasa)
        rule.program_reg_link_active = True
        rule.save()

        encoded = encode_base62(int(madrasa_id)) 
        scheme = "https" if request.is_secure() else "http"
        host = request.META.get('HTTP_HOST')
        short_link = f"{scheme}://{host}/x/{encoded}"

        # host_url = f"{request.scheme}://{request.get_host()}"
        link_generated = short_link

        return JsonResponse({"message": "success", "link": link_generated})
    
    return JsonResponse({'error': 'Invalid request method'}, status=405)
    

def revoke_program_link(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            madrasa_id = data.get('institution_id')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
  
        rule = ProgramRule.objects.filter(madrasa_id=madrasa_id).last()
        if rule:
            rule.program_reg_link_active = False
            rule.save()
            return JsonResponse({"success": True, "message": "success"})
        return JsonResponse({"message": "error", "details": "Please add rule first"})
    return JsonResponse({'error': 'Invalid request method'}, status=405)


# ---------------------------------------------------------------------------
# Parents/Students portal links (see each student's programs & published results)
# ---------------------------------------------------------------------------
def generate_parent_link(request):
    """Generate a public short link to the parents/students portal for a madrasa."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)

    try:
        data = json.loads(request.body)
        madrasa_id = data.get('institution_id')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    if not madrasa_id:
        return JsonResponse({'error': 'Missing institution_id'}, status=400)

    try:
        madrasa = Madrasa.objects.get(id=madrasa_id)
    except Madrasa.DoesNotExist:
        return JsonResponse({'error': 'Madrasa not found'}, status=404)

    rule, _ = ProgramRule.objects.get_or_create(madrasa=madrasa)
    rule.parent_view_link_active = True
    rule.save()

    encoded = encode_base62(int(madrasa_id))
    scheme = "https" if request.is_secure() else "http"
    host = request.META.get('HTTP_HOST')
    short_link = f"{scheme}://{host}/p/{encoded}/"

    return JsonResponse({"message": "success", "link": short_link})


def revoke_parent_link(request):
    """Deactivate the parents/students portal link for a madrasa."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method'}, status=405)

    try:
        data = json.loads(request.body)
        madrasa_id = data.get('institution_id')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    rule = ProgramRule.objects.filter(madrasa_id=madrasa_id).last()
    if rule:
        rule.parent_view_link_active = False
        rule.save()
        return JsonResponse({"success": True, "message": "success"})
    return JsonResponse({"message": "error", "details": "Please add rule first"})



# Ajax endpoint to get categories for team
def load_categories(request):
    madrasa_id = request.GET.get('madrasa_id')

    if not madrasa_id:
        return JsonResponse([], safe=False)

    try:
        madrasa = Madrasa.objects.get(id=madrasa_id)
    except Madrasa.DoesNotExist:
        return JsonResponse([], safe=False)

    categories = Category.objects.filter(madrasa=madrasa)
    data = [{'id': cat.id, 'name': cat.name} for cat in categories]
    return JsonResponse(data, safe=False)


# Ajax endpoint to get students for category & gender
def load_students(request):
    category_id = request.GET.get('category')
    gender = request.GET.get('gender')
    team_id = _safe_team_id(request.GET.get('team'))  # Get team_id from request

    # On a single-section fest only the active section's gender may be listed.
    category = Category.objects.filter(id=category_id).first()
    if category and category.madrasa_id:
        active_genders = _fest_active_genders(category.madrasa)
        if gender not in active_genders:
            gender = active_genders[0] if active_genders else gender

    if category_id and gender and team_id:
        students = Student.objects.filter(
            category_id=category_id,
            gender=gender,
            team_id=team_id
        )
        data = [{'id': stu.id, 'name': stu.full_name} for stu in students]
    else:
        data = []

    return JsonResponse(data, safe=False)

def load_programs(request):
    category_id = request.GET.get('category')
    gender = request.GET.get('gender')

    # On a single-section fest only the active section's gender may be used.
    category = Category.objects.filter(id=category_id).first()
    if category and category.madrasa_id:
        active_genders = _fest_active_genders(category.madrasa)
        if gender not in active_genders:
            gender = active_genders[0] if active_genders else gender

    if category_id and gender:
        try:
            category = Category.objects.get(id=category_id)
        except Category.DoesNotExist:
            return JsonResponse([], safe=False)

        if gender == 'female':
            programs = category.programs_for_girls.all()
        else:
            programs = category.programs.all()

        data = [{'id': prog.id, 'title': prog.title} for prog in programs]
    else:
        data = []

    return JsonResponse(data, safe=False)


def load_team_students(request):
    """Ajax endpoint: return students belonging to a given team.

    Used by the general-programs page when the user selects a team in a
    team-card so the participants ``<select multiple>`` can be populated.

    Supports an optional ``section`` query param ('boys' / 'girls') so that only
    the team members of the matching gender are listed for that program's
    section (Boys section → male students, Girls section → female students).
    When no/invalid section is given it falls back to returning all members.
    """
    team_id = _safe_team_id(request.GET.get('team_id'))
    if not team_id:
        return JsonResponse([], safe=False)
    try:
        team = Team.objects.get(id=team_id)
    except (Team.DoesNotExist, ValueError):
        return JsonResponse([], safe=False)
    students = Student.objects.filter(team=team)
    section = request.GET.get('section')

    # Enforce the fest section mode: on a boys-only / girls-only fest the teams
    # only contain one section, so the panel is limited to the active gender.
    if team.madrasa_id:
        active_genders = _fest_active_genders(team.madrasa)
        if section not in (Program.SECTION_BOYS, Program.SECTION_GIRLS):
            section = active_genders[0] if len(active_genders) == 1 else None
        elif not _is_fest_section_active(team.madrasa, section):
            section = active_genders[0] if len(active_genders) == 1 else None

    if section == Program.SECTION_BOYS:
        filtered = students.filter(gender='male')
        # If gender-filtering would empty a non-empty team (e.g. students whose
        # gender was left blank on upload), fall back to the full roster so the
        # participant picker is never silently empty.
        students = filtered if filtered.exists() else students
    elif section == Program.SECTION_GIRLS:
        filtered = students.filter(gender='female')
        students = filtered if filtered.exists() else students
    data = [{'id': s.id, 'name': f"{s.full_name} ({s.code_number or 'No Code'})"} for s in students]
    return JsonResponse(data, safe=False)



class CategoryView(LoginRequiredMixin, generic.ListView):
    template_name = 'program/category.html'
    context_object_name = 'categories'

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, "madrasa") and user.madrasa:
            return Category.objects.filter(madrasa=user.madrasa)
        return Category.objects.none()

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        team_id = _safe_team_id(self.request.GET.get('team'))
        team = None
        try:
            team = Team.objects.get(id=team_id) if team_id else None
        except (Team.DoesNotExist, ValueError):
            team = None

        user = self.request.user
        madrasa = user.madrasa
        if team is None and madrasa:
            # A team context is required on this page: every category link
            # carries it through to the detail page so new students land in
            # the right team (and show up in that team's student list).
            team = Team.objects.filter(madrasa=madrasa).order_by('name').first()

        context['team'] = team
        context['team_name'] = team.name if team else 'Unknown Team'
        context['team_id'] = str(team.id) if team else (team_id or '')
        context['current_team_id'] = team.id if team else None
        if team:
            context.update(team.theme_context())

        context['meelad_fest_name'] = madrasa.meelad_fest_name if madrasa else None
        context["total_students"] = Student.objects.filter(team__madrasa=madrasa).count()
        categories = Category.objects.filter(madrasa=madrasa)
        context["total_programs"] = Program.objects.filter(Q(category__in=categories) | Q(madrasa=madrasa)).distinct().count()
        context['teams'] = Team.objects.filter(madrasa=madrasa)

        return context


class AddCategoryView(LoginRequiredMixin, View):
    template_name = 'program/category.html'

    def get(self, request):
        form = CategoryForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = CategoryForm(request.POST)
        team_id = _safe_team_id(request.GET.get('team'))
        if form.is_valid():
            category = form.save(commit=False)
            category.madrasa = request.user.madrasa
            category.save()
            form.save_m2m()
            url = reverse('categories')
            if team_id:
                url = f"{url}?team={team_id}"  # keep the team context across the redirect
            if _is_ajax(request):
                return JsonResponse({
                    "ok": True,
                    "message": f"Category '{category.name}' added successfully.",
                    "redirect": url,
                })
            return redirect(url)
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": form.errors.as_text()}, status=400)
        return render(request, self.template_name, {'form': form})



class EditCategoryView(View):
    template_name = 'program/category.html'

    def get(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        form = CategoryForm(instance=category)
        return render(request, self.template_name, {"form": form, "category": category})

    def post(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        form = CategoryForm(request.POST, instance=category)
        team_id = _safe_team_id(self.request.GET.get('team'))
        if form.is_valid():
            form.save()
            url = reverse('categories')
            if team_id:
                url = f"{url}?team={team_id}"  # keep the team context across the redirect
            if _is_ajax(request):
                return JsonResponse({
                    "ok": True,
                    "message": f"Category '{category.name}' updated successfully.",
                    "redirect": url,
                })
            return redirect(url)
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": form.errors.as_text()}, status=400)
        return render(request, self.template_name, {"form": form, "category": category})


class CategoryDetailView(generic.DetailView):
    model = Category
    template_name = "program/category_detail.html"
    context_object_name = "category"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        category = self.get_object()

        # related objects
        team_id = _safe_team_id(self.request.GET.get("team"))
        teams = Team.objects.none()
        try:
            team_obj = Team.objects.get(id=team_id)
            context['team'] = team_obj
            context['team_name'] = team_obj.name
            context['team_id'] = team_id
            context.update(team_obj.theme_context())
            madrasa_id = team_obj.madrasa.id
            context['madrasa_id'] = madrasa_id
            teams = Team.objects.filter(madrasa_id=madrasa_id).order_by('name')
            rule = ProgramRule.objects.filter(madrasa_id=madrasa_id).last()
            context['reg_link_active'] = False
            context['parent_link_active'] = False
            if rule:
                context['reg_link_active'] = rule.program_reg_link_active
                context['parent_link_active'] = rule.parent_view_link_active

            encoded = encode_base62(int(madrasa_id))
            scheme = "https" if self.request.is_secure() else "http"
            host = self.request.META.get('HTTP_HOST')
            context['form_url'] = f"{scheme}://{host}/x/{encoded}"
            context['parent_form_url'] = f"{scheme}://{host}/p/{encoded}/"
        except Exception:
            pass

        if 'form_url' not in context and getattr(self.request.user, 'madrasa', None):
            institution_id = self.request.user.madrasa.id
            encoded = encode_base62(institution_id)
            scheme = "https" if self.request.is_secure() else "http"
            host = self.request.META.get('HTTP_HOST')
            context['form_url'] = f"{scheme}://{host}/x/{encoded}"
            context['parent_form_url'] = f"{scheme}://{host}/p/{encoded}/"
            # Ensure the JS always has a real institution id even when the page
            # was opened without a valid ?team= filter (otherwise the link
            # generate/revoke calls fail with "Missing madrasa_id").
            context['madrasa_id'] = institution_id
            teams = Team.objects.filter(madrasa_id=institution_id).order_by('name')
        elif 'form_url' not in context:
            context['form_url'] = ""
            context['parent_form_url'] = ""
        context['teams'] = teams

        madrasa = getattr(self.request.user, 'madrasa', None)
        # On a single-section fest only the active section's data is shown.
        show_boys = madrasa is None or not madrasa.is_girls_only
        show_girls = madrasa is None or not madrasa.is_boys_only

        context["boys"] = (
            Student.objects.filter(category=category, gender='male', team_id=team_id).order_by('-total_point')
            if show_boys else Student.objects.none()
        )
        context['girls'] = (
            Student.objects.filter(category=category, gender='female', team_id=team_id).order_by('-total_point')
            if show_girls else Student.objects.none()
        )

        general_programs = Program.objects.filter(is_general=True, madrasa=madrasa) if madrasa else Program.objects.none()
        boys_general = general_programs.filter(section=Program.SECTION_BOYS)
        girls_general = general_programs.filter(section=Program.SECTION_GIRLS)
        boys_programs = (category.programs.all() | boys_general).distinct() if show_boys else Program.objects.none()
        girls_programs = (category.programs_for_girls.all() | girls_general).distinct() if show_girls else Program.objects.none()
        context["boys_stage_programs"] = boys_programs.filter(non_stage=False)
        context["boys_non_stage_programs"] = boys_programs.filter(non_stage=True)
        context['boys_programs'] = boys_programs
        context['girls_programs'] = girls_programs

        context["girls_stage_programs"] = girls_programs.filter(non_stage=False)
        context["girls_non_stage_programs"] = girls_programs.filter(non_stage=True)

        # forms (empty forms for GET). On a single-section fest the gender is
        # prefilled AND locked — participants can only belong to the active
        # section. A disabled control isn't submitted, so the template pairs
        # the locked select with a hidden input carrying the same value.
        student_initial = {}
        if madrasa:
            if madrasa.is_boys_only:
                student_initial["gender"] = "male"
            elif madrasa.is_girls_only:
                student_initial["gender"] = "female"
        bound_student_form = kwargs.get("student_form")
        if bound_student_form is not None:
            context["student_form"] = bound_student_form
        elif student_initial:
            student_form = StudentForm(initial=student_initial)
            student_form.fields["gender"].widget.attrs["disabled"] = True
            context["student_form"] = student_form
        else:
            context["student_form"] = StudentForm()
        context["program_form"] = kwargs.get("program_form") or ProgramForm()

        host_url = f"{self.request.scheme}://{self.request.get_host()}"
        context['category_url'] = f'{host_url}/program/categories?team={team_id}'

        user = self.request.user
        madrasa = user.madrasa
        context['meelad_fest_name'] = madrasa.meelad_fest_name if user.madrasa else None
        context["total_students"] = Student.objects.filter(team__madrasa=madrasa).count()
        categories = Category.objects.filter(madrasa=madrasa)
        context["total_programs"] = Program.objects.filter(Q(category__in=categories) | Q(madrasa=madrasa)).distinct().count()

        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()  # required for DetailView
        category = self.object
        team_id = _safe_team_id(request.GET.get("team"))
        team = None
        try:
            team = Team.objects.get(id=team_id) if team_id else None
        except (Team.DoesNotExist, ValueError):
            team = None

        if "student_form" in request.POST:
            student_form = StudentForm(request.POST, team=team)
            if student_form.is_valid():
                student = student_form.save(commit=False)
                student.category = category
                if team:
                    student.team = team
                student.save()
                url = reverse("category_detail", kwargs={"pk": category.pk})
                # Add query param
                if team_id:
                    url = f"{url}?team={team_id}"
                if _is_ajax(request):
                    return JsonResponse({
                        "ok": True,
                        "message": f"Student '{student.full_name}' added successfully.",
                        "redirect": url,
                        "student": {
                            "id": student.id,
                            "full_name": student.full_name,
                            "code_number": student.code_number,
                            "team_id": student.team_id,
                            "gender": student.gender,
                        },
                    })
                messages.success(request, f"Student '{student.full_name}' added successfully.")
                return redirect(url)
            else:
                errors = student_form.errors.as_text()
                if _is_ajax(request):
                    return JsonResponse({"ok": False, "error": errors}, status=400)
                context = self.get_context_data(student_form=student_form)
                context['errors'] = errors
                return self.render_to_response(context)

        elif "program_form" in request.POST:
            program_form = ProgramForm(request.POST)
            if program_form.is_valid():
                program = program_form.save(commit=False)
                program.save()
                messages.success(request, f"Program '{program.title}' added successfully.")
                gender = request.POST.get('gender')
                # Clamp the target section to the fest structure: on a
                # boys-only / girls-only fest a program can never be linked to
                # the other section's categories, even via a forged POST.
                madrasa = getattr(self.request.user, 'madrasa', None)
                if madrasa is not None and gender and gender not in madrasa.active_genders():
                    gender = madrasa.active_genders()[0]
                if not program.is_general:
                    if gender == 'male':
                        category.programs.add(program)
                    elif gender == 'female':
                        category.programs_for_girls.add(program)
                url = reverse("category_detail", kwargs={"pk": category.pk})
                # Add query param
                if team_id:
                    url = f"{url}?team={team_id}"
                if _is_ajax(request):
                    return JsonResponse({
                        "ok": True,
                        "message": f"Program '{program.title}' added successfully.",
                        "redirect": url,
                        "program": {
                            "id": program.id,
                            "title": program.title,
                            "description": program.description or "",
                            "is_general": program.is_general,
                            "non_stage": program.non_stage,
                            "section": program.section,
                        },
                    })
                messages.success(request, f"Program '{program.title}' added successfully.")
                return redirect(url)
            if _is_ajax(request):
                return JsonResponse(
                    {"ok": False, "error": program_form.errors.as_text()},
                    status=400)
            return self.render_to_response(
                self.get_context_data(program_form=program_form)
            )

        # fallback
        return self.get(request, *args, **kwargs)


@require_POST
@login_required
def delete_student(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    category_id = student.category_id
    team_id = student.team_id

    # Undo support: snapshot the row so the toast's Undo button can bring it
    # back (hard delete still happens — snapshots are additive only).
    trash = TrashItem.snapshot(
        student, request.user,
        student.team.madrasa if student.team else getattr(request.user, 'madrasa', None),
    )
    student.delete()
    trash.save()
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url:
        redirect_target = next_url
    else:
        redirect_target = reverse('category_detail', kwargs={'pk': category_id}) if category_id else reverse('program_list')
        if team_id:
            redirect_target = f"{redirect_target}?team={team_id}"

    if _is_ajax(request):
        return JsonResponse({
            "ok": True,
            "message": "Student deleted.",
            "redirect": redirect_target,
            "undo_url": reverse('restore_trash', kwargs={'trash_id': trash.pk}),
        })
    return redirect(redirect_target)


@require_POST
@login_required
def edit_student(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    madrasa = student.team.madrasa if student.team else getattr(request.user, 'madrasa', None)
    form = EditStudentForm(request.POST, instance=student, madrasa=madrasa)

    next_url = request.POST.get('next') or request.GET.get('next')

    if form.is_valid():
        edited = form.save()
        if not next_url:
            next_url = reverse('category_detail', kwargs={'pk': edited.category_id}) if edited.category_id else reverse('program_list')
            if edited.team_id:
                next_url = f"{next_url}?team={edited.team_id}"
        if _is_ajax(request):
            return JsonResponse({
                "ok": True,
                "message": f"Student '{edited.full_name}' updated successfully.",
                "redirect": next_url,
                "student": {
                    "id": edited.id,
                    "full_name": edited.full_name,
                    "code_number": edited.code_number,
                    "team_id": edited.team_id,
                    "gender": edited.gender,
                },
            })
        messages.success(request, f"Student '{edited.full_name}' updated successfully.")
        return redirect(next_url)

    if _is_ajax(request):
        return JsonResponse({"ok": False, "error": form.errors.as_text()}, status=400)
    messages.error(request, form.errors.as_text())
    if next_url:
        return redirect(next_url)

    redirect_target = reverse('category_detail', kwargs={'pk': student.category_id}) if student.category_id else reverse('program_list')
    if student.team_id:
        redirect_target = f"{redirect_target}?team={student.team_id}"
    return redirect(redirect_target)


@require_POST
@login_required
def delete_program(request, program_id):
    program = get_object_or_404(Program, id=program_id)

    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url:
        redirect_target = next_url
    else:
        redirect_target = reverse('program_list')

    # Guard: once a result (prize/position) has been added for a program it
    # must not be deletable — otherwise the result history & ranking break.
    if program.prize_set.exists():
        msg = (f'Cannot delete "{program.title}" — a result has already been added '
               'for this program. Remove the result first before deleting it.')
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": msg}, status=400)
        messages.error(request, msg)
        return redirect(redirect_target)

    # Guard for general programs: cannot delete once participants or results
    # have been recorded. (Every madrasa team is auto-added as a participating
    # team on creation, so mere team membership alone must not block deletion
    # of a still-empty program.)
    if program.is_general and (
        program.participants.exists() or program.prize_set.exists()
    ):
        msg = (f'Cannot delete "{program.title}" — participating teams have already '
               'been added. Remove the teams first before deleting it.')
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": msg}, status=400)
        messages.error(request, msg)
        return redirect(redirect_target)

    # Guard for group programs: cannot delete once groups/participants or
    # results have been added.
    if program.is_group and (
        program.participants.exists()
        or program.prize_set.filter(participants__isnull=False).exists()
    ):
        msg = (f'Cannot delete "{program.title}" — participants/groups have already '
               'been managed for this program. Remove them first before deleting it.')
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": msg}, status=400)
        messages.error(request, msg)
        return redirect(redirect_target)

    # Undo support: snapshot before the hard delete.
    program_trash = TrashItem.snapshot(program, request.user, program.madrasa)
    program.delete()
    program_trash.save()
    if _is_ajax(request):
        return JsonResponse({
            "ok": True,
            "message": "Program deleted.",
            "redirect": redirect_target,
            "undo_url": reverse('restore_trash', kwargs={'trash_id': program_trash.pk}),
        })
    return redirect(redirect_target)


@require_POST
@login_required
def restore_trash(request, trash_id):
    """Undo a delete: recreate the snapshotted object (student or program).

    Scoped to the logged-in user's madrasa and only within the retention
    window. On success the trash row is consumed so a second click cannot
    duplicate the object; a used/expired snapshot answers 410 with a toast
    message instead of an error page.
    """
    trash = get_object_or_404(TrashItem, id=trash_id)
    user_madrasa = getattr(request.user, 'madrasa', None)
    if not (request.user.is_superuser or trash.madrasa_id == getattr(user_madrasa, 'id', None)):
        return JsonResponse({"ok": False, "error": "Not allowed."}, status=403)

    next_url = request.POST.get('next') or request.GET.get('next')
    if not trash.is_restorable():
        msg = 'This delete is too old to undo (24 h window).'
        return JsonResponse({"ok": False, "error": msg, "redirect": next_url or reverse('home')},
                            status=410)

    try:
        with transaction.atomic():
            obj = trash.restore()
    except Exception:
        msg = f'Could not undo — “{trash.summary}” may conflict with existing data.'
        return JsonResponse({"ok": False, "error": msg, "redirect": next_url or reverse('home')},
                            status=409)

    trash.delete()
    kind = trash.model_name.lower()
    if not next_url:
        if kind == 'student':
            base = reverse('category_detail', kwargs={'pk': obj.category_id}) if obj.category_id else reverse('program_list')
            next_url = f'{base}?team={obj.team_id}' if obj.team_id else base
        else:
            next_url = reverse('program_list')
    return JsonResponse({
        "ok": True,
        "message": f'{kind.capitalize()} “{trash.summary}” restored.',
        "redirect": next_url,
    })


@login_required
def student_profile(request, student_id):
    """Full student profile (suggestion #2 of the V2 roadmap).

    Scoped to the logged-in madrasa (via team/category), shows registration
    history, achievements (individual + group/general via Prize.participants)
    and computed stats. Uses the initial letter as avatar — no photo field.
    """
    madrasa = request.user.madrasa
    student = get_object_or_404(
        Student.objects.select_related("team", "team__madrasa", "category"),
        pk=student_id,
    )
    # Madrasa scoping: a student belongs to a team (team -> madrasa) or at
    # least to a category of the fest. Anything else is not ours -> 404.
    ours = (
        (student.team and student.team.madrasa_id == madrasa.id)
        or (student.category and student.category.madrasa_id == madrasa.id)
    )
    if not ours:
        raise Http404("Student not found")

    # Programs the student is registered in (Program.participants M2M reverse).
    # Program has no category/team FK (category is M2M), so only cheap
    # select_related of the real FKs; per-row M2M access stays lazy.
    registered_programs = student.program_set.select_related(
        "venue", "madrasa"
    ).order_by("title")

    # Achievements: individual prizes (Prize.student FK) + group/general
    # participation prizes (Prize.participants M2M, related_name='prizes').
    prize_map = {}

    def _absorb(prize, kind):
        if prize.pk in prize_map:
            # The same group prize may list this student via both paths —
            # keep one entry per prize.
            prize_map[prize.pk]["kinds"].add(kind)
            return
        position = (
            prize.position or prize.grade or prize.group_program_position
            or prize.general_program_position
        )
        prize_map[prize.pk] = {
            "prize": prize,
            "kind": kind,
            "kinds": {kind},
            "position_name": getattr(position, "name", None),
            "mark": getattr(position, "mark", None),
        }

    for prize in Prize.objects.filter(student=student).select_related(
        "program", "position", "grade", "group_program_position",
        "general_program_position", "team",
    ):
        _absorb(prize, "individual")
    for prize in Prize.objects.filter(participants=student).select_related(
        "program", "position", "grade", "group_program_position",
        "general_program_position", "team",
    ):
        _absorb(prize, "group")

    achievements = sorted(
        prize_map.values(),
        key=lambda a: (
            {"first": 0, "second": 1, "third": 2}.get(a["position_name"] or "", 9),
            a["prize"].program.title.lower(),
        ),
    )
    wins = sum(
        1 for a in achievements
        if a["position_name"] in ("first", "second", "third")
    )

    section = {"male": "Boys", "female": "Girls"}.get(student.gender, "-")
    context = {
        "student": student,
        "section": section,
        "registered_programs": registered_programs,
        "achievements": achievements,
        "programs_count": registered_programs.count(),
        "wins_count": wins,
        "meelad_fest_name": madrasa.meelad_fest_name,
        "total_students": Student.objects.filter(team__madrasa=madrasa).count(),
    }
    return render(request, "program/student_profile.html", context)


class AddProgramToStudentView(View):
    def post(self, request, *args, **kwargs):
        student_id = self.kwargs.get("student_id")
        student = get_object_or_404(Student, id=student_id)

        program_ids = request.POST.getlist("programs")  # multi-select
        programs = Program.objects.filter(id__in=program_ids)

        # reset student programs
        student.program_set.set(programs)

        # Redirect back to the same page or student detail page
        team_id = student.team.id if student.team else None
        next_url = request.GET.get("next", reverse("category_detail", kwargs={"pk": student.category.pk}))

        if team_id:
            # append ?team=ID if no query params exist, otherwise add &team=ID
            connector = "&" if "?" in next_url else "?"
            next_url = f"{next_url}{connector}team={team_id}"

        if _is_ajax(request):
            return JsonResponse({
                "ok": True,
                "message": "Programs updated.",
                "redirect": next_url,
                "program_ids": [p.id for p in programs],
            })
        return redirect(next_url)


class StudentRegistrationView(generic.TemplateView):
    template_name = "program/program_registration.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        madrasa_id = self.request.GET.get('institution_id')
        if madrasa_id:
            madrasa = get_object_or_404(Madrasa, id=madrasa_id)
            context['madrasa'] = madrasa
            context['madrasa_name'] = madrasa.name
            context['fest_name'] = madrasa.meelad_fest_name
            context['fest_type'] = madrasa.fest_type
            context['is_boys_only'] = madrasa.is_boys_only
            context['is_girls_only'] = madrasa.is_girls_only
            context['is_both_sections'] = madrasa.is_both_sections
            # Schedule-ready consent: the registration link is disabled once a
            # coordinator confirms all programs/participation are final.
            context['registration_locked'] = madrasa.schedule_consent_confirmed
            program_rule = ProgramRule.objects.filter(madrasa_id=madrasa_id).last()
            if program_rule:
                context['max_programs'] = program_rule.max_program_per_head
            else:
                context['max_programs'] = 3
        else:
            context['madrasa_name'] = None
            context['registration_locked'] = False

        return context
    
    def get(self, request, *args, **kwargs):
        madrasa_id = self.request.GET.get('institution_id')
        program_rule = ProgramRule.objects.filter(madrasa_id=madrasa_id).last()
        if program_rule and not program_rule.program_reg_link_active:
            return HttpResponse("Link expired!")
        return super().get(request, *args, **kwargs)


class ProgramListView(generic.ListView):
    template_name = 'program/program_list.html'
    context_object_name = 'stage_programs'

    def get_queryset(self):
        # The program list is scoped to the logged-in user's madrasa AND the
        # fest's active section(s): other institutions' programs and the
        # inactive section's programs must never be listed here.
        madrasa = getattr(self.request.user, 'madrasa', None)
        if not madrasa:
            return Program.objects.none()
        return Program.objects.filter(
            non_stage=False, madrasa=madrasa
        ).filter(
            program_section_q(madrasa, _fest_section(madrasa))
        ).distinct()

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        request = self.request
        madrasa = getattr(request.user, 'madrasa', None)
        madrasa_id = madrasa.id if madrasa else None
        if madrasa:
            section_q = program_section_q(madrasa, _fest_section(madrasa))
            context['non_stage_programs'] = Program.objects.filter(
                non_stage=True, madrasa=madrasa
            ).filter(section_q).distinct()
        else:
            context['non_stage_programs'] = Program.objects.none()
        context['categories'] = Category.objects.filter(madrasa_id=madrasa_id)

        try:
            categories = Category.objects.filter(madrasa_id=madrasa_id)
            context["total_students"] = Student.objects.filter(team__madrasa_id=madrasa_id).count()
            context["total_programs"] = Program.objects.filter(Q(category__in=categories) | Q(madrasa_id=madrasa_id)).distinct().count()
            context['meelad_fest_name'] = Madrasa.objects.get(id=madrasa_id).meelad_fest_name
        except Exception:
            pass


        host_url = f"{request.scheme}://{request.get_host()}"
        context["form_url"] = f'{host_url}/program/student-registration/?institution_id={madrasa_id}'

        # Only offer the "Copy Registration Form Link" action while the
        # program registration link is active (program_reg_link_active).
        context['reg_link_active'] = False
        rule = ProgramRule.objects.filter(madrasa_id=madrasa_id).last()
        if rule:
            context['reg_link_active'] = rule.program_reg_link_active

        # Fest section structure flags so the Boys/Girls tabs collapse when the
        # fest runs a single section (also available via context processor).
        madrasa_obj = request.user.madrasa
        if madrasa_obj:
            context['fest_type'] = madrasa_obj.fest_type
            context['is_boys_only'] = madrasa_obj.is_boys_only
            context['is_girls_only'] = madrasa_obj.is_girls_only
            context['is_both_sections'] = madrasa_obj.is_both_sections

        return context


def program_participants_json(request, pk):
    program = get_object_or_404(Program, pk=pk)
    participants = program.participants.select_related("team").all()
    winners = program.prize_set.all()
    winners_list = [
        {
            "position": winner.position.get_name_display(),
            "participant_id": winner.student.id,
            "code_number": winner.student.code_number,
            "full_name": winner.student.full_name,
            "team": winner.student.team.name,
        }
        for winner in winners
    ]
    order_map = {
        "First": 1,
        "Second": 2,
        "Third": 3,
        "Grade A": 4,
        "Grade B": 5,
    }
    winners_list.sort(key=lambda w: order_map.get(w["position"], 99))

    data = {
        "program": program.title,
        "participants": [
            {
                "id": p.id,
                "full_name": p.full_name,
                "code_number": p.code_number,
                "chest_number": "",   # if you have it
                "mark1": "",
                "mark2": "",
                "remarks": "",
                "team": p.team.name
            }
            for p in participants
        ],
        "winners": winners_list
    }
    return JsonResponse(data)


# def program_judge_slip_pdf(request, pk):
#     program = get_object_or_404(Program, pk=pk)
#     participants = program.participants.all()
#
#     response = HttpResponse(content_type="application/pdf")
#     response['Content-Disposition'] = f'attachment; filename="{program.slug}_participants.pdf"'
#
#     doc = SimpleDocTemplate(response, pagesize=A4)
#     elements = []
#     styles = getSampleStyleSheet()
#
#     elements.append(Paragraph(f"{program.title} Slip", styles['Heading1']))
#     elements.append(Spacer(1, 12))
#
#     data = [["Sl. No", "Code Number", "Chest Number", "Mark1", "Mark2", "Remarks"]]
#     for i, p in enumerate(participants, start=1):
#         data.append([i, "", "", "", "", ""])
#
#     table = Table(data, colWidths=[40, 80, 80, 60, 60, 160])
#     table.setStyle(TableStyle([
#         ("GRID", (0,0), (-1,-1), 0.5, colors.black),
#         ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
#         ("ALIGN", (0,0), (-1,-1), "CENTER"),
#         ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
#     ]))
#     elements.append(table)
#
#     doc.build(elements)
#     return response




def program_judge_slip_pdf(request, pk, category_id):
    category = Category.objects.get(id=category_id)
    program = get_object_or_404(Program, pk=pk)
    participants = program.participants.all()

    response = HttpResponse(content_type="application/pdf")
    response['Content-Disposition'] = f'attachment; filename="{program.slug}_participants.pdf"'

    doc = SimpleDocTemplate(response, pagesize=landscape(A4),
                            leftMargin=20, rightMargin=20, topMargin=20, bottomMargin=20)
    elements = []
    styles = getSampleStyleSheet()

    # -----------------------------
    # First Table:  with Code Number
    # -----------------------------
    heading1 = Paragraph(f"{program.title} - {category.name}", styles['Heading3'])
    data1 = [["Sl. No", "Code No.", "Chest No.", "Mark1", "Mark2", "Remarks"]]
    for i, p in enumerate(participants, start=1):
        data1.append([i, p.code_number or "", "", "", "", ""])

    table1 = Table(data1, colWidths=[35, 60, 60, 50, 50, 125])
    table1.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.black),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
    ]))

    # -----------------------------
    # Second Table: Judge Slip without Code Number (also include header)
    # -----------------------------
    heading2 = Paragraph(f"Judge Slip: {program.title} - {category.name}", styles['Heading3'])
    data2 = [["Sl. No", "Code No.", "Chest No.", "Mark1", "Mark2", "Remarks"]]
    for i, p in enumerate(participants, start=1):
        data2.append([i, "", "", "", "", ""])

    table2 = Table(data2, colWidths=[35, 60, 60, 50, 50, 125])
    table2.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.black),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
    ]))

    # -----------------------------
    # Combine both tables horizontally using parent table
    # -----------------------------
    combined_table = Table(
        [
            [[heading1, Spacer(1,12), table1], [heading2, Spacer(1,12), table2]]
        ],
        colWidths=[doc.width/2.0]*2
    )
    combined_table.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))

    elements.append(combined_table)
    doc.build(elements)
    return response


def download_participants_pdf(request, program_id, section, category_id):
    program = Program.objects.get(id=program_id)
    category = Category.objects.get(id=category_id)
    participants = program.participants.all().select_related('team')

    # Http response with PDF headers
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="participants_{section}.pdf"'

    # Create PDF document
    doc = SimpleDocTemplate(response, pagesize=A4,
                            rightMargin=30, leftMargin=30,
                            topMargin=30, bottomMargin=30)

    elements = []
    styles = getSampleStyleSheet()

    # Title
    title_text = f"{program.title} - {category.name} - ({section.title()})"
    title_style = ParagraphStyle(
        name="Title",
        parent=styles["Heading1"],
        alignment=1,  # center
        spaceAfter=20
    )
    elements.append(Paragraph(title_text, title_style))
    elements.append(Spacer(1, 12))

    # Table header
    data = [["Sl. No", "Code Number", "Full Name", "Team Name"]]

    # Fill rows
    for i, p in enumerate(participants, start=1):
        data.append([
            str(i),
            p.code_number or "-",
            p.full_name,
            p.team.name if p.team else "-"
        ])

    # Create table
    table = Table(data, colWidths=[50, 120, 200, 120])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#4F46E5")),  # Indigo header
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),

        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
    ]))

    elements.append(table)

    # Build PDF
    doc.build(elements)

    return response




# The poster template shows the fest logo at 320px width inside a 1200px poster
# rendered at 2x scale (i.e. ~640px retina). Embedding the user's original logo
# (often a multi-MB high-res photo/PNG) makes the poster's base64 data URI huge,
# which bloats the HTML and slows headless-Chrome rendering. Cap it so the logo
# stays crisp on the poster while the embedded payload shrinks by an order of
# magnitude or more.
_LOGO_MAX_WIDTH = 640


def _optimize_fest_logo_bytes(raw, original_name):
    """Resize + re-encode a festival logo for embedding in the poster HTML.

    Returns ``(bytes, mime_type)`` or ``(raw, None)`` on failure so the caller can
    fall back to the original bytes and a guessed MIME type.
    """
    mime = mimetypes.guess_type(original_name)[0] or 'image/png'
    try:
        img = PILImage.open(BytesIO(raw))
        if getattr(img, 'is_animated', False):
            img.seek(0)
        # Flatten to a single RGBA layer so downscaling is reliable.
        img = img.convert('RGBA')
        if img.width > _LOGO_MAX_WIDTH:
            ratio = _LOGO_MAX_WIDTH / float(img.width)
            img = img.resize(
                (_LOGO_MAX_WIDTH, max(1, round(img.height * ratio))),
                PILImage.Resampling.LANCZOS,
            )
        out = BytesIO()
        img.save(out, format='PNG', optimize=True)
        return out.getvalue(), 'image/png'
    except Exception:
        return raw, mime


def _fest_logo_data_uri(madrasa):
    """Return the madrasa's ``fest_logo`` as a compact ``data:`` URI, or None.

    Fills the poster template's ``POSTER_DATA.logo`` field so the
    ``<img class="fest-logo">`` shows the madrasa's own fest logo (downscaled and
    re-encoded to keep the HTML small).  When the madrasa has no ``fest_logo``
    uploaded (or the file is missing on disk), None is returned and the template
    falls back to its built-in fest logo.
    """
    fest_logo = getattr(madrasa, 'fest_logo', None)
    if not fest_logo:
        return None
    try:
        if not fest_logo.storage.exists(fest_logo.name):
            return None
        with fest_logo.open('rb') as fh:
            raw = fh.read()
    except Exception:
        return None
    data, mime = _optimize_fest_logo_bytes(raw, fest_logo.name)
    encoded = base64.b64encode(data).decode('ascii')
    return f"data:{mime};base64,{encoded}"


# ---------------------------------------------------------------------------
# Result-poster disk cache
# ---------------------------------------------------------------------------
# Rendering the poster launches a fresh headless Chrome process (a few seconds).
# Posters rarely change for the same program + section + logo, so we cache the
# finished JPEG on disk under MEDIA_ROOT/poster_cache keyed by a hash of the fully
# resolved HTML. Any change to the winners / fest name / logo / template produces
# a new HTML → new hash → new cache file, so the cache is always consistent and
# auto-invalidates whenever data changes (no manual invalidation needed).
_POSTER_CACHE_DIR = 'poster_cache'
_POSTER_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days


def _poster_cache_root():
    root = Path(settings.MEDIA_ROOT) / _POSTER_CACHE_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _poster_cache_path(html):
    digest = hashlib.sha1(html.encode('utf-8')).hexdigest()[:20]
    return _poster_cache_root() / f"poster_{digest}.jpg"


def _poster_cached(html):
    """Return cached JPEG bytes for the given HTML, or None on a miss."""
    path = _poster_cache_path(html)
    if not path.is_file():
        return None
    try:
        return path.read_bytes()
    except Exception:
        return None


def _store_poster_cache(html, jpeg_bytes):
    """Atomically persist a rendered poster; best-effort prune stale files."""
    root = _poster_cache_root()
    dest = _poster_cache_path(html)
    tmp = root / f"tmp_{dest.name}"
    try:
        tmp.write_bytes(jpeg_bytes)
        os.replace(tmp, dest)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
    # Keep the cache directory from growing without bound.
    try:
        cutoff = time.time() - _POSTER_CACHE_TTL_SECONDS
        for f in root.glob('poster_*.jpg'):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass


def _poster_template_path():
    """Return the on-disk path of the approved poster template.

    The template lives under ``staticfiles/poster_templates`` which is
    registered in ``STATICFILES_DIRS``.  Rather than hard-coding
    ``BASE_DIR/'staticfiles'`` (which is not reliable once ``collectstatic``
    deploys to ``STATIC_ROOT`` in production), it is located through Django's
    static-files finders, with a fallback that scans the configured static
    directories directly.
    """
    relative = 'poster_templates/meelad_result_poster_template.html'
    path = finders.find(relative)
    if path:
        return Path(path)

    candidates = list(getattr(settings, 'STATICFILES_DIRS', ()))
    if getattr(settings, 'STATIC_ROOT', None):
        candidates.append(settings.STATIC_ROOT)
    for root in candidates:
        candidate = Path(root) / relative
        if candidate.is_file():
            return candidate

    raise Http404(f"Poster template not found: {relative}")


def _find_chrome_binary():
    """Locate a Chrome/Chromium binary used for headless poster rendering."""
    for candidate in (
        shutil.which('google-chrome'),
        shutil.which('google-chrome-stable'),
        shutil.which('chromium'),
        shutil.which('chromium-browser'),
        shutil.which('chrome'),
        shutil.which('google-chrome-beta'),
    ):
        if candidate:
            return candidate
    return '/usr/bin/google-chrome'


def _poster_section(program, madrasa):
    """Pick the poster ``section`` ('boys' / 'girls') for a program.

    Individual/group programs are linked to a category either through
    ``category_set`` (boys section) or ``girls_categories`` (girls section).
    General programs are team-wise and usually have no category link, so they
    fall back to 'boys' (the poster simply prints a dash for the category).
    """
    if program.category_set.filter(madrasa=madrasa).exists():
        return 'boys'
    if program.girls_categories.filter(madrasa=madrasa).exists():
        return 'girls'
    return 'boys'


def _poster_error(message, status=500):
    """JSON error payload so the results page can toast the failure reason."""
    return JsonResponse({'message': 'error', 'details': message}, status=status)


def download_results_poster_image(request, program_id, section):
    """Result poster downloaded as a JPEG image (rendered from the approved
    poster template in ``staticfiles/poster_templates``).

    The template is a self-contained 1200x1200px HTML page that paints the
    poster from its ``POSTER_DATA`` JavaScript object.  This view loads that
    file, swaps in the real winners / program / madrasa values — including the
    madrasa's ``fest_logo`` as a data URI (the template's built-in fest logo is
    kept as the default when no logo is uploaded) — renders it with headless
    Chrome and returns the screenshot as an attachment JPEG.
    """
    program = get_object_or_404(Program, id=program_id)
    madrasa = request.user.madrasa

    # Posters are a published-results feature: block downloads until the
    # result is published (the UI hides the button; this enforces it).
    if not program.is_result_published:
        return _poster_error(
            'Publish this result before downloading its poster.', status=403
        )

    # Determine category (boys -> category_set, girls -> girls_categories)
    if section == 'boys':
        category = program.category_set.filter(madrasa=madrasa).first()
    else:
        category = program.girls_categories.filter(madrasa=madrasa).first()
    category_name = category.name if category else "-"

    # Collect prizes and map them to first / second / third positions.
    prizes = Prize.objects.filter(program=program).select_related(
        'student__team', 'team', 'position', 'grade',
        'group_program_position', 'general_program_position',
    )

    positions = {'first': None, 'second': None, 'third': None}
    for prize in prizes:
        pos_name = None
        if program.is_general and prize.general_program_position:
            pos_name = prize.general_program_position.name
        elif program.is_group and prize.group_program_position:
            pos_name = prize.group_program_position.name
        elif prize.position:
            pos_name = prize.position.name

        if pos_name not in positions:
            continue

        if prize.student:
            winner_name = prize.student.full_name
            winner_team = prize.student.team.name if prize.student.team else ""
        elif prize.team:
            # Group prizes are won by the team; list the group's member names
            # joined with "&" so the winning group is recognisable.
            if program.is_group and prize.group_program_position:
                winner_name = " & ".join(
                    prize.participants.order_by('id').values_list('full_name', flat=True)
                )
                winner_team = prize.team.name
            else:
                winner_name = ""
                winner_team = prize.team.name
        else:
            continue
        positions[pos_name] = (winner_name, winner_team)

    # The template always draws three winner cards (01/02/03). A missing
    # position simply leaves that card's name/team blank.
    winners = []
    for i, key in enumerate(('first', 'second', 'third'), start=1):
        entry = positions.get(key)
        if entry:
            name, team = entry
            # Team-wise prizes (group / general) have no student name.
            if not name and team:
                name, team = team, ""
            winners.append({'rank': f"{i:02d}", 'name': name, 'team': team, 'extra': ""})
        else:
            winners.append({'rank': f"{i:02d}", 'name': "", 'team': "", 'extra': ""})

    fest = madrasa.meelad_fest_name or "Meelad Fest"
    message = (
        "With immense joy and pride, we extend our heartiest congratulations to "
        f"all the brilliant winners of the {fest}. Your achievement is not merely "
        "a prize or a position\u2014it is a reflection of your dedication, hard "
        "work, talent, discipline, and sincere effort. Every moment you spent "
        "preparing, every challenge you faced, and every step you took towards "
        "excellence has brought you to this beautiful moment of success."
    )

    # The footer prints the madrasa's name (organization_name) followed by the
    # madrasa's committee name (organization_sub).  The previous sadr/convenor
    # display has been superseded by the committee_name field.
    committee = madrasa.committee_name or ""

    poster_data = {
        'result_number': '01',
        'logo': _fest_logo_data_uri(madrasa),
        'section': f"{category_name.upper()} ({section.upper()})",
        'category': category_name,
        'program_name': program.title.upper(),
        'program_code': "",
        'winners': winners,
        'message': message,
        'organization_name': madrasa.name.upper(),
        'organization_sub': committee.upper(),
    }

    # Load the approved poster template (located dynamically via the static
    # files finders) and swap in the real data.
    try:
        html = _poster_template_path().read_text(encoding='utf-8')
    except OSError:
        return _poster_error('Poster template file could not be loaded on the server.')

    html, replaced = re.subn(
        r'const POSTER_DATA\s*=\s*\{.*?\};',
        lambda _m: 'const POSTER_DATA = ' + json.dumps(poster_data) + ';',
        html, count=1, flags=re.DOTALL,
    )
    if not replaced:
        return _poster_error('Poster template is missing the POSTER_DATA block.')

    # Remove body padding so the 1200x1200 poster fills the viewport exactly.
    html = html.replace(
        '</head>',
        '<style>html,body{background:#fff}body{padding:0!important}</style></head>',
    )

    # Force refresh: when requested (e.g. after a result edit), skip both the
    # on-disk poster cache and the browser/ISP cache so a fresh poster is always
    # rendered and served.
    force = request.GET.get('force') == '1'

    # Fast path: serve an already-rendered poster for this exact HTML content
    # (same program, fest name, committee and logo) without relaunching Chrome.
    # This is safe because the cache key is a hash of the fully-resolved HTML —
    # any data change yields a different key automatically. The fast path is
    # skipped entirely when a forced refresh is requested.
    if not force:
        cached = _poster_cached(html)
        if cached is not None:
            return _poster_response(cached, program, section)

    chrome = _find_chrome_binary()

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            html_file = tmp / 'poster.html'
            png_file = tmp / 'poster.png'
            html_file.write_text(html, encoding='utf-8')

            subprocess.run(
                [
                    chrome, '--headless=new', '--disable-gpu', '--no-sandbox',
                    '--hide-scrollbars', '--force-device-scale-factor=2',
                    '--window-size=1200,1200', '--virtual-time-budget=1500',
                    '--disable-extensions', '--disable-component-update',
                    '--disable-background-networking', '--disable-sync',
                    f'--screenshot={png_file}',
                    html_file.as_uri(),
                ],
                check=True, capture_output=True, timeout=60,
            )

            image = PILImage.open(png_file).convert('RGB')
            jpeg_buffer = BytesIO()
            image.save(jpeg_buffer, format='JPEG', quality=92)
            jpeg_bytes = jpeg_buffer.getvalue()
    except subprocess.TimeoutExpired:
        return _poster_error('Poster rendering timed out. Please try again.')
    except FileNotFoundError:
        return _poster_error(
            'Poster rendering is unavailable: headless Chrome was not found on the server.'
        )
    except subprocess.CalledProcessError as exc:
        detail = ''
        if exc.stderr:
            detail = exc.stderr.decode(errors='replace').strip().splitlines()[:1]
            detail = f' ({detail[0][:160]})' if detail else ''
        return _poster_error(f'Poster rendering failed on the server{detail}. Please try again.')
    except OSError as exc:
        return _poster_error(f'Poster rendering failed: {exc}')

    # Persist for future requests (best-effort; TTL-pruned later).
    if jpeg_bytes:
        _store_poster_cache(html, jpeg_bytes)

    response = _poster_response(jpeg_bytes, program, section)
    if force:
        # A forced refresh must reach the client without being cached anywhere,
        # otherwise the stale image would be served again on the next download.
        response['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response['Pragma'] = 'no-cache'
    return response


def _poster_response(jpeg_bytes, program, section):
    """Build the attachment download response for a rendered poster."""
    response = HttpResponse(jpeg_bytes, content_type='image/jpeg')
    response['Content-Disposition'] = (
        f'attachment; filename="poster_{program.slug}_{section}.jpg"'
    )
    # Posters rarely change for the same content — let browsers/ISPs/browsers cache
    # so repeat downloads are fast even before the disk cache path is hit.
    response['Cache-Control'] = 'private, max-age=3600'
    return response


def _resolve_program_madrasa(program, request):
    """Return the madrasa that owns ``program``.

    Position/Grade/GroupPosition/GeneralPosition marks are configured per
    madrasa, so prize saving must use the marks of the madrasa the program
    belongs to — not necessarily the logged-in user's madrasa.

    Resolution order:
      1. The program's own ``madrasa`` FK (set for every program created after
         the madrasa-ownership change — general programs rely on this).
      2. The madrasa of the program's first category (normal/group programs).
      3. The madrasa of the program's first general team (general programs).
      4. The logged-in user's madrasa, as a last-resort fallback.
    """
    if getattr(program, 'madrasa_id', None):
        return program.madrasa

    category = program.category_set.first() or program.girls_categories.first()
    if category is not None and category.madrasa is not None:
        return category.madrasa

    team = program.general_teams.first()
    if team is not None and team.madrasa is not None:
        return team.madrasa

    return getattr(request.user, 'madrasa', None)


@require_POST
@transaction.atomic
def save_prize(request, program_id):

    """
    Mark update manual: For independant programs, the score will be updated for that contestant, 
    if program is general or group, the score will be updated for the team of that contestant.
    """

    program = get_object_or_404(Program, id=program_id)

    # Resolve the madrasa from the program itself so the position/grade
    # records (which are scoped per madrasa) are always the ones configured for
    # the madrasa that owns this program, not necessarily the logged-in user's.
    madrasa = _resolve_program_madrasa(program, request)

    # Data from request.POST
    data = json.loads(request.body.decode("utf-8"))
    first_prize_id = data.get("first")
    second_prize_id = data.get("second")
    third_prize_id = data.get("third")
    gradeA_id = data.get("gradeA")
    gradeB_id = data.get("gradeB")
    gradeC_id = data.get("gradeC")
    remarks = data.get("remarks", "")

    created_prizes = []

    # A single participant cannot win more than one position (1st/2nd/3rd) in
    # the result of the same program. Reject duplicate selections before any
    # prizes are created/updated. This guard applies to individual, general and
    # group programs handled by this view.
    position_ids = [pid for pid in (first_prize_id, second_prize_id, third_prize_id) if pid]
    if len(position_ids) != len(set(position_ids)):
        return JsonResponse({
            "message": "error",
            "details": "Same participant cannot be selected for more than one position (1st/2nd/3rd).",
        })

    # A single participant cannot win more than one grade (A/B/C) in the result
    # of the same program, just like positions. Grades only apply to individual
    # programs, but the guard is placed centrally and is a no-op when no grades
    # are submitted (general / group programs).
    grade_ids = [gid for gid in (gradeA_id, gradeB_id, gradeC_id) if gid]
    if len(grade_ids) != len(set(grade_ids)):
        return JsonResponse({
            "message": "error",
            "details": "Same participant cannot be selected for more than one grade (A/B/C).",
        })

    # no grade option for general and group programs
    if program.is_general:
        if first_prize_id:
            student = get_object_or_404(Student, id=first_prize_id)
            team = student.team
            general_first_score, _ = GeneralPosition.objects.get_or_create(name='first', madrasa=madrasa)

            if Prize.objects.filter(team=team, program=program, general_program_position__name='first').exclude(team=team).exists():
                Prize.objects.filter(team=team, program=program, general_program_position__name='first').exclude(team=team).delete()

            prize, _ = Prize.objects.update_or_create(
                team=team, program=program,
                defaults={"general_program_position": general_first_score, "remarks": remarks}
            )
            created_prizes.append(prize.id)
        elif not first_prize_id:
            Prize.objects.filter(team=team, program=program, general_program_position__name='first').delete()

        if second_prize_id:
            student = get_object_or_404(Student, id=second_prize_id)
            team = student.team
            general_sec_score = GeneralPosition.objects.get_or_create(name='second', madrasa=madrasa)

            if Prize.objects.filter(team=team, program=program, general_program_position__name='second').exclude(team=team).exists():
                Prize.objects.filter(team=team, program=program, general_program_position__name='second').exclude(team=team).delete()

            prize, _ = Prize.objects.update_or_create(
                team=team, program=program,
                defaults={"general_program_position": general_sec_score, "remarks": remarks}
            )
            created_prizes.append(prize.id)
        elif not second_prize_id:
            Prize.objects.filter(team=team, program=program, general_program_position__name='second').delete()

        if third_prize_id:
            student = get_object_or_404(Student, id=third_prize_id)
            team = student.team
            general_third_score = GeneralPosition.objects.get_or_create(name='third', madrasa=madrasa)

            if Prize.objects.filter(team=team, program=program, general_program_position__name='third').exclude(team=team).exists():
                Prize.objects.filter(team=team, program=program, general_program_position__name='third').exclude(team=team).delete()

            prize, _ = Prize.objects.update_or_create(
                team=team, program=program,
                defaults={"general_program_position": general_third_score, "remarks": remarks}
            )
            created_prizes.append(prize.id)
        elif not third_prize_id:
            Prize.objects.filter(team=team, program=program, general_program_position__name='third').delete()

        return JsonResponse({"message": "success", "created_prizes": created_prizes})

    elif program.is_group:
        if first_prize_id:
            student = get_object_or_404(Student, id=first_prize_id)
            team = student.team
            group_first_score, _ = GroupPosition.objects.get_or_create(name='first', madrasa=madrasa)
            prize, _ = Prize.objects.update_or_create(
                team=team, program=program,
                defaults={"group_program_position": group_first_score, "remarks": remarks}
            )
            created_prizes.append(prize.id)
        elif not first_prize_id:
            Prize.objects.filter(team=team, program=program, group_program_position__name='first').delete()

        if second_prize_id:
            student = get_object_or_404(Student, id=first_prize_id)
            team = student.team
            group_second_score, _ = GroupPosition.objects.get_or_create(name='second', madrasa=madrasa)
            prize, _ = Prize.objects.update_or_create(
                team=team, program=program,
                defaults={"group_program_position": group_second_score, "remarks": remarks}
            )
            created_prizes.append(prize.id)
        elif not second_prize_id:
            Prize.objects.filter(team=team, program=program, group_program_position__name='second').delete()
            
        if third_prize_id:
            student = get_object_or_404(Student, id=first_prize_id)
            team = student.team
            group_third_score, _ = GroupPosition.objects.get_or_create(name='third', madrasa=madrasa)
            prize, _ = Prize.objects.update_or_create(
                team=team, program=program,
                defaults={"group_program_position": group_third_score, "remarks": remarks}
            )
            created_prizes.append(prize.id)
        elif not third_prize_id:
            Prize.objects.filter(team=team, program=program, group_program_position__name='third').delete()

        return JsonResponse({"message": "success", "created_prizes": created_prizes})

    else:
        # for single progrms:

        # ---------------------------------------------------------
        # Track all students whose total_point may have changed.
        # This includes both old students and newly selected students.
        # ---------------------------------------------------------
        affected_student_ids = set()

        # Get students who already have prizes for this program.
        existing_student_ids = set(
            Prize.objects.filter(program=program)
            .values_list("student_id", flat=True)
        )

        affected_student_ids.update(existing_student_ids)

        # =========================================================
        # SINGLE PROGRAMS - POSITIONS
        # =========================================================

        if first_prize_id:
            student = get_object_or_404(Student, id=first_prize_id)
            affected_student_ids.add(student.id)

            pos, _ = Position.objects.get_or_create(name="first", madrasa=madrasa)

            # Remove previous first-prize winner if different
            old_prizes = Prize.objects.filter(
                program=program,
                position__name="first"
            ).exclude(student=student)

            affected_student_ids.update(
                old_prizes.values_list("student_id", flat=True)
            )

            old_prizes.delete()

            # Create/update first prize
            prize, _ = Prize.objects.update_or_create(
                student=student,
                program=program,
                defaults={
                    "position": pos,
                    "remarks": remarks,
                }
            )

            created_prizes.append(prize.id)

        else:
            # No first prize assigned -> remove existing one
            old_prizes = Prize.objects.filter(
                program=program,
                position__name="first"
            )

            affected_student_ids.update(
                old_prizes.values_list("student_id", flat=True)
            )

            old_prizes.delete()

        # ---------------------------------------------------------

        if second_prize_id:
            student = get_object_or_404(Student, id=second_prize_id)
            affected_student_ids.add(student.id)

            pos, _ = Position.objects.get_or_create(name="second", madrasa=madrasa)

            # Remove previous second-prize winner if different
            old_prizes = Prize.objects.filter(
                program=program,
                position__name="second"
            ).exclude(student=student)

            affected_student_ids.update(
                old_prizes.values_list("student_id", flat=True)
            )

            old_prizes.delete()

            # Create/update second prize
            prize, _ = Prize.objects.update_or_create(
                student=student,
                program=program,
                defaults={
                    "position": pos,
                    "remarks": remarks,
                }
            )

            created_prizes.append(prize.id)

        else:
            # No second prize assigned -> remove existing one
            old_prizes = Prize.objects.filter(
                program=program,
                position__name="second"
            )

            affected_student_ids.update(
                old_prizes.values_list("student_id", flat=True)
            )

            old_prizes.delete()

        # ---------------------------------------------------------

        if third_prize_id:
            student = get_object_or_404(Student, id=third_prize_id)
            affected_student_ids.add(student.id)

            pos, _ = Position.objects.get_or_create(name="third", madrasa=madrasa)

            # Remove previous third-prize winner if different
            old_prizes = Prize.objects.filter(
                program=program,
                position__name="third"
            ).exclude(student=student)

            affected_student_ids.update(
                old_prizes.values_list("student_id", flat=True)
            )

            old_prizes.delete()

            # Create/update third prize
            prize, _ = Prize.objects.update_or_create(
                student=student,
                program=program,
                defaults={
                    "position": pos,
                    "remarks": remarks,
                }
            )

            created_prizes.append(prize.id)

        else:
            # No third prize assigned -> remove existing one
            old_prizes = Prize.objects.filter(
                program=program,
                position__name="third"
            )

            affected_student_ids.update(
                old_prizes.values_list("student_id", flat=True)
            )

            old_prizes.delete()

        # =========================================================
        # GRADES
        # =========================================================

        if gradeA_id:
            student = get_object_or_404(Student, id=gradeA_id)
            affected_student_ids.add(student.id)

            grade = get_object_or_404(Grade, name="a_grade", madrasa=madrasa)

            # Remove previous A-grade winner if different
            old_prizes = Prize.objects.filter(
                program=program,
                grade__name="a_grade"
            ).exclude(student=student)

            affected_student_ids.update(
                old_prizes.values_list("student_id", flat=True)
            )

            old_prizes.delete()

            # Create/update A grade
            prize, _ = Prize.objects.update_or_create(
                student=student,
                program=program,
                defaults={
                    "grade": grade,
                    "remarks": remarks,
                }
            )

            created_prizes.append(prize.id)

        else:
            # No A grade assigned -> remove existing one
            old_prizes = Prize.objects.filter(
                program=program,
                grade__name="a_grade"
            )

            affected_student_ids.update(
                old_prizes.values_list("student_id", flat=True)
            )

            old_prizes.delete()

        # ---------------------------------------------------------

        if gradeB_id:
            student = get_object_or_404(Student, id=gradeB_id)
            affected_student_ids.add(student.id)

            grade = get_object_or_404(Grade, name="b_grade", madrasa=madrasa)

            # Remove previous B-grade winner if different
            old_prizes = Prize.objects.filter(
                program=program,
                grade__name="b_grade"
            ).exclude(student=student)

            affected_student_ids.update(
                old_prizes.values_list("student_id", flat=True)
            )

            old_prizes.delete()

            # Create/update B grade
            prize, _ = Prize.objects.update_or_create(
                student=student,
                program=program,
                defaults={
                    "grade": grade,
                    "remarks": remarks,
                }
            )

            created_prizes.append(prize.id)

        else:
            # No B grade assigned -> remove existing one
            old_prizes = Prize.objects.filter(
                program=program,
                grade__name="b_grade"
            )

            affected_student_ids.update(
                old_prizes.values_list("student_id", flat=True)
            )

            old_prizes.delete()

        # ---------------------------------------------------------

        if gradeC_id:
            student = get_object_or_404(Student, id=gradeC_id)
            affected_student_ids.add(student.id)

            grade = get_object_or_404(Grade, name="c_grade", madrasa=madrasa)

            # Remove previous C-grade winner if different
            old_prizes = Prize.objects.filter(
                program=program,
                grade__name="c_grade"
            ).exclude(student=student)

            affected_student_ids.update(
                old_prizes.values_list("student_id", flat=True)
            )

            old_prizes.delete()

            # Create/update C grade
            prize, _ = Prize.objects.update_or_create(
                student=student,
                program=program,
                defaults={
                    "grade": grade,
                    "remarks": remarks,
                }
            )

            created_prizes.append(prize.id)

        else:
            # No C grade assigned -> remove existing one
            old_prizes = Prize.objects.filter(
                program=program,
                grade__name="c_grade"
            )

            affected_student_ids.update(
                old_prizes.values_list("student_id", flat=True)
            )

            old_prizes.delete()

        # =========================================================
        # RECALCULATE STUDENT TOTAL POINTS
        # =========================================================
        #
        # IMPORTANT:
        # Do NOT do:
        #
        #     student.total_point += pos.mark
        #
        # because that causes points to be added again when editing.
        #
        # Instead, calculate the total from the actual Prize records.
        # =========================================================

        for student_id in affected_student_ids:

            totals = Prize.objects.filter(
                student_id=student_id
            ).aggregate(
                position_total=Coalesce(
                    Sum("position__mark"),
                    Value(0.0),
                    output_field=FloatField(),
                ),
                grade_total=Coalesce(
                    Sum("grade__mark"),
                    Value(0.0),
                    output_field=FloatField(),
                ),
                group_total=Coalesce(
                    Sum("group_program_position__mark"),
                    Value(0.0),
                    output_field=FloatField(),
                ),
                general_total=Coalesce(
                    Sum("general_program_position__mark"),
                    Value(0.0),
                    output_field=FloatField(),
                ),
            )

            total_point = (
                totals["position_total"]
                + totals["grade_total"]
                + totals["group_total"]
                + totals["general_total"]
            )

            Student.objects.filter(
                id=student_id
            ).update(
                total_point=total_point
            )



    # else:
    #     # for single programs
    #     if first_prize_id:
    #         student = get_object_or_404(Student, id=first_prize_id)
    #         pos, _ = Position.objects.get_or_create(name="first")

    #         if Prize.objects.filter(program=program, position__name="first").exclude(student=student).exists():
    #             Prize.objects.filter(program=program, position__name="first").exclude(student=student).delete()

    #         prize, _ = Prize.objects.update_or_create(
    #             student=student, program=program,
    #             defaults={"position": pos, "remarks": remarks}
    #         )
    #         student.total_point += pos.mark
    #         student.save()
    #         created_prizes.append(prize.id)
    #     elif not first_prize_id:
    #         # If first prize is not assigned, remove any existing first prize for this program
    #         Prize.objects.filter(program=program, position__name="first").delete()

    #     if second_prize_id:
    #         student = get_object_or_404(Student, id=second_prize_id)
    #         pos, _ = Position.objects.get_or_create(name="second")

    #         if Prize.objects.filter(program=program, position__name="second").exclude(student=student).exists():
    #             Prize.objects.filter(program=program, position__name="second").exclude(student=student).delete()

    #         prize, _ = Prize.objects.update_or_create(
    #             student=student, program=program,
    #             defaults={"position": pos, "remarks": remarks}
    #         )
    #         student.total_point += pos.mark
    #         student.save()
    #         created_prizes.append(prize.id)
    #     elif not second_prize_id:
    #         # If second prize is not assigned, remove any existing second prize for this program
    #         Prize.objects.filter(program=program, position__name="second").delete()

    #     if third_prize_id:
    #         student = get_object_or_404(Student, id=third_prize_id)
    #         pos, _ = Position.objects.get_or_create(name="third")

    #         if Prize.objects.filter(program=program, position__name="third").exclude(student=student).exists():
    #             Prize.objects.filter(program=program, position__name="third").exclude(student=student).delete()

    #         prize, _ = Prize.objects.update_or_create(
    #             student=student, program=program,
    #             defaults={"position": pos, "remarks": remarks}
    #         )
    #         student.total_point += pos.mark
    #         student.save()
    #         created_prizes.append(prize.id)
    #     elif not third_prize_id:
    #         # If third prize is not assigned, remove any existing third prize for this program
    #         Prize.objects.filter(program=program, position__name="third").delete()

    #         # --- Handle Grades ---
    #     if gradeA_id:
    #         student = get_object_or_404(Student, id=gradeA_id)
    #         grade = get_object_or_404(Grade, name="a_grade")

    #         if Prize.objects.filter(program=program, grade__name="a_grade").exclude(student=student).exists():
    #             Prize.objects.filter(program=program, grade__name="a_grade").exclude(student=student).delete()

    #         prize, _ = Prize.objects.update_or_create(
    #             student=student, program=program,
    #             defaults={"grade": grade, "remarks": remarks}
    #         )
    #         student.total_point += grade.mark
    #         student.save()
    #         created_prizes.append(prize.id)
    #     elif not gradeA_id:
    #         # If grade A is not assigned, remove any existing grade A for this program
    #         Prize.objects.filter(program=program, grade__name="a_grade").delete()

    #     if gradeB_id:
    #         student = get_object_or_404(Student, id=gradeB_id)
    #         grade = get_object_or_404(Grade, name="b_grade")

    #         if Prize.objects.filter(program=program, grade__name="b_grade").exclude(student=student).exists():
    #             Prize.objects.filter(program=program, grade__name="b_grade").exclude(student=student).delete()

    #         prize, _ = Prize.objects.update_or_create(
    #             student=student, program=program,
    #             defaults={"grade": grade, "remarks": remarks}
    #         )
    #         student.total_point += grade.mark
    #         student.save()
    #         created_prizes.append(prize.id)
    #     elif not gradeB_id:
    #         # If grade B is not assigned, remove any existing grade B for this program
    #         Prize.objects.filter(program=program, grade__name="b_grade").delete()

    #     if gradeC_id:
    #         student = get_object_or_404(Student, id=gradeC_id)
    #         grade = get_object_or_404(Grade, name="c_grade")

    #         if Prize.objects.filter(program=program, grade__name="c_grade").exclude(student=student).exists():
    #             Prize.objects.filter(program=program, grade__name="c_grade").exclude(student=student).delete()

    #         prize, _ = Prize.objects.update_or_create(
    #             student=student, program=program,
    #             defaults={"grade": grade, "remarks": remarks}
    #         )
    #         student.total_point += grade.mark
    #         student.save()
    #         created_prizes.append(prize.id)
    #     elif not gradeC_id:
    #         # If grade C is not assigned, remove any existing grade C for this program
    #         Prize.objects.filter(program=program, grade__name="c_grade").delete()

    return JsonResponse({"message": "success", "created_prizes": created_prizes})



def publish_or_unpublish_result(request, program_id):
    program = get_object_or_404(Program, id=program_id)

    # Guard: cannot publish without any result (prize) having been added.
    if not program.prize_set.exists():
        return JsonResponse(
            {"message": "error", "details": "Add a result first before publishing."}
        )

    if program.is_result_published:
        program.is_result_published = False
    else:
        program.is_result_published = True
    program.save()
    return JsonResponse({"message": "success"})



class StudentUploadView(generic.TemplateView):
    template_name = 'program/student_data_upload.html'

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        user = self.request.user
        madrasa = user.madrasa
        teams = Team.objects.filter(madrasa=madrasa)
        categories = Category.objects.filter(madrasa=madrasa)
        context['teams'] = teams
        context['categories'] = categories
        context['needs_setup'] = (not teams.exists() or not categories.exists())

        context['total_students'] = Student.objects.filter(team__madrasa=madrasa).count()
        context['total_programs'] = Program.objects.filter(
            Q(category__in=categories) | Q(madrasa=madrasa)
        ).distinct().count()
        context['meelad_fest_name'] = madrasa.meelad_fest_name
        context['active_sections'] = list(madrasa.active_fest_sections)
        context['is_boys_only'] = madrasa.is_boys_only
        context['is_girls_only'] = madrasa.is_girls_only

        return context

    def post(self, request, *args, **kwargs):
        file = request.FILES.get("file")
        if not file:
            return JsonResponse({"error": "No file uploaded"}, status=400)

        try:
            # Load workbook
            wb = load_workbook(filename=file, data_only=True)
        except Exception as e:
            return JsonResponse({"error": f"Invalid Excel file: {str(e)}"}, status=400)

        if "Sheet1" not in wb.sheetnames:
            return JsonResponse(
                {"error": "The file has no 'Sheet1' worksheet. Please use the downloadable sample template."},
                status=400,
            )
        ws = wb["Sheet1"]  # Sheet with student data

        created, skipped = 0, 0
        errors = []

        to_create = []
        madrasa = request.user.madrasa

        # Iterate rows (skip header row)
        for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if all(cell is None for cell in row):
                continue

            # Pad short rows so unpacking never crashes on a malformed sheet.
            row = (list(row) + [None] * 5)[:5]
            code, full_name, gender, team_name, category_name = row

            if gender:
                gender = gender.strip().lower()

            if not full_name:
                skipped += 1
                errors.append(f"Row {idx}: Full Name is required")
                continue
            full_name = full_name.strip()

            # Validate gender
            if gender not in dict(Student.GENDER).keys():
                skipped += 1
                errors.append(f"Row {idx}: Invalid gender '{gender}'")
                continue

            # Get or create Team
            team = None
            if team_name:
                team_name = team_name.strip()
                try:
                    team = Team.objects.get(name=team_name, madrasa=madrasa)
                except Team.DoesNotExist:
                    skipped += 1
                    errors.append(f"Row {idx}: Team '{team_name}' not found")
                    continue

            # Get Category
            if category_name:
                category_name = category_name.strip()
            try:
                category = Category.objects.get(name=category_name, madrasa=madrasa)
            except Category.DoesNotExist:
                skipped += 1
                errors.append(f"Row {idx}: Category '{category_name}' not found")
                continue

            if Student.objects.exclude(full_name__iexact=full_name).filter(code_number=code, team__madrasa=team.madrasa).exists():
                skipped += 1
                errors.append(f"Row {idx}: Student code '{code}' already registered!")
                continue

            exists = Student.objects.filter(
                full_name=full_name,
                gender=gender,
                code_number=code,
                team=team,
                category=category
            ).exists()

            if not exists:
                to_create.append(
                    Student(
                        code_number=code,
                        full_name=full_name,
                        gender=gender,
                        team=team,
                        category=category,
                    )
                )

        # bulk create only if needed
        if to_create:
            Student.objects.bulk_create(to_create)
            created = len(to_create)

        return JsonResponse({
            "created": created,
            "skipped": skipped,
            "errors": errors,
        })


class SampleStudentUploadFileView(View):

    def get(self, request):
        # Create a new workbook
        wb = Workbook()

        # --- First sheet: Info ---
        ws_info = wb.active
        ws_info.title = "Info"

        user = request.user
        madrasa = user.madrasa
        categories = Category.objects.filter(madrasa=madrasa).values_list('name', flat=True)
        teams_list = list(madrasa.team_set.values_list('name', flat=True))
        # Data for Info sheet
        info_data = [
            ["Category"] + list(categories),
            ["Code", "Should be numbers"],
            ["Gender", "male", "female"],
            ["Team"] + teams_list,
        ]

        for row in info_data:
            ws_info.append(row)

        # --- Second sheet: Sample Upload ---
        ws_sample = wb.create_sheet(title="Sheet1")

        # Add header row
        headers = ["Code", "Full Name", "Gender", "Team", "Category"]
        ws_sample.append(headers)

        # Example row (optional, remove if you want empty template)
        # ws_sample.append(["101", "John Doe", "male", "team1", "Junior"])

        # Adjust column widths for readability
        for i, col in enumerate(headers, start=1):
            ws_sample.column_dimensions[get_column_letter(i)].width = 20

        # Prepare HTTP response
        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="student_upload.xlsx"'

        # Save workbook to response
        wb.save(response)

        return response



class ProgramUploadView(generic.TemplateView):
    """Bulk program upload — mirrors StudentUploadView.

    Sheet1 columns: Title | Type | Section | Category | Non-Stage | Description
      - Type: individual / group / general
      - Section: boys / girls (must be an active fest section)
      - Category: required for individual & group; the section decides whether
        the program links to category.programs (boys) or
        category.programs_for_girls (girls) — exactly like the manual add form.
      - Non-Stage: yes/no, individual only (group programs are always stage
        items, general programs have no stage/non-stage split here).
      - General programs ignore Category and automatically include every team,
        mirroring the manual general-program flow.
    """

    template_name = 'program/student_data_upload.html'

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        user = self.request.user
        madrasa = user.madrasa
        teams = Team.objects.filter(madrasa=madrasa)
        categories = Category.objects.filter(madrasa=madrasa)
        context['teams'] = teams
        context['categories'] = categories
        context['needs_setup'] = (not teams.exists() or not categories.exists())

        context['total_students'] = Student.objects.filter(team__madrasa=madrasa).count()
        context['total_programs'] = Program.objects.filter(
            Q(category__in=categories) | Q(madrasa=madrasa)
        ).distinct().count()
        context['meelad_fest_name'] = madrasa.meelad_fest_name
        context['active_sections'] = list(madrasa.active_fest_sections)
        context['is_boys_only'] = madrasa.is_boys_only
        context['is_girls_only'] = madrasa.is_girls_only

        return context

    def post(self, request, *args, **kwargs):
        file = request.FILES.get("file")
        if not file:
            return JsonResponse({"error": "No file uploaded"}, status=400)

        try:
            wb = load_workbook(filename=file, data_only=True)
        except Exception as e:
            return JsonResponse({"error": f"Invalid Excel file: {str(e)}"}, status=400)

        if "Sheet1" not in wb.sheetnames:
            return JsonResponse(
                {"error": "The file has no 'Sheet1' worksheet. Please use the downloadable sample template."},
                status=400,
            )
        ws = wb["Sheet1"]  # Sheet with program data

        created, skipped = 0, 0
        errors = []

        madrasa = request.user.madrasa
        active_sections = list(madrasa.active_fest_sections)
        valid_types = ('individual', 'group', 'general')

        # Validated rows awaiting insert: (Program instance, category to link,
        # row section). Linking happens after save() by object identity — never
        # by title — because different categories can legitimately reuse the
        # same program title (the old re-fetch-by-title mapping merged them onto
        # a single program).
        to_create = []

        for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if all(cell is None for cell in row):
                continue

            # Pad short rows so unpacking never crashes on a malformed sheet.
            row = (list(row) + [None] * 6)[:6]
            title, prog_type, section, category_name, non_stage, description = row

            # ---- Title (required) ----
            if title is None or not str(title).strip():
                skipped += 1
                errors.append(f"Row {idx}: Title is required")
                continue
            title = str(title).strip()

            # ---- Type (required) ----
            prog_type = str(prog_type).strip().lower() if prog_type is not None else ''
            if prog_type not in valid_types:
                skipped += 1
                errors.append(f"Row {idx}: Type must be individual, group or general (got '{prog_type}')")
                continue

            # ---- Section (required, must be active for this fest) ----
            section = str(section).strip().lower() if section is not None else ''
            if section not in (Program.SECTION_BOYS, Program.SECTION_GIRLS):
                skipped += 1
                errors.append(f"Row {idx}: Section must be boys or girls (got '{section}')")
                continue
            if section not in active_sections:
                skipped += 1
                errors.append(f"Row {idx}: '{section}' section is not active for this fest")
                continue

            # ---- Duplicate guard (same title + type within the madrasa) ----
            dup_qs = Program.objects.filter(
                madrasa=madrasa,
                title__iexact=title,
                is_group=(prog_type == 'group'),
                is_general=(prog_type == 'general'),
            )
            if prog_type == 'general':
                dup_qs = dup_qs.filter(section=section)
            if dup_qs.exists():
                skipped += 1
                errors.append(f"Row {idx}: Program '{title}' already exists!")
                continue

            # ---- Category (required for individual & group) ----
            category_obj = None
            if prog_type in ('individual', 'group'):
                category_name = str(category_name).strip() if category_name is not None else ''
                if not category_name:
                    skipped += 1
                    errors.append(f"Row {idx}: Category is required for {prog_type} programs")
                    continue
                try:
                    category_obj = Category.objects.get(name=category_name, madrasa=madrasa)
                except Category.DoesNotExist:
                    skipped += 1
                    errors.append(f"Row {idx}: Category '{category_name}' not found")
                    continue

            # ---- Non-Stage (yes/no, individual only) ----
            non_stage_flag = False
            if prog_type == 'individual':
                non_stage_flag = str(non_stage).strip().lower() in ('yes', 'y', 'true', '1') if non_stage is not None else False

            # ---- Description (optional) ----
            description = str(description).strip() if description is not None else ''

            program = Program(
                title=title,
                description=description or None,
                is_group=(prog_type == 'group'),
                is_general=(prog_type == 'general'),
                non_stage=non_stage_flag,
                # General programs store their section directly (no category
                # link); individual/group derive it from the category.
                section=section if prog_type == 'general' else None,
                madrasa=madrasa,
            )
            to_create.append((program, category_obj, section))

        # Create + link each validated row inside one transaction so a mid-way
        # DB error can't leave a half-loaded sheet behind.
        if to_create:
            with transaction.atomic():
                for program, category_obj, section in to_create:
                    program.save()
                    if program.is_general:
                        # General programs auto-include every team, mirroring
                        # the manual general-program flow.
                        program.general_teams.set(madrasa.team_set.all())
                    elif category_obj is not None:
                        if section == Program.SECTION_GIRLS:
                            category_obj.programs_for_girls.add(program)
                        else:
                            category_obj.programs.add(program)
            created = len(to_create)

        return JsonResponse({
            "created": created,
            "skipped": skipped,
            "errors": errors,
        })


class SampleProgramUploadFileView(View):
    """Generates the downloadable program-upload template workbook."""

    def get(self, request):
        wb = Workbook()

        # --- First sheet: Info sheet listing valid values ---
        ws_info = wb.active
        ws_info.title = "Info"

        madrasa = request.user.madrasa
        categories = list(Category.objects.filter(madrasa=madrasa).values_list('name', flat=True))
        sections = list(madrasa.active_fest_sections)

        info_data = [
            ["Type", "individual", "group", "general"],
            ["Section"] + sections,
            ["Category"] + categories,
            ["Non-Stage", "yes / no — individual programs only (group programs are always stage items)"],
            ["Teams", "General programs automatically include every team — no column needed"],
        ]
        for row in info_data:
            ws_info.append(row)

        # --- Second sheet: the upload sheet itself ---
        ws_sample = wb.create_sheet(title="Sheet1")
        headers = ["Title", "Type", "Section", "Category", "Non-Stage", "Description"]
        ws_sample.append(headers)

        for i, col in enumerate(headers, start=1):
            ws_sample.column_dimensions[get_column_letter(i)].width = 22

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="program_upload.xlsx"'
        wb.save(response)
        return response



class ResultDetailsView(generic.TemplateView):
    template_name = 'program/result_details.html'

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        madrasa = self.request.user.madrasa
        context['meelad_fest_name'] = madrasa.meelad_fest_name
        context['categories'] = Category.objects.filter(madrasa=madrasa)
        context['result_page'] = True
        return context



@login_required
def statistics_dashboard(request):
    madrasa = request.user.madrasa
    if not madrasa:
        return redirect('login')

    categories = Category.objects.filter(madrasa=madrasa)
    teams = Team.objects.filter(madrasa=madrasa)
    students = Student.objects.filter(
        team__madrasa=madrasa,
        gender__in=madrasa.active_genders(),
    ).select_related('category', 'team')

    top_students = students.order_by('-total_point')[:10]

    all_points = students.aggregate(total=Sum('total_point'))['total'] or 0
    girls_points = students.filter(gender='female').aggregate(total=Sum('total_point'))['total'] or 0
    boys_points = students.filter(gender='male').aggregate(total=Sum('total_point'))['total'] or 0

    summary_rows = []
    for team in teams:
        for category in categories:
            boy_students = students.filter(team=team, category=category, gender='male')
            girl_students = students.filter(team=team, category=category, gender='female')
            boys_points_for_row = boy_students.aggregate(total=Sum('total_point'))['total'] or 0
            girls_points_for_row = girl_students.aggregate(total=Sum('total_point'))['total'] or 0
            summary_rows.append({
                'team': team,
                'category': category,
                'boys_points': boys_points_for_row,
                'girls_points': girls_points_for_row,
                'students_count': boy_students.count() + girl_students.count(),
                'total_points': (boys_points_for_row or 0) + (girls_points_for_row or 0),
            })

    # --- Chart data (Fest Analytics section) -------------------------------
    # Efficient grouped aggregations over the same (gender-filtered) students
    # queryset used by the rest of the dashboard — no extra per-row queries.
    team_rows = (students
                 .values('team__id', 'team__name', 'team__colour')
                 .annotate(points=Sum('total_point'), students_count=Count('id'))
                 .order_by('-points'))
    category_rows = (students
                     .values('category__id', 'category__name')
                     .annotate(points=Sum('total_point'))
                     .order_by('-points'))
    # Team colours come straight from the scoreboard palette so each team's
    # slice matches its colour everywhere else in the app. Pure-white slices
    # are invisible on a white card, so they get a light slate shade instead.
    team_palette = []
    for row in team_rows:
        hex_color = Team.COLOR_HEX.get(row['team__colour'], '#6366f1')
        team_palette.append('#94a3b8' if hex_color == '#ffffff' else hex_color)

    chart_data = {
        'has_points': bool(all_points),
        'teams': {
            'labels': [row['team__name'] or 'Unnamed team' for row in team_rows],
            'points': [round(float(row['points'] or 0), 1) for row in team_rows],
            'students': [row['students_count'] or 0 for row in team_rows],
            'colors': team_palette,
        },
        'categories': {
            'labels': [row['category__name'] or 'Uncategorised' for row in category_rows],
            'points': [round(float(row['points'] or 0), 1) for row in category_rows],
        },
        'sections': {
            'labels': ['Boys', 'Girls'],
            'points': [float(boys_points or 0), float(girls_points or 0)],
        },
        'top_students': {
            'labels': [s.full_name for s in top_students],
            'points': [round(float(s.total_point or 0), 1) for s in top_students],
        },
    }

    context = {
        'meelad_fest_name': madrasa.meelad_fest_name if hasattr(madrasa, 'meelad_fest_name') else 'Meelad Fest',
        'categories': categories,
        'teams': teams,
        'students': students,
        'top_students': top_students,
        'statistics_page': True,
        'total_students': students.count(),
        'total_programs': Program.objects.filter(Q(category__in=categories) | Q(madrasa=madrasa)).distinct().count(),
        'total_points': all_points,
        'boys_points': boys_points,
        'girls_points': girls_points,
        'summary_rows': summary_rows,
        'chart_data': chart_data,
        'fest_type': madrasa.fest_type,
        'is_boys_only': madrasa.is_boys_only,
        'is_girls_only': madrasa.is_girls_only,
        'is_both_sections': madrasa.is_both_sections,
    }
    return render(request, 'program/statistics.html', context)


@login_required
def statistics_download_report(request):
    report_type = request.GET.get('report', 'students')
    madrasa = request.user.madrasa

    # If the browser sends an AJAX request (X-Requested-With header), return a
    # raw blob so the caller can download it in place without a page reload.
    # Stateless GET downloads (<a href=...>) still work exactly as before.
    if _is_ajax(request):
        buffer = BytesIO()
        writer = csv.writer(buffer)
        # Single-section fests only report on the active section's gender.
        genders = madrasa.active_genders()

        if report_type == 'category-performance':
            writer.writerow(['Team', 'Team ID', 'Category', 'Boys Points', 'Girls Points', 'Total Students', 'Category Total Points'])
            teams = Team.objects.filter(madrasa=madrasa)
            for team in teams:
                for category in Category.objects.filter(madrasa=madrasa):
                    boys_points = Student.objects.filter(team=team, category=category, gender='male').aggregate(total=Sum('total_point'))['total'] or 0
                    girls_points = Student.objects.filter(team=team, category=category, gender='female').aggregate(total=Sum('total_point'))['total'] or 0
                    students_count = Student.objects.filter(team=team, category=category, gender__in=genders).count()
                    cat_total = float(boys_points) + float(girls_points)
                    writer.writerow([team.name, team.id, category.name, boys_points, girls_points, students_count, cat_total])

        elif report_type == 'top-ten':
            writer.writerow(['Rank', 'Full Name', 'Code Number', 'Gender', 'Category', 'Team', 'Total Points'])
            students = Student.objects.filter(team__madrasa=madrasa, gender__in=genders).select_related('category', 'team').order_by('-total_point')[:10]
            for i, student in enumerate(students, start=1):
                writer.writerow([i, student.full_name, student.code_number or '', student.gender or '', student.category.name if student.category else '', student.team.name if student.team else '', student.total_point])

        elif report_type == 'top-category-section':
            writer.writerow(['Category', 'Section', 'Rank', 'Student', 'Code Number', 'Team', 'Total Points'])
            for category in Category.objects.filter(madrasa=madrasa):
                for section in genders:
                    section_students = Student.objects.filter(team__madrasa=madrasa, category=category, gender=section).order_by('-total_point')[:10]
                    for rank, student in enumerate(section_students, start=1):
                        writer.writerow([category.name, section, rank, student.full_name, student.code_number or '', student.team.name if student.team else '', student.total_point])

        else:
            writer.writerow(['Student Name', 'Code Number', 'Section', 'Category', 'Team', 'Team Madrasa', 'Total Points'])
            students = Student.objects.filter(team__madrasa=madrasa, gender__in=genders).select_related('category', 'team')
            for student in students:
                writer.writerow([
                    student.full_name,
                    student.code_number or '',
                    'Boys' if student.gender == 'male' else ('Girls' if student.gender == 'female' else student.gender or ''),
                    student.category.name if student.category else '',
                    student.team.name if student.team else '',
                    student.team.madrasa.name if student.team and student.team.madrasa else '',
                    student.total_point,
                ])

        buffer.seek(0)
        return HttpResponse(buffer.read(), content_type='text/csv')

    # ---- Non-AJAX (normal browser link click) path: unchanged behavior ----
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{report_type}_report.csv"'

    writer = csv.writer(response)
    # Single-section fests only report on the active section's gender.
    genders = madrasa.active_genders()

    if report_type == 'category-performance':
        writer.writerow(['Team', 'Team ID', 'Category', 'Boys Points', 'Girls Points', 'Total Students', 'Category Total Points'])
        teams = Team.objects.filter(madrasa=madrasa)
        for team in teams:
            for category in Category.objects.filter(madrasa=madrasa):
                boys_points = Student.objects.filter(team=team, category=category, gender='male').aggregate(total=Sum('total_point'))['total'] or 0
                girls_points = Student.objects.filter(team=team, category=category, gender='female').aggregate(total=Sum('total_point'))['total'] or 0
                students_count = Student.objects.filter(team=team, category=category, gender__in=genders).count()
                cat_total = float(boys_points) + float(girls_points)
                writer.writerow([team.name, team.id, category.name, boys_points, girls_points, students_count, cat_total])

    elif report_type == 'top-ten':
        writer.writerow(['Rank', 'Full Name', 'Code Number', 'Gender', 'Category', 'Team', 'Total Points'])
        students = Student.objects.filter(team__madrasa=madrasa, gender__in=genders).select_related('category', 'team').order_by('-total_point')[:10]
        for i, student in enumerate(students, start=1):
            writer.writerow([i, student.full_name, student.code_number or '', student.gender or '', student.category.name if student.category else '', student.team.name if student.team else '', student.total_point])

    elif report_type == 'top-category-section':
        writer.writerow(['Category', 'Section', 'Rank', 'Student', 'Code Number', 'Team', 'Total Points'])
        for category in Category.objects.filter(madrasa=madrasa):
            for section in genders:
                section_students = Student.objects.filter(team__madrasa=madrasa, category=category, gender=section).order_by('-total_point')[:10]
                for rank, student in enumerate(section_students, start=1):
                    writer.writerow([category.name, section, rank, student.full_name, student.code_number or '', student.team.name if student.team else '', student.total_point])

    else:
        writer.writerow(['Student Name', 'Code Number', 'Section', 'Category', 'Team', 'Team Madrasa', 'Total Points'])
        students = Student.objects.filter(team__madrasa=madrasa, gender__in=genders).select_related('category', 'team')
        for student in students:
            writer.writerow([
                student.full_name,
                student.code_number or '',
                'Boys' if student.gender == 'male' else ('Girls' if student.gender == 'female' else student.gender or ''),
                student.category.name if student.category else '',
                student.team.name if student.team else '',
                student.team.madrasa.name if student.team and student.team.madrasa else '',
                student.total_point,
            ])

    return response


def _general_section_lists(madrasa, fest_section):
    """Boys/Girls general-program lists (with display decorations).

    Shared by the GET render and the AJAX add re-render so both produce
    identical markup for ``program/_general_sections.html``.
    """
    def _general_qs(section):
        return (
            Program.objects
            .filter(is_general=True, section=section)
            # General programs are team-wise and have no category link, so we scope
            # by the program's own madrasa FK. This keeps them visible even before
            # any participating team has been added.
            .filter(madrasa=madrasa)
            .distinct()
            .order_by('-created')
        )

    if fest_section == Madrasa.FEST_TYPE_GIRLS:
        boys_qs = Program.objects.none()
        girls_qs = _general_qs(Program.SECTION_GIRLS)
    elif fest_section == Madrasa.FEST_TYPE_BOYS:
        boys_qs = _general_qs(Program.SECTION_BOYS)
        girls_qs = Program.objects.none()
    else:
        boys_qs = _general_qs(Program.SECTION_BOYS)
        girls_qs = _general_qs(Program.SECTION_GIRLS)

    # Attach current team-wise result (First/Second/Third) per program
    for prog in list(boys_qs) + list(girls_qs):
        prog.general_results = {}
        for prize in prog.prize_set.select_related('team', 'general_program_position'):
            if prize.general_program_position and prize.team:
                prog.general_results[prize.general_program_position.name] = prize.team
        # Student participant ids (for pre-selecting the checkboxes)
        prog.participant_ids = list(prog.participants.values_list('id', flat=True))
        # Poster section ('boys' / 'girls') for the download-poster button.
        prog.poster_section = _poster_section(prog, madrasa)
    return list(boys_qs), list(girls_qs)


def _group_section_lists(madrasa, fest_section):
    """Category-grouped Boys/Girls group-program lists (display-decorated).

    Shared by the GET render and the AJAX add re-render so both produce
    identical markup for ``program/_group_sections.html``.
    """
    def _group_qs(rel):
        return (
            Program.objects
            .filter(is_group=True, **{f"{rel}__madrasa": madrasa})
            .distinct()
            .order_by('-created')
        )

    if fest_section == Madrasa.FEST_TYPE_GIRLS:
        boys_qs = Program.objects.none()
        girls_qs = _group_qs("girls_categories")
    elif fest_section == Madrasa.FEST_TYPE_BOYS:
        boys_qs = _group_qs("category")
        girls_qs = Program.objects.none()
    else:
        boys_qs = _group_qs("category")
        girls_qs = _group_qs("girls_categories")

    def _decorate(prog):
        groups = _group_prizes(prog).prefetch_related('participants', 'participants__team')
        prog.groups = groups
        prog.group_results = {}
        for g in groups:
            if g.group_program_position:
                prog.group_results[g.group_program_position.name] = _group_display_name(g)
        # Poster section ('boys' / 'girls') for the download-poster button.
        prog.poster_section = _poster_section(prog, madrasa)
        # Participants belonging to this madrasa's teams (what we scope on).
        prog.madrasa_participant_count = prog.participants.filter(team__madrasa=madrasa).count()
        return prog

    for p in list(boys_qs) + list(girls_qs):
        _decorate(p)

    categories = Category.objects.filter(madrasa=madrasa)

    # Group each section's programs under their linked category (Boys -> category_set,
    # Girls -> girls_categories).
    def _build_groups(cats, qs, rel_name):
        groups = []
        for cat in cats:
            progs = [
                p for p in qs
                if getattr(p, rel_name).filter(id=cat.id).exists()
            ]
            if progs:
                groups.append({"category": cat, "programs": progs})
        return groups

    boys_groups = _build_groups(categories, boys_qs, "category_set")
    girls_groups = _build_groups(categories, girls_qs, "girls_categories")
    return boys_groups, girls_groups


@login_required
def general_programs(request):
    """Manage general programs which are team-wise (not category-wise).

    A general program's participants are teams; any student from any category
    within a participating team counts as a participant, and scores go to the
    team, not to individual students.
    """
    madrasa = request.user.madrasa
    fest_section = _fest_section(madrasa)
    teams = Team.objects.filter(madrasa=madrasa).order_by('name')
    # Only general programs attached to a section are shown here. Their
    # Boys/Girls section is stored directly on the program (general programs
    # are team-wise and have no category link). Programs with no section are
    # deliberately hidden. On a single-section fest only that section's
    # programs (and tab) are ever shown.
    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add":
            title = request.POST.get("title", "").strip()
            description = request.POST.get("description", "").strip()
            section = request.POST.get("section")  # 'boys' or 'girls'
            # On a single-section fest the section input is hidden; fall back
            # to the only active section and never accept the inactive one.
            if section not in madrasa.active_fest_sections:
                section = madrasa.active_fest_sections[0] if len(madrasa.active_fest_sections) == 1 else section
            if title and section in (Program.SECTION_BOYS, Program.SECTION_GIRLS) and _is_fest_section_active(madrasa, section):
                # General programs are team-wise and have no category; their
                # Boys/Girls section is stored directly on the program. The
                # program is owned by the logged-in madrasa (mirrors how group
                # programs are tied to a category, which itself belongs to a
                # madrasa).
                program = Program.objects.create(
                    title=title, description=description or None,
                    is_general=True, section=section,
                    madrasa=madrasa,
                )
                # General programs are contested team-wise, so every team of the
                # madrasa is a participating team by default. This also lets the
                # program show up and have its result set immediately.
                program.general_teams.set(madrasa.team_set.all())
                if _is_ajax(request):
                    boys_programs, girls_programs = _general_section_lists(madrasa, fest_section)
                    cards_html = render(request, 'program/_general_sections.html', {
                        'boys_programs': boys_programs,
                        'girls_programs': girls_programs,
                        'is_boys_only': madrasa.is_boys_only,
                        'is_girls_only': madrasa.is_girls_only,
                        'is_both_sections': madrasa.is_both_sections,
                    }).content.decode('utf-8')
                    return JsonResponse({
                        "ok": True,
                        "message": f"General program '{program.title}' added successfully.",
                        "program": {
                            "id": program.id,
                            "title": program.title,
                            "description": program.description or "",
                            "section": program.section,
                        },
                        "cards_html": cards_html,
                    })
                return redirect(f"{reverse('general_programs')}?new_program={program.id}")
            if _is_ajax(request):
                return JsonResponse(
                    {"ok": False, "error": "Please provide a valid title and an active section."},
                    status=400)
            return redirect("general_programs")

        elif action == "save_team":
            """Add / update a single team (with its participants) on a general program.

            Returns JSON so the template can show a toast and reload without a
            full-page redirect.
            """
            program = get_object_or_404(Program, id=request.POST.get("program_id"), is_general=True)

            # Guard: once a result has been set for this program, no more teams
            # may be added/edited.
            if program.prize_set.filter(general_program_position__isnull=False).exists():
                return JsonResponse(
                    {"message": "error",
                     "details": "Cannot add/update team: a result has already been set for this program."}
                )

            team_id = request.POST.get("team_id")
            participant_ids = [p for p in request.POST.getlist("participants") if p]

            if not team_id:
                return JsonResponse({"message": "error", "details": "Please select a team."})

            try:
                team = Team.objects.get(id=team_id, madrasa=madrasa)
            except Team.DoesNotExist:
                return JsonResponse({"message": "error", "details": "Team not found."})

            # Validate participants actually belong to the selected team
            participants = Student.objects.filter(id__in=participant_ids, team=team)

            if not participants.exists():
                return JsonResponse(
                    {"message": "error", "details": f"Please select at least one participant for {team.name}."}
                )

            # Pre-clear the team's students from program participants to support editing/updating
            team_students = Student.objects.filter(team=team)
            program.participants.remove(*team_students)

            program.general_teams.add(team)
            program.participants.add(*participants)

            return JsonResponse({"message": "success", "team": team.name, "count": participants.count()})

        elif action == "remove_team":
            """Remove a single team (and its students) from a general program."""
            program = get_object_or_404(Program, id=request.POST.get("program_id"), is_general=True)
            team_id = request.POST.get("team_id")

            if not team_id:
                return JsonResponse({"message": "error", "details": "Team ID is required."})

            try:
                team = Team.objects.get(id=team_id, madrasa=madrasa)
            except Team.DoesNotExist:
                return JsonResponse({"message": "error", "details": "Team not found."})

            # Do not allow removing a team once results have been set for this program
            if program.prize_set.filter(general_program_position__isnull=False).exists():
                return JsonResponse(
                    {"message": "error",
                     "details": "Cannot remove team: results have already been set for this program."}
                )

            # Remove the team's students from this program's participants
            team_students = Student.objects.filter(team=team)
            program.participants.remove(*team_students)
            program.general_teams.remove(team)

            return JsonResponse({"message": "success", "team": team.name})

    categories = Category.objects.filter(madrasa=madrasa)

    # General programs have no category grouping — each section is a flat list.
    boys_programs, girls_programs = _general_section_lists(madrasa, fest_section)
    context = {
        'boys_programs': boys_programs,
        'girls_programs': girls_programs,
        'general_programs': boys_programs + girls_programs,
        'teams': teams,
        # Overall team-wise general ranking (sum of all published general prizes)
        'general_team_results': get_general_team_results(madrasa, fest_section),
        'meelad_fest_name': madrasa.meelad_fest_name,
        'total_students': Student.objects.filter(team__madrasa=madrasa).count(),
        'total_programs': Program.objects.filter(category__in=categories).distinct().count()
                            + Program.objects.filter(is_general=True, madrasa=madrasa).distinct().count(),
        'fest_type': madrasa.fest_type,
        'is_boys_only': madrasa.is_boys_only,
        'is_girls_only': madrasa.is_girls_only,
        'is_both_sections': madrasa.is_both_sections,
    }
    return render(request, 'program/general_programs.html', context)


@login_required
@require_POST
@transaction.atomic
def save_general_prize(request, program_id):
    """Team-wise result entry for a general program.

    Reads First/Second/Third as TEAM ids and stores the positions against the
    team (Prize.team + general_program_position). A cleared position removes
    the corresponding team prize.
    """
    program = get_object_or_404(Program, id=program_id, is_general=True)
    data = json.loads(request.body.decode("utf-8"))

    # Guard: setting a team-wise result requires at least one team added first
    if program.general_teams.count() == 0:
        return JsonResponse(
            {"message": "error", "details": "Add a team first before setting the result."}
        )

    # Resolve the madrasa from the program itself so the GeneralPosition
    # records (which are scoped per madrasa) are the ones configured for the
    # madrasa that owns this program, not necessarily the logged-in user's.
    madrasa = _resolve_program_madrasa(program, request)

    position_names = [
        ("first", data.get("first")),
        ("second", data.get("second")),
        ("third", data.get("third")),
    ]

    # A single team cannot win more than one position in the same program's
    # result. Reject duplicate team selections before mutating any prizes.
    used_team_ids = {}
    for position_name, team_id in position_names:
        if team_id:
            tid = int(team_id)
            if tid in used_team_ids:
                return JsonResponse({
                    "message": "error",
                    "details": f"Same team selected for more than one position (already {used_team_ids[tid]}).",
                })
            used_team_ids[tid] = position_name

    for position_name, team_id in position_names:
        gen_pos, _ = GeneralPosition.objects.get_or_create(name=position_name, madrasa=madrasa)

        # Clear this position for any other team
        Prize.objects.filter(
            program=program,
            general_program_position=gen_pos,
        ).exclude(team_id=team_id).delete()

        if team_id:
            team = get_object_or_404(Team, id=team_id)
            Prize.objects.update_or_create(
                team=team,
                program=program,
                defaults={"general_program_position": gen_pos}
            )
        else:
            # No team chosen for this position -> remove existing one
            Prize.objects.filter(
                program=program,
                general_program_position=gen_pos,
            ).delete()

    return JsonResponse({"message": "success"})

# ---------------------------------------------------------------------------
# Group-program management (is_group=True)
# ---------------------------------------------------------------------------
def _group_prizes(program):
    """Prize rows that represent real groups (they have participants)."""
    return (
        Prize.objects
        .filter(program=program)
        .annotate(gc=Count('participants'))
        .filter(gc__gt=0)
        .order_by('id')
    )


def _group_display_name(prize):
    """A readable name for a group built from its member students.

    Follows the ``{{member name}} & Team`` style: single member → "X & Team",
    multiple members → "X & Y & Z".
    """
    names = list(prize.participants.order_by('id').values_list('full_name', flat=True))
    if not names:
        return "(empty group)"
    if len(names) == 1:
        return f"{names[0]} & Team"
    return " & ".join(names)


@login_required
def group_programs(request):
    madrasa = request.user.madrasa
    fest_section = _fest_section(madrasa)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            title = request.POST.get("title", "").strip()
            description = request.POST.get("description", "").strip()
            category_id = request.POST.get("category_id")
            section = request.POST.get("section")  # 'boys' or 'girls'
            # On a single-section fest the section input is hidden; fall back
            # to the only active section and never accept the inactive one.
            if section not in madrasa.active_fest_sections:
                section = madrasa.active_fest_sections[0] if len(madrasa.active_fest_sections) == 1 else section
            if title and _is_fest_section_active(madrasa, section):
                program = Program.objects.create(
                    title=title, description=description or None,
                    is_group=True, is_general=False,
                    non_stage=False,  # group programs are stage programs by default
                    madrasa=madrasa,  # own the program by the logged-in madrasa
                )
                if category_id:
                    # Link the group program to the chosen section/category. Boys
                    # programs go to category.programs (category_set), girls to
                    # category.programs_for_girls (girls_categories).
                    category = Category.objects.filter(id=category_id, madrasa=madrasa).first()
                    if category:
                        if section == 'girls':
                            category.programs_for_girls.add(program)
                        else:
                            category.programs.add(program)
                if _is_ajax(request):
                    boys_groups, girls_groups = _group_section_lists(madrasa, fest_section)
                    cards_html = render(request, 'program/_group_sections.html', {
                        'boys_groups': boys_groups,
                        'girls_groups': girls_groups,
                        'is_boys_only': madrasa.is_boys_only,
                        'is_girls_only': madrasa.is_girls_only,
                        'is_both_sections': madrasa.is_both_sections,
                    }).content.decode('utf-8')
                    return JsonResponse({
                        "ok": True,
                        "message": f"Group program '{program.title}' added successfully.",
                        "program": {
                            "id": program.id,
                            "title": program.title,
                            "description": program.description or "",
                            "section": section,
                        },
                        "cards_html": cards_html,
                    })
                messages.success(request, f"Group program '{program.title}' added successfully.")
                return redirect(f"{reverse('group_programs')}?new_program={program.id}")
            if _is_ajax(request):
                return JsonResponse(
                    {"ok": False, "error": "Please provide a valid title and an active section."},
                    status=400)
        if _is_ajax(request):
            return JsonResponse(
                {"ok": False, "error": "Please provide a valid title, category and an active section."},
                status=400)
        return redirect("group_programs")

    # Category-grouped, section-split lists (shared with the AJAX re-render).
    boys_groups, girls_groups = _group_section_lists(madrasa, fest_section)
    categories_qs = Category.objects.filter(madrasa=madrasa)

    context = {
        'boys_groups': boys_groups,
        'girls_groups': girls_groups,
        'categories': categories_qs,
        'group_programs': [p for g in boys_groups + girls_groups for p in g["programs"]],
        # Overall team-wise group ranking (sum of all published group-program marks)
        'group_team_results': get_group_team_results(madrasa, fest_section),
        'meelad_fest_name': madrasa.meelad_fest_name,
        'total_students': Student.objects.filter(team__madrasa=madrasa).count(),
        'total_programs': Program.objects.filter(category__in=categories_qs).distinct().count()
                            + Program.objects.filter(is_group=True, participants__team__madrasa=madrasa).distinct().count(),
        'fest_type': madrasa.fest_type,
        'is_boys_only': madrasa.is_boys_only,
        'is_girls_only': madrasa.is_girls_only,
        'is_both_sections': madrasa.is_both_sections,
    }
    return render(request, 'program/group_programs.html', context)


@login_required
def add_program(request):
    """Create a program from the Programs Dashboard's expandable add form.

    Supports all three program types (individual / group / general) and mirrors
    the validation and linking rules of the general/group pages and the bulk
    upload view, so the dashboard gets one consistent "Add Program" entry
    point:
      - individual/group need a category; boys link via ``Category.programs``
        and girls via ``Category.programs_for_girls`` (same as the manual add).
      - general programs ignore Category, store their section directly and
        auto-include every team (same as the General Programs page).
    """
    madrasa = request.user.madrasa
    if request.method != "POST":
        return redirect("program_list")

    title = (request.POST.get("title") or "").strip()
    prog_type = (request.POST.get("type") or "").strip().lower()
    section = (request.POST.get("section") or "").strip().lower()
    category_id = request.POST.get("category_id") or None
    non_stage = request.POST.get("non_stage") in ("on", "1", "true", "yes")
    description = (request.POST.get("description") or "").strip()
    next_url = request.POST.get("next") or reverse("program_list")

    active_sections = list(madrasa.active_fest_sections)

    if not title or prog_type not in ("individual", "group", "general"):
        err = "Program title is required and Type must be individual, group or general."
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": err}, status=400)
        messages.error(request, err)
        return redirect(next_url)
    if section not in (Program.SECTION_BOYS, Program.SECTION_GIRLS) or section not in active_sections:
        err = "Please choose an active section (boys/girls)."
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": err}, status=400)
        messages.error(request, err)
        return redirect(next_url)

    # Duplicate guard (same title + type within the madrasa; general also by
    # section) — matches ProgramUploadView so manual and bulk adds agree.
    dup_qs = Program.objects.filter(
        madrasa=madrasa,
        title__iexact=title,
        is_group=(prog_type == "group"),
        is_general=(prog_type == "general"),
    )
    if prog_type == "general":
        dup_qs = dup_qs.filter(section=section)
    if dup_qs.exists():
        err = f"Program '{title}' already exists."
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": err}, status=400)
        messages.error(request, err)
        return redirect(next_url)

    category_obj = None
    if prog_type in ("individual", "group"):
        if not category_id:
            err = "Category is required for individual and group programs."
            if _is_ajax(request):
                return JsonResponse({"ok": False, "error": err}, status=400)
            messages.error(request, err)
            return redirect(next_url)
        category_obj = Category.objects.filter(id=category_id, madrasa=madrasa).first()
        if category_obj is None:
            err = "Please select a valid category."
            if _is_ajax(request):
                return JsonResponse({"ok": False, "error": err}, status=400)
            messages.error(request, err)
            return redirect(next_url)

    program = Program.objects.create(
        title=title,
        description=description or None,
        is_group=(prog_type == "group"),
        is_general=(prog_type == "general"),
        non_stage=non_stage if prog_type == "individual" else False,
        # General programs store their section directly (no category link);
        # individual/group derive their section from the category.
        section=section if prog_type == "general" else None,
        madrasa=madrasa,
    )

    if prog_type == "general":
        program.general_teams.set(madrasa.team_set.all())
        general_url = f"{reverse('general_programs')}?new_program={program.id}"
        if _is_ajax(request):
            return JsonResponse({
                "ok": True,
                "message": f"General program '{program.title}' added successfully.",
                "program": {"id": program.id, "title": program.title},
                "redirect": general_url,
            })
        messages.success(
            request, f"General program '{title}' added successfully.")
        return redirect(general_url)

    # Individual / group programs link to the chosen category exactly like the
    # manual category-add flow.
    if section == Program.SECTION_GIRLS:
        category_obj.programs_for_girls.add(program)
    else:
        category_obj.programs.add(program)
    list_url = f"{reverse('program_list')}?new_program={program.id}"
    if _is_ajax(request):
        return JsonResponse({
            "ok": True,
            "message": f"Program '{program.title}' added successfully.",
            "program": {"id": program.id, "title": program.title},
            "redirect": list_url,
        })
    messages.success(request, f"Program '{program.title}' added successfully.")
    return redirect(list_url)


@login_required
def group_program_detail(request, program_id):
    madrasa = request.user.madrasa
    # Group programs have no direct madrasa FK; ownership is inferred from the
    # madrasa of their participants' teams, so a user only ever sees/accesses
    # group programs that belong to their own madrasa.
    program = get_object_or_404(
        Program.objects.filter(is_group=True, madrasa=madrasa).distinct(),
        id=program_id,
    )

    if request.method == "POST":
        action = request.POST.get("action")

        # Create a new group from the selected (currently unassigned) participants.
        if action == "create_group":
            # The frontend posts the ids as a repeated single field ("participant_ids"),
            # but older/some clients send them as indexed keys ("participant_ids[0]",
            # "participant_ids[1]..."). getlist() only sees the former, so also scan all
            # POST keys to make sure we never silently drop selected participants — that
            # would otherwise trigger a misleading "at least two members" error.
            participant_ids = request.POST.getlist("participant_ids")
            if not participant_ids:
                participant_ids = [
                    v
                    for k, v in request.POST.items()
                    if k.startswith("participant_ids[")
                ]
            participant_ids = [p for p in participant_ids if p]

            if not participant_ids:
                return JsonResponse(
                    {"message": "error", "details": "No participants were selected."}
                )
            if len(participant_ids) < 2:
                return JsonResponse(
                    {"message": "error", "details": "A group must contain at least two members."}
                )
            students = Student.objects.filter(
                id__in=participant_ids,
                program__id=program.id,
                team__madrasa=madrasa,
            )
            if students.count() != len(participant_ids):
                return JsonResponse(
                    {"message": "error", "details": "Some selected participants are not registered for this program."}
                )
            # All members must belong to the same team so the score can go to the team.
            teams = {s.team_id for s in students}
            if len(teams) != 1:
                return JsonResponse(
                    {"message": "error", "details": "All group members must belong to the same team."}
                )
            # None may already be assigned to an existing group.
            assigned = set(
                Prize.objects.filter(
                    program=program,
                    participants__in=students,
                ).values_list('participants__id', flat=True)
            )
            if assigned & set(participant_ids):
                return JsonResponse(
                    {"message": "error", "details": "One or more selected participants are already in a group."}
                )

            team = students.first().team
            group = Prize.objects.create(program=program, team=team)
            group.participants.set(students)
            return JsonResponse({"message": "success", "group_name": _group_display_name(group)})

        # Remove an entire group (its members go back to being unassigned).
        if action == "delete_group":
            group_id = request.POST.get("group_id")
            group = Prize.objects.filter(id=group_id, program=program).first()
            if group:
                group.delete()
                return JsonResponse({"message": "success"})
            return JsonResponse({"message": "error", "details": "Group not found."})

        # Remove a participant from the program entirely.
        if action == "remove_participant":
            student_id = request.POST.get("participant_id")
            student = Student.objects.filter(id=student_id, team__madrasa=madrasa).first()
            if not student:
                return JsonResponse({"message": "error", "details": "Participant not found."})
            program.participants.remove(student)
            for g in _group_prizes(program).filter(participants=student):
                g.participants.remove(student)
                if g.participants.count() == 0:
                    g.delete()
            return JsonResponse({"message": "success"})

        return JsonResponse({"message": "error", "details": "Unknown action"})

    participants = program.participants.filter(
        team__madrasa=madrasa
    ).select_related('team').order_by('full_name')
    groups = _group_prizes(program).prefetch_related('participants', 'participants__team')
    for g in groups:
        g.display_name = _group_display_name(g)

    # participant ids already assigned to a group
    assigned_ids = set(
        Prize.objects.filter(program=program).values_list('participants__id', flat=True).distinct()
    )
    unassigned = [p for p in participants if p.id not in assigned_ids]

    group_results = {}
    for g in groups:
        if g.group_program_position:
            group_results[g.group_program_position.name] = g

    context = {
        'program': program,
        'participants': participants,
        'groups': groups,
        'unassigned': unassigned,
        'assigned_ids': assigned_ids,
        'group_results': group_results,
        # Poster section ('boys' / 'girls') for the download-poster button.
        'poster_section': _poster_section(program, request.user.madrasa),
    }
    return render(request, 'program/group_program_detail.html', context)


@require_POST
@login_required
@transaction.atomic
def save_group_prize(request, program_id):
    """Team-wise result entry for a group program.

    First/Second/Third select a *group* (a Prize row holding the member students).
    The group's team is the scoring unit; the result is associated with the chosen
    group so its group name (members) shows as the prize winner.
    """
    program = get_object_or_404(Program, id=program_id, is_group=True)

    # A group-program result requires at least one group to exist.
    if not _group_prizes(program).exists():
        return JsonResponse(
            {"message": "error", "details": "Create a group first before adding a result."}
        )

    madrasa = _resolve_program_madrasa(program, request)
    data = json.loads(request.body.decode("utf-8"))

    used_group_ids = {}
    for position_name, group_id in (
        ("first", data.get("first")),
        ("second", data.get("second")),
        ("third", data.get("third")),
    ):
        pos, _ = GroupPosition.objects.get_or_create(name=position_name, madrasa=madrasa)

        # Clear this position from every group of this program first.
        _group_prizes(program).filter(group_program_position=pos).update(group_program_position=None)

        if group_id:
            group = get_object_or_404(Prize, id=int(group_id), program=program)
            if group.participants.count() == 0:
                return JsonResponse({"message": "error", "details": "Selected group has no members."})
            # A group can only win a single position.
            if int(group_id) in used_group_ids:
                return JsonResponse(
                    {"message": "error",
                     "details": f"Same group selected for more than one position ({used_group_ids[int(group_id)]})."}
                )
            used_group_ids[int(group_id)] = position_name
            group.group_program_position = pos
            group.save()

    return JsonResponse({"message": "success"})


def get_group_team_results(madrasa, section='both'):
    """Group category: results ranked team-wise across published group programs.

    ``section`` scopes the ranking to the active fest section mode so a
    boys-only fest never counts girls group-program points. Every team that has
    a published group-program prize is returned, ordered by descending total
    group marks.
    """
    base = (
        Prize.objects
        .filter(
            team__madrasa=madrasa,
            team__isnull=False,
            program__is_group=True,
            program__is_result_published=True,
            program__in=Program.objects.filter(program_section_q(madrasa, section)),
            group_program_position__isnull=False,
        )
        .values("team__id", "team__name", "team__colour")
        .annotate(
            total_group=Coalesce(
                Sum("group_program_position__mark"),
                Value(0.0),
                output_field=FloatField()
            )
        )
        .order_by("-total_group", "team__name")
    )
    results = list(base)
    for idx, row in enumerate(results, start=1):
        row["rank"] = idx
        row["medal"] = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, "")
        row["position_text"] = {1: "First", 2: "Second", 3: "Third"}.get(idx, "")
    return results


def get_general_team_results(madrasa, section='both'):
    """General category: results are ranked team-wise (not per program).

    ``section`` scopes the ranking to the active fest section mode so a
    boys-only fest never counts girls general-program points. Every team that
    has any published general-program prize is returned, ordered by
    descending total general marks. Row dicts are decorated with
    'position_text' and 'medal' so the template can render them directly.
    """
    general_sections = {
        Madrasa.FEST_TYPE_BOYS: [Program.SECTION_BOYS],
        Madrasa.FEST_TYPE_GIRLS: [Program.SECTION_GIRLS],
    }.get(section, [Program.SECTION_BOYS, Program.SECTION_GIRLS])

    base = (
        Prize.objects
        .filter(
            team__madrasa=madrasa,
            team__isnull=False,
            program__is_general=True,
            program__section__in=general_sections,
            program__is_result_published=True,
            general_program_position__isnull=False,
        )
        .values("team__id", "team__name", "team__colour")
        .annotate(
            total_general=Coalesce(
                Sum("general_program_position__mark"),
                Value(0.0),
                output_field=FloatField()
            )
        )
        .order_by("-total_general", "team__name")
    )

    results = list(base)
    for idx, row in enumerate(results, start=1):
        row["rank"] = idx
        row["medal"] = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, "")
        row["position_text"] = {1: "First", 2: "Second", 3: "Third"}.get(idx, "")
    return results


def category_program_list(request):
    category_id = request.GET.get('category')
    madrasa = request.user.madrasa
    fest_section = _fest_section(madrasa)
    categories = Category.objects.filter(madrasa=madrasa)

    # On a single-section fest only the active section's result table is shown.
    show_boys = not madrasa.is_girls_only
    show_girls = not madrasa.is_boys_only

    if category_id:
        selected_category = get_object_or_404(Category, id=category_id)
        if show_boys:
            programs_for_boys = (
                selected_category.programs.all()
                .exclude(is_general=True)
                .exclude(is_group=True)
                .annotate(
                    published=Case(
                        When(prize__isnull=False, then=Value(True)),
                        default=Value(False),
                        output_field=BooleanField()
                    )
                )
                .order_by('-published').distinct()  # Descending: True (has prize) comes first
            )
        else:
            programs_for_boys = Program.objects.none()
        if show_girls:
            programs_for_girls = (selected_category.programs_for_girls.all()
                                  .exclude(is_general=True)
                                  .exclude(is_group=True)
                                  .annotate(
                published=Case(
                    When(prize__isnull=False, then=Value(True)),
                    default=Value(False),
                    output_field=BooleanField()
                )
            )
            .order_by('-published').distinct()
                                  )
        else:
            programs_for_girls = Program.objects.none()
    else:
        base_qs = (
            Program.objects
            .filter(program_section_q(madrasa, fest_section))
            .exclude(is_general=True)
            .exclude(is_group=True)
        )
        if show_boys and show_girls:
            programs_for_boys = programs_for_girls = base_qs
        else:
            # Single-section fest: only the active section's programs.
            if show_boys:
                programs_for_boys = base_qs
                programs_for_girls = Program.objects.none()
            else:
                programs_for_boys = Program.objects.none()
                programs_for_girls = base_qs
        selected_category = None

    try:
        madrasa_id = request.user.madrasa.id
        categories = Category.objects.filter(madrasa_id=madrasa_id)
        total_students = Student.objects.filter(team__madrasa=madrasa_id).count()
        total_programs = Program.objects.filter(Q(category__in=categories) | Q(madrasa_id=madrasa_id)).distinct().count()
    except AttributeError:
        pass

    # --- Header stats ------------------------------------------------------
    # Counted over exactly the programs listed below, de-duplicated so a
    # both-section fest (where boys and girls share a single queryset) is never
    # counted twice. These follow the category filter on purpose — the numbers
    # always describe the table the user is looking at.
    listed_ids = set(programs_for_boys.values_list('id', flat=True))
    listed_ids.update(programs_for_girls.values_list('id', flat=True))
    listed_programs = Program.objects.filter(id__in=listed_ids)

    result_total_programs = listed_programs.count()
    result_published = listed_programs.filter(is_result_published=True).count()
    # A program counts as "entered" once at least one prize row exists for it,
    # matching the is_result_added template filter used by the table rows.
    result_entered = (
        listed_programs.filter(prize__isnull=False).values('id').distinct().count()
    )
    result_unpublished = result_total_programs - result_published
    result_awaiting = max(result_entered - result_published, 0)
    result_not_entered = max(result_total_programs - result_entered, 0)

    context = {
        'categories': categories,
        'programs_for_boys': programs_for_boys,
        'programs_for_girls': programs_for_girls,
        'selected_category': selected_category,
        'result_page': True,
        'result_total_programs': result_total_programs,
        'result_published': result_published,
        'result_unpublished': result_unpublished,
        'result_awaiting': result_awaiting,
        'result_not_entered': result_not_entered,
        'meelad_fest_name': madrasa.meelad_fest_name,
        'total_students': total_students,
        'total_programs': total_programs,
        'fest_type': madrasa.fest_type,
        'is_boys_only': madrasa.is_boys_only,
        'is_girls_only': madrasa.is_girls_only,
        'is_both_sections': madrasa.is_both_sections,
    }
    return render(request, 'program/result_details.html', context)


def _prize_positions(prizes):
    """Return the 1st/2nd/3rd display strings from a program's prizes."""
    winners = {'first': None, 'second': None, 'third': None}
    for prize in prizes:
        pos_name = None
        if prize.general_program_position:
            pos_name = prize.general_program_position.name
        elif prize.group_program_position:
            pos_name = prize.group_program_position.name
        elif prize.position:
            pos_name = prize.position.name

        if pos_name not in winners:
            continue

        if prize.student:
            # Individual prize: winner is the student.
            name = prize.student.full_name
            team = prize.student.team.name if prize.student.team else ""
        elif prize.group_program_position:
            # Group prize: winner is the team, but show its member names
            # joined with "&" so the group is recognisable.
            members = " & ".join(
                prize.participants.order_by('id').values_list('full_name', flat=True)
            )
            name = members
            team = prize.team.name if prize.team else ""
        else:
            # Team-wise (general) prize: winner is just the team.
            team = prize.team.name if prize.team else ""
            name = ""

        if name and team:
            display = f"{name} ({team})"
        else:
            display = name or team

        winners[pos_name] = display
    return winners


@login_required
def download_all_results_pdf(request):
    """Generate a single formal PDF with results for every category
    (each category on its own page) followed by a team-wise summary that
    includes general results."""
    madrasa = request.user.madrasa
    if not madrasa:
        return redirect('login')

    fest_section = _fest_section(madrasa)
    genders = _fest_active_genders(madrasa)
    # General programs carry their section on the program row.
    general_sections = {
        Madrasa.FEST_TYPE_BOYS: [Program.SECTION_BOYS],
        Madrasa.FEST_TYPE_GIRLS: [Program.SECTION_GIRLS],
    }.get(fest_section, [Program.SECTION_BOYS, Program.SECTION_GIRLS])
    show_boys = not madrasa.is_girls_only
    show_girls = not madrasa.is_boys_only

    categories = list(Category.objects.filter(madrasa=madrasa).order_by('name'))
    teams = list(Team.objects.filter(madrasa=madrasa).order_by('name'))

    # ---- Per-category results (programs + 1st/2nd/3rd winners) ----
    category_sections = []
    prize_related = ('student__team', 'team', 'position',
                     'group_program_position', 'general_program_position')
    for cat in categories:
        boys = []
        if show_boys:
            for prog in cat.programs.all().exclude(is_general=True).order_by('title'):
                prizes = Prize.objects.filter(program=prog).select_related(*prize_related)
                boys.append({
                    'title': prog.title,
                    'published': prog.is_result_published,
                    'winners': _prize_positions(prizes),
                })
        girls = []
        if show_girls:
            for prog in cat.programs_for_girls.all().exclude(is_general=True).order_by('title'):
                prizes = Prize.objects.filter(program=prog).select_related(*prize_related)
                girls.append({
                    'title': prog.title,
                    'published': prog.is_result_published,
                    'winners': _prize_positions(prizes),
                })
        category_sections.append({'category': cat, 'boys': boys, 'girls': girls})

    # ---- General (team-wise) programs results (active sections only) ----
    general_section = []
    for prog in Program.objects.filter(is_general=True, section__in=general_sections).order_by('title'):
        prizes = Prize.objects.filter(program=prog).select_related(*prize_related)
        general_section.append({
            'title': prog.title,
            'published': prog.is_result_published,
            'winners': _prize_positions(prizes),
        })

    # ---- Team-wise summary (per category + general + grand total) ----
    summary = []
    for team in teams:
        cat_totals = {}
        for cat in categories:
            ind = Prize.objects.filter(
                student__team=team, student__category=cat,
                student__gender__in=genders,
                program__is_result_published=True,
            ).aggregate(
                pos=Coalesce(Sum('position__mark'), Value(0.0), output_field=FloatField()),
                grade=Coalesce(Sum('grade__mark'), Value(0.0), output_field=FloatField()),
            )
            # Group points within this category come only from the category's
            # programs in the active fest section.
            if madrasa.is_girls_only:
                cat_programs = cat.programs_for_girls.all()
            elif madrasa.is_boys_only:
                cat_programs = cat.programs.all()
            else:
                cat_programs = cat.programs.all() | cat.programs_for_girls.all()
            group = Prize.objects.filter(
                team=team,
                program__is_result_published=True,
                group_program_position__isnull=False,
                program__in=cat_programs,
            ).aggregate(g=Coalesce(Sum('group_program_position__mark'), Value(0.0), output_field=FloatField()))
            cat_totals[cat.id] = round(
                float(ind['pos']) + float(ind['grade']) + float(group['g']), 2
            )
        general = Prize.objects.filter(
            team=team, program__is_result_published=True,
            program__section__in=general_sections,
            general_program_position__isnull=False,
        ).aggregate(g=Coalesce(Sum('general_program_position__mark'), Value(0.0), output_field=FloatField()))
        general_total = round(float(general['g']), 2)
        cat_sum = round(sum(cat_totals.values()), 2)
        summary.append({
            'team': team,
            'cat_totals': cat_totals,
            'general': general_total,
            'grand_total': round(cat_sum + general_total, 2),
        })
    summary.sort(key=lambda r: r['grand_total'], reverse=True)
    for idx, row in enumerate(summary, start=1):
        row['rank'] = idx



# ---- Build the PDF ----
    response = HttpResponse(content_type='application/pdf')
    filename = f"all_results_{madrasa.reg_number or madrasa.id}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    doc = SimpleDocTemplate(
        response, pagesize=landscape(A4),
        rightMargin=30, leftMargin=30, topMargin=40, bottomMargin=40,
    )
    styles = getSampleStyleSheet()
    elements = []

    fest_name = madrasa.meelad_fest_name or "MEELAD FEST"
    indigo = colors.HexColor('#1E3A8A')
    header_line = colors.HexColor('#4F46E5')
    amber = colors.HexColor('#B45309')

    def add_header(subtitle):
        madrasa_style = ParagraphStyle('HdMadrasa', parent=styles['Normal'],
            fontName='Helvetica-Bold', fontSize=17, leading=21,
            textColor=indigo, alignment=1, spaceAfter=2)
        fest_style = ParagraphStyle('HdFest', parent=styles['Normal'],
            fontName='Helvetica-Bold', fontSize=12, leading=15,
            textColor=amber, alignment=1, spaceAfter=2)
        sub_style = ParagraphStyle('HdSub', parent=styles['Normal'],
            fontName='Helvetica', fontSize=9, leading=12,
            textColor=colors.HexColor('#6B7280'), alignment=1, spaceAfter=4)
        elements.append(Paragraph(madrasa.name.upper(), madrasa_style))
        elements.append(Paragraph(fest_name.upper(), fest_style))
        if madrasa.reg_number:
            elements.append(Paragraph(f"Reg. No: {madrasa.reg_number}", sub_style))
        elements.append(Paragraph(subtitle, sub_style))
        divider = Table([[""]], colWidths=[doc.width])
        divider.setStyle(TableStyle([
            ('LINEBELOW', (0, 0), (-1, -1), 2, header_line),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(divider)
        elements.append(Spacer(1, 12))

    def results_table(prog_list):
        head_style = ParagraphStyle('TblHead', parent=styles['Normal'],
            fontName='Helvetica-Bold', fontSize=9, textColor=colors.white)
        cell_style = ParagraphStyle('TblCell', parent=styles['Normal'],
            fontName='Helvetica', fontSize=9, leading=11)
        pub_style = ParagraphStyle('PubCell', parent=styles['Normal'],
            fontName='Helvetica-Bold', fontSize=9, leading=11)
        data = [[Paragraph('Program', head_style),
                 Paragraph('1st Prize', head_style),
                 Paragraph('2nd Prize', head_style),
                 Paragraph('3rd Prize', head_style),
                 Paragraph('Result', head_style)]]
        for item in prog_list:
            w = item['winners']
            if item.get('published'):
                status = Paragraph('PUBLISHED', pub_style)
            else:
                status = Paragraph('NOT PUBLISHED', cell_style)
            data.append([
                Paragraph(item['title'], cell_style),
                Paragraph(w['first'] or "—", cell_style),
                Paragraph(w['second'] or "—", cell_style),
                Paragraph(w['third'] or "—", cell_style),
                status,
            ])
        col_widths = [doc.width * 0.34, doc.width * 0.15,
                      doc.width * 0.15, doc.width * 0.15,
                      doc.width * 0.21]
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), header_line),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        return t
# ---- Cover page ----
    elements.append(Spacer(1, 70))
    cover_title = ParagraphStyle('CoverTitle', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=24, leading=30,
        textColor=indigo, alignment=1, spaceAfter=8)
    elements.append(Paragraph(fest_name.upper(), cover_title))
    elements.append(Paragraph("OFFICIAL RESULT SHEET", cover_title))
    elements.append(Spacer(1, 10))
    meta_style = ParagraphStyle('CoverMeta', parent=styles['Normal'],
        fontName='Helvetica', fontSize=12, leading=16,
        textColor=colors.HexColor('#4B5563'), alignment=1, spaceAfter=3)
    elements.append(Paragraph(madrasa.name.upper(), meta_style))
    if madrasa.reg_number:
        elements.append(Paragraph(f"Reg. No: {madrasa.reg_number}", meta_style))
    elements.append(Paragraph(
        f"Generated on: {datetime.now().strftime('%d/%m/%Y %I:%M %p')}", meta_style))
    elements.append(PageBreak())

    # ---- Category pages ----
    for section in category_sections:
        cat = section['category']
        add_header("RESULTS — BY CATEGORY")
        cat_title = ParagraphStyle('CatTitle', parent=styles['Normal'],
            fontName='Helvetica-Bold', fontSize=15, leading=19,
            textColor=indigo, alignment=0, spaceAfter=8)
        elements.append(Paragraph(f"Category: {cat.name}", cat_title))

        section_head = ParagraphStyle('SecHead', parent=styles['Normal'],
            fontName='Helvetica-Bold', fontSize=11, leading=14,
            textColor=amber, alignment=0, spaceBefore=4, spaceAfter=6)
        if section['boys']:
            elements.append(Paragraph("BOYS", section_head))
            elements.append(results_table(section['boys']))
            elements.append(Spacer(1, 14))
        if section['girls']:
            elements.append(Paragraph("GIRLS", section_head))
            elements.append(results_table(section['girls']))

        elements.append(PageBreak())

    # ---- General programs page (team-wise results) ----
    add_header("RESULTS — GENERAL")
    cat_title = ParagraphStyle('CatTitle', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=15, leading=19,
        textColor=indigo, alignment=0, spaceAfter=8)
    elements.append(Paragraph("General Programs", cat_title))

    section_head = ParagraphStyle('SecHead', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=11, leading=14,
        textColor=amber, alignment=0, spaceBefore=4, spaceAfter=6)
    if general_section:
        elements.append(Paragraph("TEAM-WISE", section_head))
        elements.append(results_table(general_section))
    else:
        note_style = ParagraphStyle('NoGen', parent=styles['Normal'],
            fontName='Helvetica-Oblique', fontSize=10,
            textColor=colors.HexColor('#6B7280'), alignment=0)
        elements.append(Paragraph("No general programs found.", note_style))

    elements.append(PageBreak())

    # ---- Summary page ----
    add_header("SUMMARY OF TEAM RESULTS (CATEGORY-WISE)")
    sum_head = ParagraphStyle('SumHead', parent=styles['Normal'],
        fontName='Helvetica-Bold', fontSize=8.5, textColor=colors.white)
    sum_cell = ParagraphStyle('SumCell', parent=styles['Normal'],
        fontName='Helvetica', fontSize=8.5, leading=11)

    head_cells = [Paragraph('Rank', sum_head), Paragraph('Team', sum_head)]
    for cat in categories:
        head_cells.append(Paragraph(cat.name, sum_head))
    head_cells.append(Paragraph('General', sum_head))
    head_cells.append(Paragraph('Grand Total', sum_head))

    sdata = [head_cells]
    for row in summary:
        cells = [Paragraph(str(row['rank']), sum_cell),
                 Paragraph(row['team'].name, sum_cell)]
        for cat in categories:
            cells.append(Paragraph(f"{row['cat_totals'].get(cat.id, 0.0):.2f}", sum_cell))
        cells.append(Paragraph(f"{row['general']:.2f}", sum_cell))
        cells.append(Paragraph(f"{row['grand_total']:.2f}", sum_cell))
        sdata.append(cells)

    ncat = max(len(categories), 1)
    rank_w, team_w, gen_w, grand_w = 40, 140, 70, 85
    avail = doc.width - rank_w - team_w - gen_w - grand_w
    cat_w = max(40, int(avail / ncat))
    col_widths = [rank_w, team_w] + [cat_w] * len(categories) + [gen_w, grand_w]

    st = Table(sdata, colWidths=col_widths, repeatRows=1)
    st.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), indigo),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (2, 1), (-1, -1), 'CENTER'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8FAFC')]),
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    # Highlight the 1st position team
    if summary:
        st.setStyle(TableStyle([
            ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#FEF3C7'))
        ]))
    elements.append(st)

    elements.append(Spacer(1, 12))
    note_style = ParagraphStyle('SumNote', parent=styles['Normal'],
        fontName='Helvetica-Oblique', fontSize=9,
        textColor=colors.HexColor('#6B7280'), alignment=1)
    elements.append(Paragraph(
        "Ranking is based on the Grand Total. The 1st position team is highlighted.", note_style))

    doc.build(elements)
    return response



def participant_search(request, program_id):
    q = request.GET.get("q", "")
    participants = (
        Program.objects.get(id=program_id).participants
        .filter(Q(full_name__icontains=q) | Q(code_number__startswith=q))
        .values("id", "full_name", "code_number")[:20]  # limit results
    )
    return JsonResponse({"participants": list(participants)})



def get_program_participants(request, pk):
    program = get_object_or_404(Program, pk=pk)
    participants = program.participants.values("id", "full_name", "code_number", "team__name")
    students = Student.objects.filter(team__madrasa=request.user.madrasa)
    # On a single-section fest the participant picker only lists the active
    # section's students — no girls entries in a boys-only fest and vice versa.
    madrasa = request.user.madrasa
    if madrasa and not madrasa.is_both_sections:
        students = students.filter(gender__in=madrasa.active_genders())
    students = students.values("id", "full_name", "code_number")

    return JsonResponse({
        "title": program.title,
        "participants": list(participants),
        "students": list(students),
    })

@csrf_exempt
def save_program_participants(request, pk):
    program = get_object_or_404(Program, pk=pk)
    if request.method == "POST":
        ids = request.POST.getlist("participants")
        program.participants.set(ids)
        return JsonResponse({"message": "Participants saved successfully!"})
    return JsonResponse({"error": "Invalid request"}, status=400)




@login_required
@csrf_exempt
def save_config(request):
    if request.method == "POST":
        # example fields — you can save to your Config model or Settings table
        first_prize = request.POST.get("first_prize")
        second_prize = request.POST.get("second_prize")
        third_prize = request.POST.get("third_prize")
        grade_a = request.POST.get("grade_a")
        grade_b = request.POST.get("grade_b")
        grade_c = request.POST.get("grade_c")
        max_programs = request.POST.get("max_programs")
        fest_type = request.POST.get("fest_type")

        group_first = request.POST.get("group_first")
        group_second = request.POST.get("group_second")
        group_third = request.POST.get("group_third")
        general_first = request.POST.get("general_first")
        general_second = request.POST.get("general_second")
        general_third = request.POST.get("general_third")

        # Save in your model (pseudo code)
        user = request.user
        madrasa = user.madrasa
        config, _ = ProgramRule.objects.get_or_create(madrasa=madrasa)
        
        positions = {
            'first': first_prize,
            'second': second_prize,
            'third': third_prize,
        }
        for name, mark in positions.items():
            if mark:
                Position.objects.update_or_create(name=name, madrasa=madrasa, defaults={'mark': mark})
        grades = {
            'a_grade': grade_a,
            'b_grade': grade_b,
            'c_grade': grade_c,
        }
        for name, mark in grades.items():
            if mark:
                Grade.objects.update_or_create(name=name, madrasa=madrasa, defaults={'mark': mark})

        group_positions = {
            'first': group_first,
            'second': group_second,
            'third': group_third,
        }
        for name, mark in group_positions.items():
            if mark:
                GroupPosition.objects.update_or_create(name=name, madrasa=madrasa, defaults={'mark': mark})
        general_prizes = {
            'first': general_first,
            'second': general_second,
            'third': general_third,
        }
        for name, mark in general_prizes.items():
            if mark:
                GeneralPosition.objects.update_or_create(name=name, madrasa=madrasa, defaults={'mark': mark})

        config.max_program_per_head = max_programs
        config.save()
        # Persist the fest section structure (both / boys only / girls only)
        # ONLY when the config form actually posts it. The field is optional
        # here — resetting to 'both' whenever it is absent silently undid the
        # fest type the user picked at signup (initial-config runs right
        # after signup, before anything else touches the madrasa).
        if fest_type in dict(Madrasa.FEST_TYPE_CHOICES):
            madrasa.fest_type = fest_type
            madrasa.save(update_fields=["fest_type"])
        user.config_done = True
        user.save()

        return JsonResponse({"status": "success"})



# program register link shortening and redirecting
BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def encode_base62(num):
    if num == 0:
        return BASE62[0]
    base62 = []
    while num > 0:
        num, r = divmod(num, 62)
        base62.append(BASE62[r])
    return ''.join(reversed(base62))


def decode_base62(encoded):
    num = 0
    for char in encoded:
        num = num * 62 + BASE62.index(char)
    return num



def program_reg_short_link_redirect(request, code):
    try:
        institution_id = decode_base62(code)
    except Exception:
        raise Http404("Invalid link")

    final_url = (
        f"/program/student-registration/?institution_id={institution_id}"
    )
    return redirect(final_url)


# ---------------------------------------------------------------------------
# Parents/Students portal — pick team, category, section, then student
# ---------------------------------------------------------------------------
def parents_portal(request, code):
    """Public page where parents/students pick a team -> category -> section -> student."""
    try:
        madrasa_id = decode_base62(code)
        madrasa = Madrasa.objects.get(id=madrasa_id)
    except Exception:
        raise Http404("Invalid link")

    rule = ProgramRule.objects.filter(madrasa=madrasa).last()
    # A generated parent link is open while the flag is active.
    if not (rule and rule.parent_view_link_active):
        raise Http404("This link is no longer active")

    teams = madrasa.team_set.order_by('name')
    categories = Category.objects.filter(madrasa=madrasa).order_by('name')

    context = {
        'madrasa': madrasa,
        'fest_name': madrasa.meelad_fest_name or 'Meelad Fest',
        'teams': teams,
        'categories': categories,
        'code': code,
        'fest_type': madrasa.fest_type,
        'is_boys_only': madrasa.is_boys_only,
        'is_girls_only': madrasa.is_girls_only,
        'is_both_sections': madrasa.is_both_sections,
    }
    return render(request, 'program/parents_portal.html', context)


def student_programs_results(request, code, student_id):
    """Public page showing a single student's programs and (published) results."""
    try:
        madrasa_id = decode_base62(code)
        madrasa = Madrasa.objects.get(id=madrasa_id)
    except Exception:
        raise Http404("Invalid link")

    rule = ProgramRule.objects.filter(madrasa=madrasa).last()
    if not (rule and rule.parent_view_link_active):
        raise Http404("This link is no longer active")

    student = get_object_or_404(Student, id=student_id, team__madrasa=madrasa)
    context = _student_results_context(student, madrasa)
    context['code'] = code
    return render(request, 'program/student_programs_results.html', context)


def _student_results_context(student, madrasa):
    """Shared context builder for the public (shared-link) and the logged-in
    student portal pages — both show the same programs & published results."""
    team = student.team

    # All programs the student is registered for
    programs = student.program_set.all().order_by('title')

    # Build results only for published programs
    results = []
    for program in programs:
        entry = {'program': program, 'published': program.is_result_published}
        prize = None
        if program.is_result_published:
            prize = (
                Prize.objects.filter(student=student, program=program)
                .select_related('position', 'grade', 'group_program_position', 'general_program_position')
                .first()
            )
            # For group/general programmes the prize is stored against the team
            if not prize:
                prize = (
                    Prize.objects.filter(team=team, program=program)
                    .select_related('position', 'grade', 'group_program_position', 'general_program_position')
                    .first()
                )
        entry['prize'] = prize
        results.append(entry)

    total_published = sum(1 for r in results if r['published'])

    return {
        'madrasa': madrasa,
        'fest_name': madrasa.meelad_fest_name or 'Meelad Fest',
        'student': student,
        'team': team,
        'results': results,
        'total_published': total_published,
        'fest_type': madrasa.fest_type,
        'is_boys_only': madrasa.is_boys_only,
        'is_girls_only': madrasa.is_girls_only,
        'is_both_sections': madrasa.is_both_sections,
        # Full team scoring state shared with parents via the sharing link.
        'team_leaderboard': Prize.get_team_leaderboard(madrasa, _fest_section(madrasa)),
    }


# Student portal login (public, code-based) ----------------------------------
# Students log in with their fest code; per the owner's spec the password IS
# the student's code number (code + code login). The session key keeps the
# portal independent from staff/judge accounts, exactly like the judge portal.
STUDENT_PORTAL_SESSION_KEY = "student_portal_id"


def student_login(request):
    """Public login page for the student portal (code + password)."""
    if request.session.get(STUDENT_PORTAL_SESSION_KEY):
        return redirect("student_portal")

    error = None
    code_value = ""
    if request.method == "POST":
        code_value = (request.POST.get("code") or "").strip()
        password = (request.POST.get("password") or "").strip()
        if not code_value or not password:
            error = "Please enter both your code and password."
        else:
            try:
                code_int = int(code_value)
            except ValueError:
                error = "Student code must be a number."
            else:
                # code_number is unique per madrasa, not globally; with a
                # single-fest deployment the first match is the student.
                student = (
                    Student.objects.filter(code_number=code_int)
                    .select_related("team", "team__madrasa", "category")
                    .order_by("id")
                    .first()
                )
                if student is None or password != str(student.code_number):
                    error = "Invalid code or password. Please check with your teacher."
                else:
                    request.session[STUDENT_PORTAL_SESSION_KEY] = student.id
                    request.session.modified = True
                    return redirect("student_portal")
    return render(request, "program/student_login.html", {
        "error": error,
        "code_value": code_value,
    })


def student_logout(request):
    """Leave the student portal (clears only the student session key)."""
    request.session.pop(STUDENT_PORTAL_SESSION_KEY, None)
    request.session.modified = True
    return redirect("student_login")


def _student_portal_student(request):
    """The student logged into the portal via session, or None."""
    student_id = request.session.get(STUDENT_PORTAL_SESSION_KEY)
    if not student_id:
        return None
    return (
        Student.objects.filter(id=student_id)
        .select_related("team", "team__madrasa", "category")
        .first()
    )


def student_portal(request):
    """Logged-in student's homepage: their programs & published results."""
    student = _student_portal_student(request)
    if student is None:
        return redirect("student_login")

    # Resolve the fest the student belongs to (team first, then category).
    madrasa = None
    if student.team_id and student.team:
        madrasa = student.team.madrasa
    elif student.category_id and getattr(student.category, "madrasa", None):
        madrasa = student.category.madrasa
    if madrasa is None:
        request.session.pop(STUDENT_PORTAL_SESSION_KEY, None)
        return redirect("student_login")

    context = _student_results_context(student, madrasa)
    context["student_logged_in"] = True
    return render(request, 'program/student_programs_results.html', context)


   


# for adding program to venue
@login_required
def update_venue_with_program(request, pk):
    venue = get_object_or_404(Venue, id=pk, madrasa=request.user.madrasa)

    if request.method == "POST":
        try:
            body = json.loads(request.body.decode("utf-8"))
            program_ids = body.get("programs", [])
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            return JsonResponse(
                {"status": "error", "message": "Invalid request payload"}, status=400)

        # Convert to integers
        programs = Program.objects.filter(id__in=program_ids).filter(
            program_section_q(request.user.madrasa, _fest_section(request.user.madrasa)))

        venue.program_set.set(programs)

        return JsonResponse({
            "status": "success",
        })

    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)


@login_required
@csrf_exempt
def remove_program_from_venue(request, program_id):
    if request.method == "POST":
        program = get_object_or_404(
            Program, id=program_id, madrasa=request.user.madrasa)
        program.venue = None
        program.save()
        return JsonResponse({"status": "success"})
    return JsonResponse({"status": "error", "message": "Method Not Allowed"}, status=405)



@login_required
def venue_list(request):
    madrasa = getattr(request.user, 'madrasa', None)
    # Venues are always scoped to the logged-in user's madrasa — data from
    # other institutions must never be listed here.
    venues = Venue.objects.filter(madrasa=madrasa) if madrasa else Venue.objects.none()
    total_students = 0
    total_programs = 0
    if madrasa:
        categories = Category.objects.filter(madrasa=madrasa)
        total_students = Student.objects.filter(team__madrasa=madrasa).count()
        total_programs = Program.objects.filter(Q(category__in=categories) | Q(madrasa=madrasa) ).distinct().count()
    # Scheduled-program count per venue, scoped to the active fest section.
    venue_sched_counts = {}
    if madrasa:
        section_programs = Program.objects.filter(program_section_q(madrasa, _fest_section(madrasa)))
        rows = (
            ScheduleEntry.objects.filter(venue__in=venues, fest_day__madrasa=madrasa)
            .filter(program__in=section_programs)
            .values('venue_id')
            .annotate(cnt=Count('id'))
        )
        venue_sched_counts = {r['venue_id']: r['cnt'] for r in rows}
    venues_with_counts = [(v, venue_sched_counts.get(v.id, 0)) for v in venues]
    return render(request, "program/venue_list.html", {
        "venues_with_counts": venues_with_counts,
        "venue_count": venues.count(),
        "total_students": total_students,
        "total_programs": total_programs,
        "meelad_fest_name": getattr(madrasa, 'meelad_fest_name', None),
    })

@login_required
def add_venue(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            if _is_ajax(request):
                return JsonResponse({"ok": False, "error": "Venue name is required."}, status=400)
            messages.error(request, "Venue name is required.")
            return redirect("venue_list")
        Venue.objects.create(
            name=name,
            description=request.POST.get("description") or None,
            madrasa=request.user.madrasa,
        )
        if _is_ajax(request):
            return JsonResponse({
                "ok": True,
                "message": f"Venue '{name}' added successfully.",
                "redirect": reverse("venue_list"),
            })
        messages.success(request, f"Venue '{name}' added successfully.")
        return redirect("venue_list")


@login_required
def edit_venue(request, venue_id):
    venue = get_object_or_404(Venue, id=venue_id, madrasa=request.user.madrasa)
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            if _is_ajax(request):
                return JsonResponse({"ok": False, "error": "Venue name is required."}, status=400)
            messages.error(request, "Venue name is required.")
            return redirect("venue_list")
        venue.name = name
        venue.description = request.POST.get("description") or None
        venue.save()
        if _is_ajax(request):
            return JsonResponse({
                "ok": True,
                "message": f"Venue '{venue.name}' updated.",
                "redirect": reverse("venue_list"),
            })
        messages.success(request, f"Venue '{venue.name}' updated.")
    return redirect("venue_list")


@login_required
def delete_venue(request, venue_id):
    venue = get_object_or_404(Venue, id=venue_id, madrasa=request.user.madrasa)
    # Unschedule any programs at this venue before deleting.
    ScheduleEntry.objects.filter(venue=venue).update(venue=None)
    venue.delete()
    if _is_ajax(request):
        return JsonResponse({
            "ok": True,
            "message": "Venue deleted.",
            "redirect": reverse("venue_list"),
        })
    messages.success(request, "Venue deleted.")
    return redirect("venue_list")


def venue_detail(request, venue_id):
    madrasa = request.user.madrasa
    venue = get_object_or_404(Venue, id=venue_id, madrasa=madrasa)
    # Programs scheduled at this venue from the Schedule board — the schedule
    # entry is the source of truth. Scoped to the active fest section so
    # cross-section strays never surface.
    section_programs = Program.objects.filter(program_section_q(madrasa, _fest_section(madrasa)))
    scheduled_entries = (
        ScheduleEntry.objects.filter(venue=venue, fest_day__madrasa=madrasa)
        .filter(program__in=section_programs)
        .select_related('program', 'fest_day')
        .order_by('fest_day__date', 'start_time', 'id')
    )
    scheduled_rows = []
    for entry in scheduled_entries:
        end_dt = datetime.combine(entry.fest_day.date, entry.start_time) + timedelta(
            minutes=entry.duration_minutes or 0
        )
        scheduled_rows.append({'entry': entry, 'end_time': end_dt.time()})
    # Total distinct participants across programs scheduled at this venue.
    total_participants = Student.objects.filter(
        program__in=[r['entry'].program_id for r in scheduled_rows]
    ).distinct().count()
    return render(request, "program/venue_detail.html", {
        "venue": venue,
        'scheduled_rows': scheduled_rows,
        'total_participants': total_participants,
    })



def download_venue_programs(request, venue_id):
    madrasa = getattr(request.user, 'madrasa', None)
    venue = get_object_or_404(Venue, id=venue_id, madrasa=madrasa) if madrasa else get_object_or_404(Venue, id=venue_id)
    # Source of truth is the Schedule board — get scheduled entries for this
    # venue, scoped to the active fest section so cross-section strays never
    # surface in the report.
    section_programs = Program.objects.filter(program_section_q(madrasa, _fest_section(madrasa))) if madrasa else Program.objects.none()
    scheduled_entries = (
        ScheduleEntry.objects.filter(venue=venue, fest_day__madrasa=madrasa)
        .filter(program__in=section_programs)
        .select_related('program', 'fest_day')
        .prefetch_related('program__participants')
        .order_by('fest_day__date', 'start_time', 'id')
    )

    # HTTP response for PDF
    response = HttpResponse(content_type='application/pdf')
    filename = f"{venue.name}_programs.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    # PDF document
    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        title="Venue Programs Report",
    )

    styles = getSampleStyleSheet()
    elements = []

    # Title
    title = Paragraph(f"{venue.name}: <b>Programs</b>", styles['Title'])
    elements.append(title)
    elements.append(Spacer(1, 12))

    # Table heading
    data = [
        ["SL No", "Program Title", "Category", "Day", "Date", "Time"]
    ]

    # Initialize stats
    category_counts = {}
    total_participants = 0

    body_style = styles['BodyText']
    body_style.fontSize = 9
    body_style.leading = 11

    # Table data — one row per scheduled entry from the Schedule board
    for idx, entry in enumerate(scheduled_entries, start=1):
        program = entry.program
        cat_name = program.program_category() or "-"
        start_label = entry.start_time.strftime("%I:%M %p").lstrip("0")
        end_dt = datetime.combine(entry.fest_day.date, entry.start_time) + timedelta(
            minutes=entry.duration_minutes or 0
        )
        end_label = end_dt.strftime("%I:%M %p").lstrip("0")
        day_label = entry.fest_day.name
        date_label = entry.fest_day.date.strftime("%d/%m/%Y")
        time_label = f"{start_label} - {end_label}"

        data.append([
            idx,
            Paragraph(program.title, body_style),
            Paragraph(cat_name, body_style),
            day_label,
            date_label,
            time_label,
        ])

        # Calc Stats
        stats_cat_name = cat_name if cat_name != "-" else "Uncategorized"
        category_counts[stats_cat_name] = category_counts.get(stats_cat_name, 0) + 1
        total_participants += program.participants.count()

    # Create main table (A4 portrait usable width is ~6.27in; repeat the
    # header row on every page)
    table = Table(
        data,
        colWidths=[0.45*inch, 1.85*inch, 1.05*inch, 0.65*inch, 0.95*inch, 1.3*inch],
        repeatRows=1,
    )

    # Style
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F46E5')), # Indigo header
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),

        ('ALIGN', (0, 0), (-1, -1), 'CENTER'), # Default center alignment
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),    # Left align titles

        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('TOPPADDING', (0, 0), (-1, 0), 12),

        ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.white]),
        ('VALIGN', (0, 1), (-1, -1), 'TOP'),

        # Add some padding to cells
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
    ]))

    elements.append(table)

    # -----------------------------
    # Summary Section for Venue
    # -----------------------------
    elements.append(Spacer(1, 30))

    summary_title = Paragraph("<b>Venue Summary</b>", styles['Heading3'])
    elements.append(summary_title)
    elements.append(Spacer(1, 8))

    # Build summary data
    # Header
    summary_data = [
        ["Category", "Total Programs"]
    ]

    # Rows for each category
    for cat, count in category_counts.items():
        summary_data.append([cat, count])

    # Add spacing or separator row for Total Participants if desired,
    # but here we'll just add it as a special row
    summary_data.append(["", ""]) # Empty row for visual spacing
    summary_data.append(["Total Participants (All Programs)", total_participants])

    # Create Summary Table
    summary_table = Table(summary_data, colWidths=[3.5*inch, 2.5*inch])

    # Styling for Summary
    summary_table.setStyle(TableStyle([
        # Header Row Style
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F46E5')), # Indigo header
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),

        # Data Rows
        ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ('ALIGN', (1, 1), (1, -2), 'CENTER'), # Center program counts

        # Specific style for the last row (Total Participants)
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#E0E7FF')), # Light indigo
        ('ALIGN', (1, -1), (1, -1), 'CENTER'),
    ]))

    elements.append(summary_table)


    # Build PDF
    doc.build(elements)

    return response


@login_required
def download_certificates_pdf(request):
    """Bulk certificates: one A4 landscape page per award.

    Includes Top-3 winners (individual, group and general/team-wise programs)
    and grade (A/B/C) certificates for every published program of the user's
    madrasa, merged into a single PDF.
    """
    madrasa = request.user.madrasa
    if not madrasa:
        return redirect('login')

    # Only published results produce certificates. Group/general programs are
    # scoped via Program.madrasa; individual programs through their category.
    program_ids = list(Program.objects.filter(
        madrasa=madrasa, is_result_published=True,
    ).values_list('id', flat=True))
    category_program_ids = list(Program.objects.filter(
        category__madrasa=madrasa, is_result_published=True,
    ).values_list('id', flat=True))
    allowed = set(program_ids) | set(category_program_ids)

    prizes = (Prize.objects.filter(program_id__in=allowed)
              .select_related(
                  'program', 'student__team', 'team', 'position',
                  'grade', 'group_program_position', 'general_program_position')
              .prefetch_related('participants__team')
              .order_by('program__title', 'id'))

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = (
        'attachment; filename="certificates-%s.pdf"'
        % timezone.now().strftime('%Y%m%d-%H%M%S'))
    doc = SimpleDocTemplate(
        response, pagesize=landscape(A4),
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        title='Meelad Fest Certificates')
    story = []

    indigo = colors.HexColor('#4F46E5')
    styles = getSampleStyleSheet()
    fest_style = ParagraphStyle(
        'CertFestName', parent=styles['Title'], fontName='Helvetica-Bold',
        fontSize=24, textColor=indigo, spaceAfter=4)
    award_kind = ParagraphStyle(
        'CertAwardKind', parent=styles['Normal'], fontName='Helvetica-Bold',
        fontSize=13, textColor=colors.HexColor('#7C3AED'), spaceAfter=18)
    winner = ParagraphStyle(
        'CertWinner', parent=styles['Normal'], fontName='Helvetica-Bold',
        fontSize=20, alignment=1, spaceBefore=10, spaceAfter=6)
    detail = ParagraphStyle(
        'CertDetail', parent=styles['Normal'], fontName='Helvetica',
        fontSize=13, alignment=1, textColor=colors.HexColor('#334155'),
        leading=20)
    footer_style = ParagraphStyle(
        'CertFooterNote', parent=styles['Normal'], fontName='Helvetica-Oblique',
        fontSize=9, textColor=colors.HexColor('#64748B'), alignment=1)

    fest_title = escape(madrasa.meelad_fest_name or 'Meelad Fest')
    POS_KINDS = {'first': ('First Prize', '1st'),
                 'second': ('Second Prize', '2nd'),
                 'third': ('Third Prize', '3rd')}
    PLACE_LABELS = {'first': 'First', 'second': 'Second', 'third': 'Third'}

    for prize in prizes:
        program = prize.program
        # Position label across all program kinds (normalised to lowercase
        # choice values: 'first'/'second'/'third').
        pos_name = None
        if prize.general_program_position:
            pos_name = prize.general_program_position.name
        elif prize.group_program_position:
            pos_name = prize.group_program_position.name
        elif prize.position:
            pos_name = prize.position.name
        grade_name = (prize.grade.get_name_display() if prize.grade else None)

        if pos_name in POS_KINDS:
            kind, place = POS_KINDS[pos_name]
        elif grade_name:
            kind, place = 'Grade Certificate', grade_name
        else:
            continue  # remarks-only prize rows carry no printable award

        # Winner line: individual -> student; group -> member names joined;
        # general/team-wise -> team name.
        if prize.student:
            winner_line = prize.student.full_name
            team_line = prize.student.team.name if prize.student.team else ''
        elif prize.group_program_position:
            winner_line = ' & '.join(
                prize.participants.order_by('id')
                .values_list('full_name', flat=True)) or (
                prize.team.name if prize.team else '')
            team_line = prize.team.name if prize.team else ''
        else:
            winner_line = prize.team.name if prize.team else ''
            team_line = ''

        if story:
            story.append(PageBreak())

        story.append(Paragraph(fest_title, fest_style))
        story.append(Paragraph(kind, award_kind))
        story.append(Paragraph(escape(winner_line), winner))
        if team_line and team_line != winner_line:
            story.append(Paragraph(f'Team: {escape(team_line)}', detail))
        category_name = program.program_category() or ''
        story.append(Paragraph(
            f'Program: {escape(program.title)}'
            + (f' &nbsp;·&nbsp; Category: {escape(category_name)}'
               if category_name else ''),
            detail))
        if pos_name in POS_KINDS:
            story.append(Paragraph(
                f'Awarded <b>{PLACE_LABELS[pos_name]} Prize</b> ({place})',
                detail))
        if grade_name:
            story.append(Paragraph(
                f'Awarded <b>{escape(grade_name)}</b>', detail))
        story.append(Paragraph(
            f'{fest_title} — {escape(madrasa.name)}', footer_style))

    if not story:
        # Friendly single page when nothing is published yet.
        story.append(Paragraph(fest_title, fest_style))
        story.append(Paragraph(
            'No published results yet — publish program results to generate '
            'certificates.', detail))

    doc.build(story)
    return response


# ============================================================================
# JUDGE MANAGEMENT + DIGITAL EVALUATION
# ============================================================================


def _judge_madrasa(request):
    """Resolve the madrasa that owns a judge feature for ``request``.

    Staff/superusers use their own madrasa; a judge (linked login account)
    uses the madrasa of the judge record they belong to. Falls back to the
    user's madrasa for backward compatibility.
    """
    if hasattr(request.user, 'judge_profile') and request.user.judge_profile:
        return request.user.judge_profile.madrasa or request.user.madrasa
    return request.user.madrasa


def _active_judge_for(request):
    """Return the Judge record for a linked judge login, else None."""
    jprofile = getattr(request.user, 'judge_profile', None)
    if jprofile and jprofile.is_active:
        return jprofile
    return None


def _judge_can_access_program(judge, program):
    """True when this judge (or staff) may evaluate ``program``."""
    if judge is None:
        return True  # staff/admin
    return program in judge.programs.all()


def _program_contestants(program, madrasa):
    """Return evaluation contestants for ``program``.

    Individual programs are judged per student participant; general programs
    per team (``general_teams``); group programs per team detected through
    their participant students. Returns (kind, queryset) where kind is
    'student' or 'team'.
    """
    if program.is_general:
        return 'team', program.general_teams.filter(madrasa=madrasa).distinct()
    if program.is_group:
        team_ids = Student.objects.filter(
            program__is_group=True, program=program, team__madrasa=madrasa
        ).values_list('team_id', flat=True).distinct()
        return 'team', Team.objects.filter(id__in=team_ids)
    return 'student', program.participants.filter(team__madrasa=madrasa).distinct()


def _next_judge_code(madrasa):
    """First free judge code for a madrasa, starting from 1000.

    Judge.code is a CharField and codes are unique per madrasa (validated in
    the judges/edit_judge views), so non-numeric codes are ignored when
    picking the next numeric suggestion.
    """
    if madrasa is None:
        return "1000"
    used = set()
    for code in (
        Judge.objects.filter(madrasa=madrasa)
        .exclude(code=None)
        .values_list("code", flat=True)
    ):
        if code and code.isdigit():
            used.add(int(code))
    num = 1000
    while num in used:
        num += 1
    return str(num)


@login_required
def global_search(request):
    """JSON endpoint for the header command palette (Ctrl+K).

    Searches Students, Programs, Venues and Judges for the caller's madrasa
    (never leaks across tenants) and returns grouped results with direct
    URLs so any record can be opened in two keystrokes.
    """
    madrasa = _judge_madrasa(request)
    q = (request.GET.get("q") or "").strip()
    # `total` is part of the payload from the very first keystroke so the
    # palette can always render "no results" consistently.
    out = {"q": q, "students": [], "programs": [], "venues": [], "judges": [],
           "counts": {}, "total": 0}
    # Code numbers are short numeric strings — allow a single-digit query when
    # it is purely numeric (a code lookup); names still need 2+ characters.
    min_len = 1 if q.isdigit() else 2
    if not madrasa or len(q) < min_len:
        return JsonResponse(out)

    limit = 6  # per group — a palette, not a data table
    section_q = program_section_q(madrasa, _fest_section(madrasa))

    students = (Student.objects.filter(team__madrasa=madrasa)
                .filter(Q(full_name__icontains=q) | Q(code_number__icontains=q))
                .select_related("team").order_by("full_name")[:limit])
    out["students"] = [{
        "id": s.id,
        "title": s.full_name,
        "meta": f"Code {s.code_number}" if s.code_number else (s.team.name if s.team else ""),
        "url": reverse("student_profile", args=[s.id]),
    } for s in students]

    programs = (Program.objects.filter(section_q)
                .filter(Q(title__icontains=q) | Q(description__icontains=q))
                .distinct().order_by("title")[:limit])
    program_ids = [p.id for p in programs]
    # Category ↔ Program is M2M, so resolve each program's first category in a
    # single query and link into the category-filtered results page (general
    # programs without any category fall back to the unfiltered listing).
    cat_by_program = dict(
        Category.programs.through.objects.filter(program_id__in=program_ids)
        .values_list("program_id", "category_id"))
    out["programs"] = [{
        "id": p.id,
        "title": p.title,
        "meta": ("Result live" if p.is_result_published else "Result pending"),
        # The results page filters by ?category=, so link into that program's
        # category view rather than an unfiltered listing. (URL name is
        # 'results' — see program/urls.py.)
        "url": reverse("results") + (f"?category={cat_by_program[p.id]}"
                                     if p.id in cat_by_program else ""),
    } for p in programs]

    venues = (Venue.objects.filter(madrasa=madrasa)
              .filter(Q(name__icontains=q) | Q(description__icontains=q))
              .order_by("name")[:limit])
    out["venues"] = [{
        "id": v.id, "title": v.name, "meta": v.description or "Venue",
        "url": reverse("venue_detail", args=[v.id]),
    } for v in venues]

    judges = (Judge.objects.filter(madrasa=madrasa)
              .filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(expertise__icontains=q))
              .order_by("name")[:limit])
    out["judges"] = [{
        "id": j.id, "title": j.name,
        "meta": f"Judge {j.code}" if j.code else "Judge",
        "url": reverse("judge_program_evaluation", args=[j.id, j.programs.first().id])
               if j.programs.exists() else reverse("judges"),
    } for j in judges]

    out["counts"] = {k: len(v) for k, v in out.items() if isinstance(v, list)}
    out["total"] = sum(out["counts"].values())
    return JsonResponse(out)


def judges(request):
    """Judge list + add (page + AJAX). Only staff may manage judges.

    A linked judge login must NOT see the management screen — they only use
    the portal (spec: no student admin, no other programs).
    """
    if _active_judge_for(request):
        raise Http404
    madrasa = _judge_madrasa(request)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            if _is_ajax(request):
                return JsonResponse({"ok": False, "error": "Judge name is required."}, status=400)
            messages.error(request, "Judge name is required.")
            return redirect("judges")
        # Judge codes auto-generate from 1000 when left blank (the form also
        # opens prefilled with the suggestion); explicit codes always win.
        code = (request.POST.get("code") or "").strip() or _next_judge_code(madrasa)
        if Judge.objects.filter(madrasa=madrasa, code=code).exists():
            msg = f"Judge code '{code}' is already assigned to another judge."
            if _is_ajax(request):
                return JsonResponse({"ok": False, "error": msg}, status=400)
            messages.error(request, msg)
            return redirect("judges")
        judge = Judge.objects.create(
            madrasa=madrasa,
            name=name,
            code=code,
            expertise=request.POST.get("expertise", "").strip() or None,
            is_active=request.POST.get("is_active") != "off",
        )
        program_ids = request.POST.getlist("programs")
        if program_ids:
            judge.programs.set(
                Program.objects.filter(id__in=program_ids, madrasa=madrasa)
            )
        # Optional linked login account (judge portal access).
        email = (request.POST.get("email") or "").strip().lower()
        password = request.POST.get("password") or ""
        if email and password:
            User = get_user_model()
            account = User.objects.filter(email__iexact=email).first()
            if account is None:
                account = User.objects.create_user(
                    email=email, password=password, madrasa=None
                )
                # New judge logins are fest staff, not customers — flag them
                # subscribed so no subscription gate blocks the portal.
                account.subscribed = True
            account.set_password(password)
            account.is_active = True
            account.save()
            judge.user = account
            judge.save()
        if _is_ajax(request):
            return JsonResponse({
                "ok": True,
                "message": f"Judge '{judge.name}' added successfully (code {judge.code}).",
                "redirect": reverse("judges"),
            })
        messages.success(request, f"Judge '{judge.name}' added successfully.")
        return redirect("judges")

    judge_list = Judge.objects.filter(madrasa=madrasa).prefetch_related('programs')
    # Per judge: assigned programs + evaluations submitted + unique contestants evaluated.
    rows = []
    for judge in judge_list:
        evals = Evaluation.objects.filter(judge=judge, madrasa=madrasa)
        rows.append({
            'judge': judge,
            'program_count': judge.programs.count(),
            'eval_count': evals.count(),
            'evaluated_contestants': (
                evals.values('student_id').exclude(student_id=None).distinct().count()
                + evals.values('team_id').exclude(team_id=None).distinct().count()
            ),
        })
    section_programs = list(
        Program.objects.filter(program_section_q(madrasa, _fest_section(madrasa))).distinct()
    )
    # The criteria editor is grouped by category so organisers can find a
    # program's marking sheet quickly. Programs with no category link
    # (general/team-wise programs, or groups created without a category)
    # fall into the "Uncategorised" group at the end.
    scoped = {p.id: p for p in section_programs}
    grouped_ids = set()
    criteria_groups = []
    for cat in (Category.objects.filter(madrasa=madrasa).order_by("name")
                .prefetch_related("programs", "programs_for_girls")):
        seen = set()
        cat_programs = []
        for p in list(cat.programs.all()) + list(cat.programs_for_girls.all()):
            if p.id in scoped and p.id not in seen:
                seen.add(p.id)
                cat_programs.append(scoped[p.id])
        if cat_programs:
            grouped_ids.update(p.id for p in cat_programs)
            criteria_groups.append({"category": cat, "programs": cat_programs})
    leftovers = [p for p in section_programs if p.id not in grouped_ids]
    if leftovers:
        criteria_groups.append({"category": None, "programs": leftovers})
    return render(request, "program/judges.html", {
        "judge_rows": rows,
        "programs": section_programs,
        "criteria_groups": criteria_groups,
        "meelad_fest_name": madrasa.meelad_fest_name if madrasa else None,
    })


@require_POST
@login_required
def edit_judge(request, judge_id):
    """Update a judge (page redirect + AJAX)."""
    if _active_judge_for(request):
        raise Http404
    madrasa = _judge_madrasa(request)
    judge = get_object_or_404(Judge, id=judge_id, madrasa=madrasa)
    name = request.POST.get("name", "").strip()
    if not name:
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": "Judge name is required."}, status=400)
        messages.error(request, "Judge name is required.")
        return redirect("judges")
    judge.name = name
    # The judge form no longer edits codes (backend-managed, auto-assigned
    # from 1000) — honour an explicitly posted code, otherwise keep the
    # existing one instead of wiping it.
    code = (request.POST.get("code") or "").strip()
    if code:
        if Judge.objects.filter(madrasa=madrasa, code=code).exclude(pk=judge.pk).exists():
            msg = f"Judge code '{code}' is already assigned to another judge."
            if _is_ajax(request):
                return JsonResponse({"ok": False, "error": msg}, status=400)
            messages.error(request, msg)
            return redirect("judges")
        judge.code = code
    judge.expertise = request.POST.get("expertise", "").strip() or None
    judge.is_active = request.POST.get("is_active") != "off"
    judge.save()
    program_ids = request.POST.getlist("programs")
    judge.programs.set(Program.objects.filter(id__in=program_ids, madrasa=madrasa))
    if _is_ajax(request):
        return JsonResponse({
            "ok": True,
            "message": f"Judge '{judge.name}' updated successfully.",
            "redirect": reverse("judges"),
        })
    messages.success(request, f"Judge '{judge.name}' updated successfully.")
    return redirect("judges")


@require_POST
@login_required
def delete_judge(request, judge_id):
    """Delete a judge."""
    if _active_judge_for(request):
        raise Http404
    madrasa = _judge_madrasa(request)
    judge = get_object_or_404(Judge, id=judge_id, madrasa=madrasa)
    judge.delete()
    if _is_ajax(request):
        return JsonResponse({
            "ok": True,
            "message": "Judge deleted.",
            "redirect": reverse("judges"),
        })
    messages.success(request, "Judge deleted.")
    return redirect("judges")


@require_POST
def save_program_evaluation_criteria(request, program_id):
    """Set the marking criteria + max marks for a program (admin)."""
    if _active_judge_for(request):
        raise Http404
    madrasa = _judge_madrasa(request)
    program = get_object_or_404(
        Program.objects.filter(program_section_q(madrasa, _fest_section(madrasa))).distinct(),
        id=program_id,
    )
    program.evaluation_criteria.all().delete()
    names = request.POST.getlist("criterion_name")
    marks = request.POST.getlist("criterion_max")
    added = 0
    for name, mark in zip(names, marks):
        name = (name or "").strip()
        if not name:
            continue
        try:
            max_marks = float(mark or 0)
        except (TypeError, ValueError):
            max_marks = 10.0
        if max_marks <= 0:
            max_marks = 10.0
        EvaluationCriterion.objects.create(
            program=program, name=name, max_marks=max_marks
        )
        added += 1
    if _is_ajax(request):
        return JsonResponse({
            "ok": True,
            "message": f"{added} criterion saved for '{program.title}'.",
        })
    messages.success(request, f"{added} criterion saved.")
    return redirect("judges")


@login_required
def judge_portal(request):
    """Judge dashboard: assigned programs with evaluation progress."""
    madrasa = _judge_madrasa(request)
    judge = _active_judge_for(request)
    is_staff = request.user.is_staff or request.user.is_superuser

    # A linked judge sees only their programs; staff may pick a judge.
    if judge is None and not is_staff:
        raise Http404
    if judge is None:
        judge_id = request.GET.get("judge_id")
        judge = Judge.objects.filter(id=judge_id, madrasa=madrasa).first()

    programs = (
        judge.programs.filter(program_section_q(madrasa, _fest_section(madrasa))).distinct()
        if judge else Program.objects.none()
    )
    rows = []
    for program in programs:
        contestants = _program_contestants(program, madrasa)
        total = contestants[1].count()
        if contestants[0] == 'student':
            evaluated = Evaluation.objects.filter(
                judge=judge, program=program, madrasa=madrasa
            ).exclude(student_id=None).values('student_id').distinct().count()
        else:
            evaluated = Evaluation.objects.filter(
                judge=judge, program=program, madrasa=madrasa
            ).exclude(team_id=None).values('team_id').distinct().count()
        rows.append({
            'program': program,
            'contestant_kind': contestants[0],
            'total_contestants': total,
            'evaluated': evaluated,
            'progress': (round(evaluated / total * 100) if total else 0),
        })
    judges_all = Judge.objects.filter(madrasa=madrasa) if is_staff else Judge.objects.none()
    return render(request, "program/judge_portal.html", {
        "judge": judge,
        "rows": rows,
        "judges_all": judges_all,
        "is_staff": is_staff,
        "meelad_fest_name": madrasa.meelad_fest_name if madrasa else None,
    })


@login_required
def judge_program_evaluation(request, judge_id, program_id):
    """Digital evaluation sheet for one judge + program."""
    madrasa = _judge_madrasa(request)
    judge = get_object_or_404(Judge, id=judge_id, madrasa=madrasa)
    program = get_object_or_404(
        Program.objects.filter(program_section_q(madrasa, _fest_section(madrasa))).distinct(),
        id=program_id,
    )
    # A linked judge may only evaluate their assigned programs; staff may preview any.
    judge_user = _active_judge_for(request)
    if judge_user and judge_user != judge:
        raise Http404
    if judge_user and program not in judge.programs.all():
        raise Http404

    criteria = program.evaluation_criteria.all()
    contestants = _program_contestants(program, madrasa)
    kind, qs = contestants
    rows = []
    for contestant in qs:
        ev = Evaluation.objects.filter(
            judge=judge, program=program, madrasa=madrasa,
            **({f'{kind}_id': contestant.id} if contestant else {})
        ).first()
        rows.append({
            'contestant': contestant,
            'scores': ev.get_scores() if ev else {},
            'total': ev.total_marks if ev else 0,
            'evaluated': bool(ev),
        })
    return render(request, "program/judge_program_evaluation.html", {
        "judge": judge,
        "program": program,
        "criteria": criteria,
        "rows": rows,
        "contestant_kind": kind,
        "meelad_fest_name": madrasa.meelad_fest_name if madrasa else None,
    })


@require_POST
@login_required
def judge_save_evaluation(request, judge_id, program_id):
    """Save (upsert) one judge's evaluation for one contestant, AJAX JSON."""
    madrasa = _judge_madrasa(request)
    judge = get_object_or_404(Judge, id=judge_id, madrasa=madrasa)
    program = get_object_or_404(
        Program.objects.filter(program_section_q(madrasa, _fest_section(madrasa))).distinct(),
        id=program_id,
    )
    judge_user = _active_judge_for(request)
    if judge_user and judge_user != judge:
        return JsonResponse({"ok": False, "error": "Not your evaluation sheet."}, status=403)
    if judge_user and program not in judge.programs.all():
        return JsonResponse({"ok": False, "error": "Program not assigned to you."}, status=403)

    kind = request.POST.get("contestant_kind", "student")
    contestant_id = request.POST.get("contestant_id")
    if not contestant_id:
        return JsonResponse({"ok": False, "error": "Missing contestant id."}, status=400)

    scores = {}
    for key, raw in request.POST.items():
        if not key.startswith("score_"):
            continue
        criterion_id = key[len("score_"):]
        try:
            scores[int(criterion_id)] = float(raw or 0)
        except (TypeError, ValueError):
            continue
    total = round(sum(scores.values()), 2)

    contestant = None
    if kind == "team":
        contestant = get_object_or_404(Team, id=contestant_id)
    else:
        contestant = get_object_or_404(Student, id=contestant_id)

    import json as _json
    ev, _ = Evaluation.objects.update_or_create(
        defaults={
            "scores": _json.dumps(scores),
            "total_marks": total,
            "student": contestant if kind == "student" else None,
            "team": contestant if kind == "team" else None,
        },
        judge=judge, program=program, madrasa=madrasa,
        student=contestant if kind == "student" else None,
        team=contestant if kind == "team" else None,
    )
    return JsonResponse({
        "ok": True,
        "message": f"Saved {program.title} — {getattr(contestant, 'full_name', None) or getattr(contestant, 'name', '?')} → {total:g}",
        "total": total,
    })


@login_required
def judge_program_rankings(request, program_id):
    """Aggregated rankings across all active judges for a program."""
    madrasa = _judge_madrasa(request)
    program = get_object_or_404(
        Program.objects.filter(program_section_q(madrasa, _fest_section(madrasa))).distinct(),
        id=program_id,
    )
    ranked = Evaluation.rankings(program, madrasa)
    return render(request, "program/judge_rankings.html", {
        "program": program,
        "ranked": ranked,
        "meelad_fest_name": madrasa.meelad_fest_name if madrasa else None,
    })


@require_POST
@login_required
def judge_publish_rankings(request, program_id):
    """Promote top-3 averaged rankings into Prize rows (auto result)."""
    madrasa = _judge_madrasa(request)
    program = get_object_or_404(
        Program.objects.filter(program_section_q(madrasa, _fest_section(madrasa))).distinct(),
        id=program_id,
    )
    ranked = Evaluation.rankings(program, madrasa)[:3]
    if not ranked:
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": "No evaluations yet to rank."}, status=400)
        messages.error(request, "No evaluations yet to rank.")
        return redirect("judge_program_rankings", program_id=program.id)

    position_names = ["first", "second", "third"]
    created = 0
    for rank, row in enumerate(ranked, start=1):
        if row["avg"] <= 0:
            continue
        if program.is_general:
            pos, _ = GeneralPosition.objects.get_or_create(
                name=position_names[rank - 1], madrasa=madrasa
            )
            Prize.objects.update_or_create(
                defaults={"general_program_position": pos, "remarks": f"Auto from judging (avg {row['avg']:g})."},
                team=row["team"], program=program,
            )
        elif program.is_group:
            pos, _ = GroupPosition.objects.get_or_create(
                name=position_names[rank - 1], madrasa=madrasa
            )
            Prize.objects.update_or_create(
                defaults={"group_program_position": pos, "remarks": f"Auto from judging (avg {row['avg']:g})."},
                team=row["team"], program=program,
            )
        else:
            pos, _ = Position.objects.get_or_create(
                name=position_names[rank - 1], madrasa=madrasa
            )
            Prize.objects.update_or_create(
                defaults={"position": pos, "remarks": f"Auto from judging (avg {row['avg']:g})."},
                student=row["student"], program=program,
            )
        created += 1
    if _is_ajax(request):
        return JsonResponse({
            "ok": True,
            "message": f"Published {created} result(s) for '{program.title}'.",
            "redirect": reverse("judge_program_rankings", kwargs={"program_id": program.id}),
        })
    messages.success(request, f"Published {created} result(s).")
    return redirect("judge_program_rankings", program_id=program.id)
