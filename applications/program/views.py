import json
import csv

from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, Image
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

from datetime import datetime

from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl import load_workbook

# from xhtml2pdf import pisa

from django.shortcuts import render, get_object_or_404, redirect
from django.views import generic, View
from django.http import HttpResponseRedirect, FileResponse, HttpResponse, JsonResponse, Http404
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.template.loader import get_template
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Case, When, Value, BooleanField, Q, Sum
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from django.shortcuts import redirect, get_object_or_404

from applications.scoreboard.models import Team
from applications.program.models import Category, Program, Student, Prize, Position, Grade, GroupPosition, GeneralPosition, \
    ProgramRule, Venue
from .forms import CategoryForm, ProgramForm, StudentForm
from applications.accounts.models import Madrasa


@csrf_exempt
def register_program(request):
    if request.method == 'POST':
        student_id = request.POST.get('student')
        program_ids = request.POST.getlist('programs[]') or request.POST.getlist('programs')

        if not student_id or not program_ids:
            return JsonResponse({"message": "error", "details": "Missing student or programs"})

        try:
            student = Student.objects.get(id=student_id)
            programs = Program.objects.filter(id__in=program_ids)

            # for program in programs:
            #     program.participants.add(student)
            student.program_set.set(programs)

            program_names = list(student.program_set.values_list('title', flat=True))

            return JsonResponse({"message": "success", "programs": program_names})
        except Student.DoesNotExist:
            return JsonResponse({"message": "error", "details": "Invalid student"})
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
    team_id = request.GET.get('team')  # Get team_id from request

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
        team_id = self.request.GET.get('team')
        context['team_name'] = Team.objects.get(id=team_id).name
        context['team_id'] = team_id

        user = self.request.user
        madrasa = user.madrasa
        context['meelad_fest_name'] = madrasa.meelad_fest_name if user.madrasa else None
        context["total_students"] = Student.objects.filter(team__madrasa=madrasa).count()
        categories = Category.objects.filter(madrasa=madrasa)
        context["total_programs"] = Program.objects.filter(category__in=categories).distinct().count()

        return context


class AddCategoryView(LoginRequiredMixin, View):
    template_name = 'program/category.html'

    def get(self, request):
        form = CategoryForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = CategoryForm(request.POST)
        team_id = request.GET.get('team')
        if form.is_valid():
            category = form.save(commit=False)
            category.madrasa = request.user.madrasa
            category.save()
            form.save_m2m()
            url = f"{reverse('categories')}?team={team_id}"  # reverse() gets the URL from name
            return redirect(url)
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
        team_id = self.request.GET.get('team')
        if form.is_valid():
            form.save()
            url = f"{reverse('categories')}?team={team_id}"  # reverse() gets the URL from name
            return redirect(url)
        return render(request, self.template_name, {"form": form, "category": category})


class CategoryDetailView(generic.DetailView):
    model = Category
    template_name = "program/category_detail.html"
    context_object_name = "category"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        category = self.get_object()

        # related objects
        team_id = self.request.GET.get("team")
        try:
            team_obj = Team.objects.get(id=team_id)
            context['team_name'] = team_obj.name
            context['team_id'] = team_id
            madrasa_id = team_obj.madrasa.id
            context['madrasa_id'] = madrasa_id
            rule = ProgramRule.objects.filter(madrasa_id=madrasa_id).last()
            context['reg_link_active'] = False
            if rule:
                context['reg_link_active'] = rule.program_reg_link_active
        except:
            pass

        host_url = f"{self.request.scheme}://{self.request.get_host()}"
        context['category_url'] = f'{host_url}/program/categories?team={team_id}'
        context["boys"] = Student.objects.filter(category=category, gender='male', team_id=team_id).order_by('-total_point')
        context['girls'] = Student.objects.filter(category=category, gender='female', team_id=team_id).order_by('-total_point')

        general_programs = Program.objects.filter(is_general=True)
        boys_programs = (category.programs.all() | general_programs).distinct()
        girls_programs = (category.programs_for_girls.all() | general_programs).distinct()
        context["boys_stage_programs"] = boys_programs.filter(non_stage=False)
        context["boys_non_stage_programs"] = boys_programs.filter(non_stage=True)
        context['boys_programs'] = boys_programs
        context['girls_programs'] = girls_programs

        context["girls_stage_programs"] = girls_programs.filter(non_stage=False)
        context["girls_non_stage_programs"] = girls_programs.filter(non_stage=True)

        # forms (empty forms for GET)
        context["student_form"] = kwargs.get("student_form") or StudentForm()
        context["program_form"] = kwargs.get("program_form") or ProgramForm()

        institution_id = self.request.user.madrasa.id
        encoded = encode_base62(institution_id) 
        scheme = "https" if self.request.is_secure() else "http"
        host = self.request.META.get('HTTP_HOST')
        short_link = f"{scheme}://{host}/x/{encoded}"
        # context["form_url"] = f'{host_url}/program/student-registration/?institution_id={institution_id}'
        context['form_url'] = short_link

        user = self.request.user
        madrasa = user.madrasa
        context['meelad_fest_name'] = madrasa.meelad_fest_name if user.madrasa else None
        context["total_students"] = Student.objects.filter(team__madrasa=madrasa).count()
        categories = Category.objects.filter(madrasa=madrasa)
        context["total_programs"] = Program.objects.filter(category__in=categories).distinct().count()

        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()  # required for DetailView
        category = self.object
        team_id = request.GET.get("team")
        team = Team.objects.get(id=team_id) if team_id else None

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
                return redirect(url)
            else:
                errors = student_form.errors.as_text()
                # print(errors)
                context = self.get_context_data(student_form=student_form)
                context['errors'] = errors
                return self.render_to_response(context)

        elif "program_form" in request.POST:
            program_form = ProgramForm(request.POST)
            if program_form.is_valid():
                program = program_form.save(commit=False)
                program.save()
                gender = request.POST.get('gender')
                if not program.is_general:
                    if gender == 'male':
                        category.programs.add(program)
                    elif gender == 'female':
                        category.programs_for_girls.add(program)
                url = reverse("category_detail", kwargs={"pk": category.pk})
                # Add query param
                if team_id:
                    url = f"{url}?team={team_id}"
                return redirect(url)
            return self.render_to_response(
                self.get_context_data(program_form=program_form)
            )

        # fallback
        return self.get(request, *args, **kwargs)


