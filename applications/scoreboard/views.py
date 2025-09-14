from django.shortcuts import render, get_object_or_404, redirect
from django.views import generic, View
from django.http import HttpResponseRedirect, FileResponse, HttpResponse

from applications.scoreboard.models import Mark, Team
from .forms import TeamForm, MarksForm, MarkEditForm
from applications.accounts.models import Madrasa, User


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
        marks_form = MarksForm()

    return render(request, 'teams/add_team.html', {
        'team_form': team_form,
        'marks_form': marks_form,
    })


def edit_marks_view(request, team_id):
    team = get_object_or_404(Team, id=team_id)

    boys_mark, _ = Mark.objects.get_or_create(team=team, section="boys")
    girls_mark, _ = Mark.objects.get_or_create(team=team, section="girls")

    if request.method == "POST":
        boys_form = MarkEditForm(request.POST, prefix="boys", instance=boys_mark)
        girls_form = MarkEditForm(request.POST, prefix="girls", instance=girls_mark)

        if boys_form.is_valid() and girls_form.is_valid():
            boys_form.save()
            girls_form.save()
            return redirect("teams")  # or wherever you want
    else:
        boys_form = MarkEditForm(prefix="boys", instance=boys_mark)
        girls_form = MarkEditForm(prefix="girls", instance=girls_mark)

    return render(request, "teams/edit_team_marks.html", {
        "team": team,
        "boys_form": boys_form,
        "girls_form": girls_form,
    })

class MarkView(generic.ListView):
    template_name = 'index.html'
    context_object_name = 'marks'

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Mark.objects.none()
        if hasattr(self.request.user, "madrasa") and self.request.user.madrasa:
            madrasa = self.request.user.madrasa
            teams = Team.objects.filter(madrasa=madrasa)  # ✅ correct filter
            return Mark.objects.filter(team__in=teams)
        return Mark.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # collect unique teams and compute their grand total
        teams = {}
        for mark in context['marks']:
            if mark.team.id not in teams:
                teams[mark.team.id] = {
                    "team": mark.team,
                    "grand_total": Mark.get_team_grand_total(mark.team)
                }

        context['teams_with_grand_totals'] = teams.values()
        user = self.request.user
        madrasa = user.madrasa
        context['meelad_fest_name'] = madrasa.meelad_fest_name if user.madrasa else None
        # context['madrasa_id'] = madrasa.id
        return context


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
        context["form_url"] = f'{host_url}/program/student-registration/?madrasa_id={madrasa_id}'
        return context




