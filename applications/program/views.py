from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# from xhtml2pdf import pisa

from django.shortcuts import render, get_object_or_404, redirect
from django.views import generic, View
from django.http import HttpResponseRedirect, FileResponse, HttpResponse, JsonResponse
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.template.loader import get_template

from applications.scoreboard.models import Team
from applications.program.models import Category, Program, Student, Prize, Position, Grade
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

            for program in programs:
                program.participants.add(student)

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
        return context


class AddCategoryView(LoginRequiredMixin, View):
    template_name = 'program/category.html'

    def get(self, request):
        form = CategoryForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = CategoryForm(request.POST)
        if form.is_valid():
            category = form.save(commit=False)
            category.madrasa = request.user.madrasa
            category.save()
            form.save_m2m()
            return redirect('categories')  # name of your url for CategoryView
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
        if form.is_valid():
            form.save()
            return redirect("categories")  # adjust to your list view name
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
        except:
            pass

        host_url = f"{self.request.scheme}://{self.request.get_host()}"
        context['category_url'] = f'{host_url}/program/categories?team={team_id}'
        context["boys"] = Student.objects.filter(category=category, gender='male', team_id=team_id)
        context['girls'] = Student.objects.filter(category=category, gender='female', team_id=team_id)

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

        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()  # required for DetailView
        category = self.object

        team_id = request.GET.get("team")

        if "student_form" in request.POST:
            student_form = StudentForm(request.POST)

            if student_form.is_valid():
                student = student_form.save(commit=False)
                student.category = category
                if team_id:
                    student.team = Team.objects.get(id=team_id)
                student.save()
                url = reverse("category_detail", kwargs={"pk": category.pk})
                # Add query param
                if team_id:
                    url = f"{url}?team={team_id}"
                return redirect(url)
            return self.render_to_response(
                self.get_context_data(student_form=student_form)
            )

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
        for program in programs:
            program.participants.add(student)

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
        else:
            context['madrasa_name'] = None

        return context



class ProgramListView(generic.ListView):
    queryset = Program.objects.filter(non_stage=False)
    template_name = 'program/program_list.html'
    context_object_name = 'stage_programs'

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        context['non_stage_programs'] = Program.objects.filter(non_stage=True)
        context['categories'] = Category.objects.all()

        request = self.request
        madrasa_id = request.user.madrasa.id
        host_url = f"{request.scheme}://{request.get_host()}"
        context["form_url"] = f'{host_url}/program/student-registration/?madrasa_id={madrasa_id}'
        return context


def program_participants_json(request, pk):
    program = get_object_or_404(Program, pk=pk)
    participants = program.participants.select_related("team").all()

    data = {
        "program": program.title,
        "participants": [
            {
                "full_name": p.full_name,
                "code_number": p.code_number,
                "chest_number": "",   # if you have it
                "mark1": "",
                "mark2": "",
                "remarks": "",
            }
            for p in participants
        ]
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




def program_judge_slip_pdf(request, pk):
    program = get_object_or_404(Program, pk=pk)
    participants = program.participants.all()

    response = HttpResponse(content_type="application/pdf")
    response['Content-Disposition'] = f'attachment; filename="{program.slug}_participants.pdf"'

    doc = SimpleDocTemplate(response, pagesize=landscape(A4),
                            leftMargin=20, rightMargin=20, topMargin=20, bottomMargin=20)
    elements = []
    styles = getSampleStyleSheet()

    # -----------------------------
    # First Table: Judge Slip with Code Number
    # -----------------------------
    heading1 = Paragraph(f"Judge Slip: {program.title} with Category", styles['Heading3'])
    data1 = [["Sl. No", "Code Number", "Chest Number", "Mark1", "Mark2", "Remarks"]]
    for i, p in enumerate(participants, start=1):
        data1.append([i, p.code_number or "", "", "", "", ""])

    table1 = Table(data1, colWidths=[30, 60, 60, 50, 50, 130])
    table1.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.5, colors.black),
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
    ]))

    # -----------------------------
    # Second Table: without Code Number (also include header)
    # -----------------------------
    heading2 = Paragraph(f"{program.title} with Category", styles['Heading3'])
    data2 = [["Sl. No", "Code Number", "Chest Number", "Mark1", "Mark2", "Remarks"]]
    for i, p in enumerate(participants, start=1):
        data2.append([i, "", "", "", "", ""])

    table2 = Table(data2, colWidths=[30, 60, 60, 50, 50, 130])
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