class AddProgramToStudentView(View):
    def post(self, request, *args, **kwargs):
        student_id = self.kwargs.get("student_id")
        student = get_object_or_404(Student, id=student_id)

        program_ids = request.POST.getlist("programs")  # multi-select
        programs = Program.objects.filter(id__in=program_ids)

        # reset student programs
        student.program_set.set(programs)

        # for program in programs:
        #     program.participants.add(student)

        # Redirect back to the same page or student detail page
        team_id = student.team.id if student.team else None
        next_url = request.GET.get("next", reverse("category_detail", kwargs={"pk": student.category.pk}))

        if team_id:
            # append ?team=ID if no query params exist, otherwise add &team=ID
            connector = "&" if "?" in next_url else "?"
            next_url = f"{next_url}{connector}team={team_id}"
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
            program_rule = ProgramRule.objects.filter(madrasa_id=madrasa_id).last()
            if program_rule:
                context['max_programs'] = program_rule.max_program_per_head
            else:
                context['max_programs'] = 3
        else:
            context['madrasa_name'] = None

        return context
    
    def get(self, request, *args, **kwargs):
        madrasa_id = self.request.GET.get('institution_id')
        program_rule = ProgramRule.objects.filter(madrasa_id=madrasa_id).last()
        if program_rule and not program_rule.program_reg_link_active:
            return HttpResponse("Link expired!")
        return super().get(request, *args, **kwargs)


class ProgramListView(generic.ListView):
    queryset = Program.objects.filter(non_stage=False)
    template_name = 'program/program_list.html'
    context_object_name = 'stage_programs'

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        request = self.request
        madrasa_id = request.user.madrasa.id
        context['non_stage_programs'] = Program.objects.filter(non_stage=True)
        context['categories'] = Category.objects.filter(madrasa_id=madrasa_id)

        try:
            categories = Category.objects.filter(madrasa_id=madrasa_id)
            context["total_students"] = Student.objects.filter(team__madrasa_id=madrasa_id).count()
            context["total_programs"] = Program.objects.filter(category__in=categories).distinct().count()
            context['meelad_fest_name'] = Madrasa.objects.get(id=madrasa_id).meelad_fest_name
        except:
            pass


        host_url = f"{request.scheme}://{request.get_host()}"
        context["form_url"] = f'{host_url}/program/student-registration/?institution_id={madrasa_id}'
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




