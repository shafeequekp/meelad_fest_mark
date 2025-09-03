from django.shortcuts import render, get_object_or_404
from django.views import generic, View
from django.http import HttpResponseRedirect, FileResponse, HttpResponse

from .models import Mark, Team
from accounts.models import Madrasa, User


class MarkView(generic.ListView):
    template_name = 'index.html'
    queryset = Mark.objects.all()
    context_object_name = 'marks'

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
        context['meelad_fest_name'] = user.madrasa.meelad_fest_name if user.madrasa else None
        return context



from django.shortcuts import render, redirect
from .forms import TeamForm, MarksForm
from .models import Team, Mark


def add_team_and_marks(request):
    if request.method == 'POST':
        team_form = TeamForm(request.POST)
        marks_form = MarksForm(request.POST)

        if team_form.is_valid() and marks_form.is_valid():
            team = team_form.save()

            # Boys Section
            Mark.objects.create(
                team=team,
                section='boys',
                super_senior=marks_form.cleaned_data['super_senior_boys'],
                senior=marks_form.cleaned_data['senior_boys'],
                junior=marks_form.cleaned_data['junior_boys'],
                subjunior=marks_form.cleaned_data['subjunior_boys'],
                kiddies=marks_form.cleaned_data['kiddies_boys'],
                general=marks_form.cleaned_data['general_boys'],
            )

            # Girls Section
            Mark.objects.create(
                team=team,
                section='girls',
                super_senior=marks_form.cleaned_data['super_senior_girls'],
                senior=marks_form.cleaned_data['senior_girls'],
                junior=marks_form.cleaned_data['junior_girls'],
                subjunior=marks_form.cleaned_data['subjunior_girls'],
                kiddies=marks_form.cleaned_data['kiddies_girls'],
                general=marks_form.cleaned_data['general_girls'],
            )

            return redirect('team_list')  # redirect to some list page after save
    else:
        team_form = TeamForm()
        marks_form = MarksForm()

    return render(request, 'teams/add_team.html', {
        'team_form': team_form,
        'marks_form': marks_form,
    })


class TeamsView(generic.ListView):
    template_name = 'teams/teams.html'
    queryset = Team.objects.all()
    context_object_name = 'teams'








# # views.py
# from django.shortcuts import render, redirect, get_object_or_404
# from django.forms import modelformset_factory
# from .models import Team
# from .forms import TeamForm, MarkFormSet
#
# def team_list(request):
#     teams = Team.objects.all()
#     return render(request, "teams/team_list.html", {"teams": teams})
#
# def add_team_with_marks(request):
#     if request.method == "POST":
#         team_form = TeamForm(request.POST)
#         if team_form.is_valid():
#             team = team_form.save()
#             marks_formset = MarkFormSet(request.POST, instance=team)
#             if marks_formset.is_valid():
#                 marks_formset.save()
#                 return redirect("team_list")
#     else:
#         team_form = TeamForm()
#         marks_formset = MarkFormSet()
#
#     return render(request, "teams/add_team_marks.html", {
#         "team_form": team_form,
#         "marks_formset": marks_formset
#     })
#
# def edit_team_with_marks(request, pk):
#     team = get_object_or_404(Team, pk=pk)
#     if request.method == "POST":
#         team_form = TeamForm(request.POST, instance=team)
#         marks_formset = MarkFormSet(request.POST, instance=team)
#         if team_form.is_valid() and marks_formset.is_valid():
#             team_form.save()
#             marks_formset.save()
#             return redirect("team_list")
#     else:
#         team_form = TeamForm(instance=team)
#         marks_formset = MarkFormSet(instance=team)
#
#     return render(request, "teams/edit_team_marks.html", {
#         "team_form": team_form,
#         "marks_formset": marks_formset,
#         "team": team,
#     })
