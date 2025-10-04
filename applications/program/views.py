import json

from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl import load_workbook

# from xhtml2pdf import pisa

from django.shortcuts import render, get_object_or_404, redirect
from django.views import generic, View
from django.http import HttpResponseRedirect, FileResponse, HttpResponse, JsonResponse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.template.loader import get_template
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Case, When, Value, BooleanField, Q

from applications.scoreboard.models import Team
from applications.program.models import Category, Program, Student, Prize, Position, Grade, GroupPosition, GeneralPosition, ProgramRule
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

            return JsonResponse({"message": "success"})
        except Student.DoesNotExist:
            return JsonResponse({"message": "error", "details": "Invalid student"})
    return JsonResponse({"message": "error", "details": "Invalid request"})


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
            context['team_name'] = Team.objects.get(id=team_id).name
            context['team_id'] = team_id
        except:
            pass

        host_url = f"{self.request.scheme}://{self.request.get_host()}"
        context['category_url'] = f'{host_url}/program/categories?team={team_id}'
        context["boys"] = Student.objects.filter(category=category, gender='male', team_id=team_id).order_by('-total_point')
        context['girls'] = Student.objects.filter(category=category, gender='female', team_id=team_id).order_by('-total_point')

        boys_programs = category.programs.all()
        girls_programs = category.programs_for_girls.all()
        context["boys_stage_programs"] = boys_programs.filter(non_stage=False)
        context["boys_non_stage_programs"] = boys_programs.filter(non_stage=True)
        context['boys_programs'] = boys_programs
        context['girls_programs'] = girls_programs

        context["girls_stage_programs"] = girls_programs.filter(non_stage=False)
        context["girls_non_stage_programs"] = girls_programs.filter(non_stage=True)

        # forms (empty forms for GET)
        context["student_form"] = kwargs.get("student_form") or StudentForm()
        context["program_form"] = kwargs.get("program_form") or ProgramForm()

        context["form_url"] = f'{host_url}/program/student-registration/?madrasa_id={self.request.user.madrasa.id}'

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

        madrasa_id = self.request.GET.get('madrasa_id')
        if madrasa_id:
            madrasa = Madrasa.objects.get(id=madrasa_id)
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

        host_url = f"{request.scheme}://{request.get_host()}"
        context["form_url"] = f'{host_url}/program/student-registration/?madrasa_id={madrasa_id}'
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

    # Save prizes
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
    print(created_prizes, 'aaaaaaaaa')

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
        programs_for_boys = programs_for_girls = Program.objects.all()
        selected_category = None

    context = {
        'categories': categories,
        'programs_for_boys': programs_for_boys,
        'programs_for_girls': programs_for_girls,
        'selected_category': selected_category,
        'result_page': True,
        'meelad_fest_name': madrasa.meelad_fest_name,
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




from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from .models import Program, Student

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