def download_results_poster_pdf(request, program_id, section):
    program = get_object_or_404(Program, id=program_id)
    madrasa = request.user.madrasa

    # Determine category
    if section == 'boys':
        category = program.category_set.filter(madrasa=madrasa).first()
    else:
        category = program.girls_categories.filter(madrasa=madrasa).first()

    category_name = category.name if category else "-"

    # Get results (Prizes filter)
    prizes = Prize.objects.filter(program=program).select_related(
        'student__team', 'team', 'position', 'grade',
        'group_program_position', 'general_program_position'
    )

    first_winner = None
    second_winner = None
    third_winner = None
    a_grades = []
    b_grades = []
    c_grades = []

    for prize in prizes:
        pos_name = None
        if program.is_general and prize.general_program_position:
            pos_name = prize.general_program_position.name
        elif program.is_group and prize.group_program_position:
            pos_name = prize.group_program_position.name
        elif prize.position:
            pos_name = prize.position.name

        if prize.student:
            winner_name = prize.student.full_name
            team_name = prize.student.team.name if prize.student.team else ""
        elif prize.team:
            winner_name = ""
            team_name = prize.team.name
        else:
            continue

        if team_name:
            display_name = f"{winner_name} ({team_name})" if winner_name else team_name
        else:
            display_name = winner_name

        if pos_name == 'first':
            first_winner = display_name
        elif pos_name == 'second':
            second_winner = display_name
        elif pos_name == 'third':
            third_winner = display_name

        if prize.grade:
            grade_name = prize.grade.name
            if grade_name == 'a_grade':
                a_grades.append(display_name)
            elif grade_name == 'b_grade':
                b_grades.append(display_name)
            elif grade_name == 'c_grade':
                c_grades.append(display_name)

    # HTTP response for PDF
    response = HttpResponse(content_type='application/pdf')
    filename = f"poster_{program.slug}_{section}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    # SimpleDocTemplate with A4 Portrait
    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40
    )

    styles = getSampleStyleSheet()
    elements = []

    # 1. Madrasa Name
    styles.add(ParagraphStyle(
        name='PosterMadrasa',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=colors.HexColor('#1E3A8A'),
        alignment=1, # Center
        spaceAfter=4 if getattr(madrasa, 'reg_number', None) else 12
    ))
    elements.append(Paragraph(madrasa.name.upper(), styles['PosterMadrasa']))

    if getattr(madrasa, 'reg_number', None):
        styles.add(ParagraphStyle(
            name='PosterRegNo',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=11,
            leading=13,
            textColor=colors.HexColor('#4B5563'),
            alignment=1, # Center
            spaceAfter=12
        ))
        elements.append(Paragraph(f"Reg. No: {madrasa.reg_number}", styles['PosterRegNo']))

    # 2. Fest Name Badge
    fest_name = madrasa.meelad_fest_name or "MEELAD FEST"
    badge_style = ParagraphStyle(
        name='PosterFest',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=15,
        leading=18,
        textColor=colors.white,
        alignment=1,
    )
    badge_table = Table([[Paragraph(fest_name.upper(), badge_style)]], colWidths=[300])
    badge_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#D97706')), # Gold/Amber/Bronze style
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 12),
        ('RIGHTPADDING', (0,0), (-1,-1), 12),
    ]))
    badge_table.hAlign = 'CENTER'
    elements.append(badge_table)
    elements.append(Spacer(1, 20))

    # 3. Sub-header / Divider
    line_data = [[""]]
    line_table = Table(line_data, colWidths=[450])
    line_table.setStyle(TableStyle([
        ('LINEBELOW', (0,0), (-1,-1), 2, colors.HexColor('#E2E8F0')),
        ('BOTTOMPADDING', (0,0), (-1,-1), 0),
        ('TOPPADDING', (0,0), (-1,-1), 0),
    ]))
    line_table.hAlign = 'CENTER'
    elements.append(line_table)
    elements.append(Spacer(1, 15))

    # 4. Result Title
    styles.add(ParagraphStyle(
        name='PosterAnnounce',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=14,
        textColor=colors.HexColor('#D97706'),
        alignment=1,
        spaceAfter=15
    ))
    elements.append(Paragraph("RESULT ANNOUNCEMENT", styles['PosterAnnounce']))

    # 5. Program Title
    styles.add(ParagraphStyle(
        name='PosterProgramTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=26,
        leading=30,
        textColor=colors.HexColor('#1E3A8A'),
        alignment=1,
        spaceAfter=8
    ))
    elements.append(Paragraph(program.title, styles['PosterProgramTitle']))

    # 6. Category & Section
    styles.add(ParagraphStyle(
        name='PosterMeta',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=15,
        textColor=colors.HexColor('#4B5563'),
        alignment=1,
        spaceAfter=25
    ))
    meta_text = f"Category: {category_name}   |   Section: {section.upper()}"
    elements.append(Paragraph(meta_text, styles['PosterMeta']))

    # 7. Winners table
    winner_label_style = ParagraphStyle(
        name='WinnerLabel',
        fontName='Helvetica-Bold',
        fontSize=14,
        textColor=colors.white,
        alignment=0, # Left
    )
    winner_val_style = ParagraphStyle(
        name='WinnerValue',
        fontName='Helvetica-Bold',
        fontSize=14,
        textColor=colors.HexColor('#1F2937'),
        alignment=0, # Left
    )

    t_data = []

    if first_winner:
        t_data.append([
            Paragraph("1st PRIZE", winner_label_style),
            Paragraph(first_winner, winner_val_style)
        ])
    if second_winner:
        t_data.append([
            Paragraph("2nd PRIZE", winner_label_style),
            Paragraph(second_winner, winner_val_style)
        ])
    if third_winner:
        t_data.append([
            Paragraph("3rd PRIZE", winner_label_style),
            Paragraph(third_winner, winner_val_style)
        ])

    if t_data:
        winners_table = Table(t_data, colWidths=[120, 320])
        # Build TableStyle commands dynamically based on actual rows
        ts_commands = [
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('TOPPADDING', (0,0), (-1,-1), 10),
            ('BOTTOMPADDING', (0,0), (-1,-1), 10),
            ('LEFTPADDING', (0,0), (-1,-1), 12),
            ('RIGHTPADDING', (0,0), (-1,-1), 12),
            ('LINEBELOW', (0,0), (-1,-1), 1, colors.HexColor('#F3F4F6')),
        ]
        
        bg_styles = {
            0: (colors.HexColor('#D97706'), colors.HexColor('#FEF3C7')), # 1st (Gold / Light Amber)
            1: (colors.HexColor('#78716C'), colors.HexColor('#F3F4F6')), # 2nd (Slate / Light Silver)
            2: (colors.HexColor('#B45309'), colors.HexColor('#FFEDD5')), # 3rd (Bronze / Light Bronze)
        }
        
        for idx in range(len(t_data)):
            if idx in bg_styles:
                label_bg, val_bg = bg_styles[idx]
                ts_commands.append(('BACKGROUND', (0, idx), (0, idx), label_bg))
                ts_commands.append(('BACKGROUND', (1, idx), (1, idx), val_bg))
                
        winners_table.setStyle(TableStyle(ts_commands))
        winners_table.hAlign = 'CENTER'
        elements.append(winners_table)
    else:
        no_winners_style = ParagraphStyle(
            name='NoWinners',
            fontName='Helvetica-Oblique',
            fontSize=14,
            textColor=colors.red,
            alignment=1,
        )
        elements.append(Paragraph("Results processed but no winners assigned.", no_winners_style))

    elements.append(Spacer(1, 30))

    # 8. Grades list if any exist
    grades_awarded = False
    grade_elements = []

    grades_title_style = ParagraphStyle(
        name='GradesTitle',
        fontName='Helvetica-Bold',
        fontSize=14,
        textColor=colors.HexColor('#1E3A8A'),
        alignment=1,
        spaceAfter=10
    )
    grade_text_style = ParagraphStyle(
        name='GradeText',
        fontName='Helvetica',
        fontSize=12,
        leading=15,
        textColor=colors.HexColor('#374151'),
        alignment=1,
        spaceAfter=6
    )

    if a_grades or b_grades or c_grades:
        grades_awarded = True
        grade_elements.append(Paragraph("<b>GRADE ACHIEVERS</b>", grades_title_style))
        if a_grades:
            grade_elements.append(Paragraph(f"<b>A Grade:</b> {', '.join(a_grades)}", grade_text_style))
        if b_grades:
            grade_elements.append(Paragraph(f"<b>B Grade:</b> {', '.join(b_grades)}", grade_text_style))
        if c_grades:
            grade_elements.append(Paragraph(f"<b>C Grade:</b> {', '.join(c_grades)}", grade_text_style))

    if grades_awarded:
        grade_box = Table([[grade_elements]], colWidths=[440])
        grade_box.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#E2E8F0')),
            ('TOPPADDING', (0,0), (-1,-1), 12),
            ('BOTTOMPADDING', (0,0), (-1,-1), 12),
            ('LEFTPADDING', (0,0), (-1,-1), 15),
            ('RIGHTPADDING', (0,0), (-1,-1), 15),
        ]))
        grade_box.hAlign = 'CENTER'
        elements.append(grade_box)
        elements.append(Spacer(1, 20))

    # 9. Signatures Block
    elements.append(Spacer(1, 40))

    sadr_name = madrasa.sadr or ""
    convenor_name_1 = getattr(madrasa, 'convenor_name_1', None) or ""
    convenor_name_2 = getattr(madrasa, 'convenor_name_2', None) or ""

    signature_image = None
    if getattr(madrasa, 'sadr_signature', None) and getattr(madrasa.sadr_signature, 'name', None):
        # reportlab Image expects filesystem access via open storage path
        try:
            signature_path = madrasa.sadr_signature.path
            if signature_path:
                signature_image = Image(signature_path, width=105, height=38)
        except Exception:
            signature_image = None

    sig_lines = [
        ["", ""],
        ["", ""],
    ]

    if signature_image:
        sig_lines[0] = [signature_image, ""]
    else:
        sig_lines[0] = ["_________________________", "_________________________"]

    sig_lines[1] = [
        Paragraph("<b>Madrasa Sadr</b>", ParagraphStyle(name='SigL', fontName='Helvetica', fontSize=11, textColor=colors.HexColor('#4B5563'))),
        Paragraph("<b>Convenor / Authority</b>", ParagraphStyle(name='SigR', fontName='Helvetica', fontSize=11, textColor=colors.HexColor('#4B5563')))
    ]

    if sadr_name:
        sig_lines.insert(2, [
            Paragraph(sadr_name, ParagraphStyle(name='SadrName', fontName='Helvetica-Bold', fontSize=11, textColor=colors.HexColor('#1E3A8A'))),
            ""
        ])

    if convenor_name_1 or convenor_name_2:
        convenor_text = " / ".join([n for n in [convenor_name_1, convenor_name_2] if n])
        sig_lines.append([
            "",
            Paragraph(convenor_text, ParagraphStyle(name='ConvenorName', fontName='Helvetica-Bold', fontSize=10, textColor=colors.HexColor('#1E3A8A')))
        ])
    
    sig_table = Table(sig_lines, colWidths=[220, 220])
    sig_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2),
        ('TOPPADDING', (0,0), (-1,-1), 2),
    ]))
    sig_table.hAlign = 'CENTER'
    elements.append(sig_table)

    def draw_poster_frame(canvas, doc):
        canvas.saveState()
        w, h = doc.pagesize

        # Primary Outer Gold elegant border
        canvas.setStrokeColor(colors.HexColor("#D97706")) # Gold
        canvas.setLineWidth(4)
        canvas.rect(15, 15, w - 30, h - 30)

        # Thin inner Navy border
        canvas.setStrokeColor(colors.HexColor("#1E3A8A")) # Navy
        canvas.setLineWidth(1)
        canvas.rect(20, 20, w - 40, h - 40)

        # Corner decorations
        canvas.setFillColor(colors.HexColor("#D97706")) # Gold
        # Top-Left
        canvas.rect(15, h - 35, 20, 20, fill=True, stroke=False)
        # Top-Right
        canvas.rect(w - 35, h - 35, 20, 20, fill=True, stroke=False)
        # Bottom-Left
        canvas.rect(15, 15, 20, 20, fill=True, stroke=False)
        # Bottom-Right
        canvas.rect(w - 35, 15, 20, 20, fill=True, stroke=False)

        # Developer credit — small footer text bottom center
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#9CA3AF"))  # Tailwind gray-400
        footer_text = "Powered by Team Mahara  |  9544443981"
        canvas.drawCentredString(w / 2, 26, footer_text)

        canvas.restoreState()

    doc.build(elements, onFirstPage=draw_poster_frame)
    return response




