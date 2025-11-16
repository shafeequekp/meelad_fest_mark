from django.shortcuts import render, get_object_or_404, redirect
from django.views import generic, View
from django.http import HttpResponseRedirect, FileResponse, HttpResponse

from applications.scoreboard.models import Team
from .forms import TeamForm
from applications.accounts.models import Madrasa, User
from applications.program.models import Category, Prize, Position, Grade, ProgramRule, GroupPosition, GeneralPosition
from applications.subscription.models import Subscription, Transaction


def add_team_and_marks(request):
    if request.method == 'POST':
        team_form = TeamForm(request.POST)
        # marks_form = MarksForm(request.POST)

        if team_form.is_valid():
            team = team_form.save(commit=False)
            team.madrasa = request.user.madrasa
            team.save()

            # # Boys Section
            # Mark.objects.create(
            #     team=team,
            #     section='boys',
            #     super_senior=marks_form.cleaned_data['super_senior_boys'],
            #     senior=marks_form.cleaned_data['senior_boys'],
            #     junior=marks_form.cleaned_data['junior_boys'],
            #     subjunior=marks_form.cleaned_data['subjunior_boys'],
            #     kiddies=marks_form.cleaned_data['kiddies_boys'],
            #     general=marks_form.cleaned_data['general_boys'],
            # )
            #
            # # Girls Section
            # Mark.objects.create(
            #     team=team,
            #     section='girls',
            #     super_senior=marks_form.cleaned_data['super_senior_girls'],
            #     senior=marks_form.cleaned_data['senior_girls'],
            #     junior=marks_form.cleaned_data['junior_girls'],
            #     subjunior=marks_form.cleaned_data['subjunior_girls'],
            #     kiddies=marks_form.cleaned_data['kiddies_girls'],
            #     general=marks_form.cleaned_data['general_girls'],
            # )

            return redirect('teams')  # redirect to team list page after save
    else:
        team_form = TeamForm()
        # marks_form = MarksForm()

    return render(request, 'teams/add_team.html', {
        'team_form': team_form,
        # 'marks_form': marks_form,
    })


# def edit_marks_view(request, team_id):
#     team = get_object_or_404(Team, id=team_id)
#
#     boys_mark, _ = Mark.objects.get_or_create(team=team, section="boys")
#     girls_mark, _ = Mark.objects.get_or_create(team=team, section="girls")
#
#     if request.method == "POST":
#         boys_form = MarkEditForm(request.POST, prefix="boys", instance=boys_mark)
#         girls_form = MarkEditForm(request.POST, prefix="girls", instance=girls_mark)
#
#         if boys_form.is_valid() and girls_form.is_valid():
#             boys_form.save()
#             girls_form.save()
#             return redirect("teams")  # or wherever you want
#     else:
#         boys_form = MarkEditForm(prefix="boys", instance=boys_mark)
#         girls_form = MarkEditForm(prefix="girls", instance=girls_mark)
#
#     return render(request, "teams/edit_team_marks.html", {
#         "team": team,
#         "boys_form": boys_form,
#         "girls_form": girls_form,
#     })

class MarkView(generic.ListView):
    template_name = 'index.html'
    context_object_name = 'teams'

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Team.objects.none()
        if hasattr(self.request.user, "madrasa") and self.request.user.madrasa:
            madrasa = self.request.user.madrasa
            teams = Team.objects.filter(madrasa=madrasa)
            return teams
        return Team.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        madrasa = user.madrasa
        teams_with_totals = Prize.get_team_grand_totals(madrasa)
        context['meelad_fest_name'] = madrasa.meelad_fest_name if user.madrasa else None
        categories = Category.objects.filter(madrasa=madrasa)
        context['categories'] = categories
        context['teams_with_grand_totals'] = teams_with_totals
        from applications.program.models import Student, Program
        context["total_students"] = Student.objects.filter(team__madrasa=madrasa).count()
        context["total_programs"] = Program.objects.filter(category__in=categories).distinct().count()
        context['home_page'] = True
        context['config_done'] = user.config_done
        context['subscribed'] = True
        subscription = Subscription.objects.filter(institution=madrasa).last()
        if not subscription or not subscription.is_active:
            context['subscribed'] = False

        first_obj = Position.objects.filter(name='first').last()
        second_obj = Position.objects.filter(name='second').last()
        third_obj = Position.objects.filter(name='third').last()
        a_grade = Grade.objects.filter(name='a_grade').last()
        b_grade = Grade.objects.filter(name='b_grade').last()
        c_grade = Grade.objects.filter(name='c_grade').last()
        group_first = GroupPosition.objects.filter(name='first').last()
        group_second = GroupPosition.objects.filter(name='second').last()
        group_third = GroupPosition.objects.filter(name='third').last()
        general_first = GeneralPosition.objects.filter(name='first').last()
        general_second = GeneralPosition.objects.filter(name='second').last()
        general_third = GeneralPosition.objects.filter(name='third').last()
        if first_obj:
            context['first'] = first_obj.mark
        if second_obj:
            context['second'] = second_obj.mark
        if third_obj:
            context['third'] = third_obj.mark
        if a_grade:
            context['a_grade'] = a_grade.mark
        if b_grade:
            context['b_grade'] = b_grade.mark
        if c_grade:
            context['c_grade'] = c_grade.mark
        if group_first:
            context['group_first'] = group_first.mark
        if group_second:
            context['group_second'] = group_second.mark
        if group_third:
            context['group_third'] = group_third.mark
        if general_first:
            context['gen_first'] = general_first.mark
        if general_second:
            context['gen_second'] = general_second.mark
        if general_third:
            context['gen_third'] = general_third.mark
        
        context['rule'] = ProgramRule.objects.filter(madrasa=madrasa).last()
        return context
    
    # need to add redirect url if subscribed is False

    
    def get(self, request, *args, **kwargs):
        madrasa_id = request.user.madrasa.id
        subscription = Subscription.objects.filter(institution_id=madrasa_id).last()

        # subscription.is_active → not subscription.is_active  (NO parentheses!)
        if not subscription or not subscription.is_active:
            return redirect("subscription:subscribe")

        return super().get(request, *args, **kwargs)



class TeamsView(generic.ListView):
    template_name = 'teams/teams.html'
    context_object_name = 'teams'

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Team.objects.none()
        if hasattr(self.request.user, "madrasa") and self.request.user.madrasa:
            madrasa = self.request.user.madrasa
            return madrasa.team_set.all()
        return Team.objects.none()

    def get_context_data(self, *args, **kwargs):
        context = super().get_context_data(*args, **kwargs)
        request = self.request
        madrasa_id = request.user.madrasa.id
        host_url = f"{request.scheme}://{request.get_host()}"
        context["form_url"] = f'{host_url}/program/student-registration/?institution_id={madrasa_id}'
        return context