@require_POST
@transaction.atomic
def save_prize(request, program_id):
    program = get_object_or_404(Program, id=program_id)

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

    # no grade option for general and group programs
    if program.is_general:
        if first_prize_id:
            student = get_object_or_404(Student, id=first_prize_id)
            team = student.team
            general_first_score, _ = GeneralPosition.objects.get_or_create(name='first')
            prize, _ = Prize.objects.update_or_create(
                team=team, program=program,
                defaults={"general_program_position": general_first_score, "remarks": remarks}
            )
            created_prizes.append(prize.id)
        if second_prize_id:
            student = get_object_or_404(Student, id=second_prize_id)
            team = student.team
            general_sec_score = GeneralPosition.objects.get_or_create(name='second')
            prize, _ = Prize.objects.update_or_create(
                team=team, program=program,
                defaults={"general_program_position": general_sec_score, "remarks": remarks}
            )
            created_prizes.append(prize.id)
        if third_prize_id:
            student = get_object_or_404(Student, id=third_prize_id)
            team = student.team
            general_third_score = GeneralPosition.objects.get_or_create(name='third')
            prize, _ = Prize.objects.update_or_create(
                team=team, program=program,
                defaults={"general_program_position": general_third_score, "remarks": remarks}
            )
            created_prizes.append(prize.id)
        return JsonResponse({"message": "success", "created_prizes": created_prizes})

    elif program.is_group:
        if first_prize_id:
            student = get_object_or_404(Student, id=first_prize_id)
            team = student.team
            group_first_score, _ = GroupPosition.objects.get_or_create(name='first')
            prize, _ = Prize.objects.update_or_create(
                team=team, program=program,
                defaults={"group_program_position": group_first_score, "remarks": remarks}
            )
            created_prizes.append(prize.id)
        if second_prize_id:
            student = get_object_or_404(Student, id=first_prize_id)
            team = student.team
            group_second_score, _ = GroupPosition.objects.get_or_create(name='second')
            prize, _ = Prize.objects.update_or_create(
                team=team, program=program,
                defaults={"group_program_position": group_second_score, "remarks": remarks}
            )
            created_prizes.append(prize.id)
        if third_prize_id:
            student = get_object_or_404(Student, id=first_prize_id)
            team = student.team
            group_third_score, _ = GroupPosition.objects.get_or_create(name='third')
            prize, _ = Prize.objects.update_or_create(
                team=team, program=program,
                defaults={"group_program_position": group_third_score, "remarks": remarks}
            )
            created_prizes.append(prize.id)
        return JsonResponse({"message": "success", "created_prizes": created_prizes})

    else:
        # for single programs
        if first_prize_id:
            student = get_object_or_404(Student, id=first_prize_id)
            pos, _ = Position.objects.get_or_create(name="first")
            prize, _ = Prize.objects.update_or_create(
                student=student, program=program,
                defaults={"position": pos, "remarks": remarks}
            )
            student.total_point += pos.mark
            student.save()
            created_prizes.append(prize.id)

        if second_prize_id:
            student = get_object_or_404(Student, id=second_prize_id)
            pos, _ = Position.objects.get_or_create(name="second")
            prize, _ = Prize.objects.update_or_create(
                student=student, program=program,
                defaults={"position": pos, "remarks": remarks}
            )
            student.total_point += pos.mark
            student.save()
            created_prizes.append(prize.id)

        if third_prize_id:
            student = get_object_or_404(Student, id=third_prize_id)
            pos, _ = Position.objects.get_or_create(name="third")
            prize, _ = Prize.objects.update_or_create(
                student=student, program=program,
                defaults={"position": pos, "remarks": remarks}
            )
            student.total_point += pos.mark
            student.save()
            created_prizes.append(prize.id)

            # --- Handle Grades ---
        if gradeA_id:
            student = get_object_or_404(Student, id=gradeA_id)
            grade = get_object_or_404(Grade, name="a_grade")
            prize, _ = Prize.objects.update_or_create(
                student=student, program=program,
                defaults={"grade": grade, "remarks": remarks}
            )
            student.total_point += grade.mark
            student.save()
            created_prizes.append(prize.id)

        if gradeB_id:
            student = get_object_or_404(Student, id=gradeB_id)
            grade = get_object_or_404(Grade, name="b_grade")
            prize, _ = Prize.objects.update_or_create(
                student=student, program=program,
                defaults={"grade": grade, "remarks": remarks}
            )
            student.total_point += grade.mark
            student.save()
            created_prizes.append(prize.id)
        if gradeC_id:
            student = get_object_or_404(Student, id=gradeC_id)
            grade = get_object_or_404(Grade, name="c_grade")
            prize, _ = Prize.objects.update_or_create(
                student=student, program=program,
                defaults={"grade": grade, "remarks": remarks}
            )
            student.total_point += grade.mark
            student.save()
            created_prizes.append(prize.id)

    return JsonResponse({"message": "success", "created_prizes": created_prizes})



def publish_result(request, program_id):
    program = get_object_or_404(Program, id=program_id)
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
        context['total_programs'] = Program.objects.filter(category__in=categories).distinct().count()
        context['meelad_fest_name'] = madrasa.meelad_fest_name
        
        return context

    def post(self, request, *args, **kwargs):
        file = request.FILES.get("file")
        if not file:
            return JsonResponse({"error": "No file uploaded"}, status=400)

        try:
            # Load workbook
            wb = load_workbook(filename=file, data_only=True)
            ws = wb["Sheet1"]  # Sheet with student data
        except Exception as e:
            return JsonResponse({"error": f"Invalid Excel file: {str(e)}"}, status=400)

        created, skipped = 0, 0
        errors = []

        to_create = []
        madrasa = request.user.madrasa

        # Iterate rows (skip header row)
        for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if all(cell is None for cell in row):
                continue

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
    students = Student.objects.filter(team__madrasa=madrasa).select_related('category', 'team')

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

    context = {
        'meelad_fest_name': madrasa.meelad_fest_name if hasattr(madrasa, 'meelad_fest_name') else 'Meelad Fest',
        'categories': categories,
        'teams': teams,
        'students': students,
        'top_students': top_students,
        'statistics_page': True,
        'total_students': students.count(),
        'total_programs': Program.objects.filter(category__in=categories).distinct().count(),
        'total_points': all_points,
        'boys_points': boys_points,
        'girls_points': girls_points,
        'summary_rows': summary_rows,
    }
    return render(request, 'program/statistics.html', context)


@login_required
def statistics_download_report(request):
    report_type = request.GET.get('report', 'students')
    madrasa = request.user.madrasa

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{report_type}_report.csv"'

    writer = csv.writer(response)

    if report_type == 'category-performance':
        writer.writerow(['Team', 'Team ID', 'Category', 'Boys Points', 'Girls Points', 'Total Students', 'Category Total Points'])
        teams = Team.objects.filter(madrasa=madrasa)
        for team in teams:
            for category in Category.objects.filter(madrasa=madrasa):
                boys_points = Student.objects.filter(team=team, category=category, gender='male').aggregate(total=Sum('total_point'))['total'] or 0
                girls_points = Student.objects.filter(team=team, category=category, gender='female').aggregate(total=Sum('total_point'))['total'] or 0
                students_count = Student.objects.filter(team=team, category=category).count()
                cat_total = float(boys_points) + float(girls_points)
                writer.writerow([team.name, team.id, category.name, boys_points, girls_points, students_count, cat_total])

    elif report_type == 'top-ten':
        writer.writerow(['Rank', 'Full Name', 'Code Number', 'Gender', 'Category', 'Team', 'Total Points'])
        students = Student.objects.filter(team__madrasa=madrasa).select_related('category', 'team').order_by('-total_point')[:10]
        for i, student in enumerate(students, start=1):
            writer.writerow([i, student.full_name, student.code_number or '', student.gender or '', student.category.name if student.category else '', student.team.name if student.team else '', student.total_point])

    elif report_type == 'top-category-section':
        writer.writerow(['Category', 'Section', 'Rank', 'Student', 'Code Number', 'Team', 'Total Points'])
        for category in Category.objects.filter(madrasa=madrasa):
            for section in ['male', 'female']:
                section_students = Student.objects.filter(team__madrasa=madrasa, category=category, gender=section).order_by('-total_point')[:10]
                for rank, student in enumerate(section_students, start=1):
                    writer.writerow([category.name, section, rank, student.full_name, student.code_number or '', student.team.name if student.team else '', student.total_point])

    else:
        writer.writerow(['Student Name', 'Code Number', 'Section', 'Category', 'Team', 'Team Madrasa', 'Total Points'])
        students = Student.objects.filter(team__madrasa=madrasa).select_related('category', 'team')
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


def category_program_list(request):
    category_id = request.GET.get('category')
    madrasa = request.user.madrasa
    categories = Category.objects.filter(madrasa=madrasa)

    if category_id:
        selected_category = get_object_or_404(Category, id=category_id)
        programs_for_boys = (
            selected_category.programs.all()
            .annotate(
                published=Case(
                    When(prize__isnull=False, then=Value(True)),
                    default=Value(False),
                    output_field=BooleanField()
                )
            )
            .order_by('-published').distinct()  # Descending: True (has prize) comes first
        )
        programs_for_girls = (selected_category.programs_for_girls.all().annotate(
                published=Case(
                    When(prize__isnull=False, then=Value(True)),
                    default=Value(False),
                    output_field=BooleanField()
                )
            )
            .order_by('-published').distinct()
                              )
    else:
        programs_for_boys = programs_for_girls = Program.objects.filter(Q(category__madrasa=madrasa) | Q(girls_categories__madrasa=madrasa))
        selected_category = None

    try:
        madrasa_id = request.user.madrasa.id
        categories = Category.objects.filter(madrasa_id=madrasa_id)
        total_students = Student.objects.filter(team__madrasa=madrasa_id).count()
        total_programs = Program.objects.filter(category__in=categories).distinct().count()
    except:
        pass

    context = {
        'categories': categories,
        'programs_for_boys': programs_for_boys,
        'programs_for_girls': programs_for_girls,
        'selected_category': selected_category,
        'result_page': True,
        'meelad_fest_name': madrasa.meelad_fest_name,
        'total_students': total_students,
        'total_programs': total_programs,
    }
    return render(request, 'program/result_details.html', context)


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
    participants = program.participants.values("id", "full_name", "code_number")
    students = Student.objects.filter(team__madrasa=request.user.madrasa).values("id", "full_name", "code_number")

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
        config, _ = ProgramRule.objects.get_or_create(madrasa=user.madrasa)
        
        positions = {
            'first': first_prize,
            'second': second_prize,
            'third': third_prize,
        }
        for name, mark in positions.items():
            if mark:
                Position.objects.update_or_create(name=name, defaults={'mark': mark})
        grades = {
            'a_grade': grade_a,
            'b_grade': grade_b,
            'c_grade': grade_c,
        }
        for name, mark in grades.items():
            if mark:
                Grade.objects.update_or_create(name=name, defaults={'mark': mark})

        group_positions = {
            'first': group_first,
            'second': group_second,
            'third': group_third,
        }
        for name, mark in group_positions.items():
            if mark:
                GroupPosition.objects.update_or_create(name=name, defaults={'mark': mark})
        general_prizes = {
            'first': general_first,
            'second': general_second,
            'third': general_third,
        }
        for name, mark in general_prizes.items():
            if mark:
                GeneralPosition.objects.update_or_create(name=name, defaults={'mark': mark})

        config.max_program_per_head = max_programs
        config.fest_type = fest_type
        config.save()
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

   


# for adding program to venue
def add_venue(request):
    if request.method == 'POST':
        data = request.POST()
        name = data.get('name')
        venue, _ = Venue.objects.get_or_create(name=name)
        venue.description = data.get('description')
        venue.save()
        return JsonResponse({'message':'success'})
    return JsonResponse({'message': 'Method Not Allowed'})


# def update_venue_with_program(request, pk):
#     venue = get_object_or_404(Venue, id=pk)
#     if request.method == 'POST':
#         programs = request.POST.get('programs')
#         if programs:
#             venue.program_set.set(programs)
#         return JsonResponse({'message': 'success'})
#     return JsonResponse({'message': 'Method Not Allowed'})

def update_venue_with_program(request, pk):
    venue = get_object_or_404(Venue, id=pk)

    if request.method == "POST":
        body = json.loads(request.body.decode("utf-8"))
        program_ids = body.get("programs", [])

        # Convert to integers
        programs = Program.objects.filter(id__in=program_ids)

        venue.program_set.set(programs)

        return JsonResponse({
            "status": "success",
        })

    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)


@csrf_exempt
def remove_program_from_venue(request, program_id):
    if request.method == "POST":
        program = get_object_or_404(Program, id=program_id)
        program.venue = None
        program.save()
        return JsonResponse({"status": "success"})
    return JsonResponse({"status": "error", "message": "Method Not Allowed"}, status=405)



def venue_list(request):
    venues = Venue.objects.all()
    total_students = 0
    total_programs = 0
    try:
        madrasa_id = request.user.madrasa.id
        categories = Category.objects.filter(madrasa_id=madrasa_id)
        total_students = Student.objects.filter(team__madrasa=madrasa_id).count()
        total_programs = Program.objects.filter(category__in=categories).distinct().count()
    except:
        pass
    return render(request, "program/venue_list.html", {"venues": venues, 
                                                        "total_students": total_students, 
                                                        "total_programs": total_programs, 
                                                        "meelad_fest_name": request.user.madrasa.meelad_fest_name})

def add_venue(request):
    if request.method == "POST":
        Venue.objects.create(
            name=request.POST["name"],
            description=request.POST["description"],
        )
        return redirect("venue_list")

def venue_detail(request, venue_id):
    venue = Venue.objects.get(id=venue_id)
    madrasa = request.user.madrasa
    programs = Program.objects.filter(Q(category__madrasa=madrasa) | Q(girls_categories__madrasa=madrasa))
    venue_programs = Program.objects.filter(venue=venue)
    total_students = Student.objects.filter(team__madrasa=madrasa).count()
    categories = Category.objects.filter(madrasa=madrasa)
    total_programs = Program.objects.filter(category__in=categories).distinct().count()
    return render(request, "program/venue_detail.html", {"venue": venue, 'all_programs': programs,
                                                         'venue_programs': venue_programs,
                                                         'total_students': total_students,
                                                         'total_programs': total_programs,
                                                         'meelad_fest_name': request.user.madrasa.meelad_fest_name})



def download_venue_programs(request, venue_id):
    venue = Venue.objects.get(id=venue_id)
    programs = venue.program_set.all().order_by('scheduled_time').prefetch_related('participants', 'category_set', 'girls_categories')

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
        ["SL No", "Program Title", "Category", "Scheduled Time"]
    ]

    # Initialize stats
    category_counts = {}
    total_participants = 0

    # Table data
    for idx, program in enumerate(programs, start=1):
        # Format time
        if program.scheduled_time:
            scheduled = program.scheduled_time.strftime("%I:%M %p")  # 12-hour format
        else:
            scheduled = "Waiting..."

        cat_name = program.program_category() or "-"
        
        data.append([
            idx,
            program.title,
            cat_name,
            scheduled
        ])

        # Calc Stats
        stats_cat_name = cat_name if cat_name != "-" else "Uncategorized"
        category_counts[stats_cat_name] = category_counts.get(stats_cat_name, 0) + 1
        total_participants += program.participants.count()

    # Create main table
    # Adjusted widths: SL(0.6), Title(3.0), Category(1.5), Time(1.5)
    # Total width of A4 is ~8.27 inch. Margins are likely standard (e.g. 1 inch each side?), 
    # Document was created without margins param? No, in new code doc = SimpleDocTemplate(...).
    # SimpleDocTemplate default margin is 1 inch (72 points). 
    # Available width approx 6 inch?
    # Let's use proportional widths that fit comfortably.
    # Page width = A4[0] = 595.27 points / 72 = 8.27 inches
    # Margins default: 1 inch left, 1 right. Avail: 6.27 inches.
    table = Table(data, colWidths=[0.6*inch, 3.2*inch, 1.8*inch, 1.5*inch])

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
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#DCFCE7')), # Light green
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.black),
        ('ALIGN', (1, -1), (1, -1), 'CENTER'), # Center participant count
        
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
    ]))

    elements.append(summary_table)


    # Build PDF
    doc.build(elements)

    return response
