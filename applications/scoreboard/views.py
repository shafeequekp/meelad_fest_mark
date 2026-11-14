from django.shortcuts import render, get_object_or_404, redirect
from django.views import generic, View
from django.http import HttpResponseRedirect, FileResponse, HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.contrib import messages
from django.db.models import Q

from applications.scoreboard.models import Team, ScreeningLink
from .forms import TeamForm
from applications.accounts.models import Madrasa, User
from applications.program.models import Category, Prize, Position, Grade, ProgramRule, GroupPosition, GeneralPosition, Judge
from applications.subscription.models import Subscription, Transaction


def _hex_to_rgb(value):
    """Parse '#rrggbb' / '#rgb' → (r, g, b) tuple, or None if invalid."""
    h = (value or '').lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _nearest_colour_key(hex_val):
    """Return the named palette key closest to an arbitrary hex colour."""
    rgb = _hex_to_rgb(hex_val)
    if rgb is None:
        return None
    return min(
        Team.COLOR_HEX.items(),
        key=lambda kv: sum((a - b) ** 2 for a, b in zip(rgb, _hex_to_rgb(kv[1]))),
    )[0]


def _colour_key(post):
    """The teams UI picks colours with a named-palette select; but older
    submissions (and any legacy flow) sent a hex from a <input type='color'>
    picker while Team.colour stores named keys (blue/green/indigo/...). Map a
    hex back to the closest named key so form validation succeeds — a colour
    choice never silently disappears."""
    data = post.copy()
    hex_val = (post.get('colour') or '').strip()
    key = None
    if hex_val.lower().startswith('#') or _hex_to_rgb(hex_val) is not None:
        key = _nearest_colour_key(hex_val)
    if not key:
        key = hex_val.lower() if hex_val.lower() in Team.COLOR_HEX else None
    if key:
        data['colour'] = key
    else:
        data['colour'] = ''
    return data


def add_team_and_marks(request):
    if request.method == 'POST':
        post_data = _colour_key(request.POST)
        team_form = TeamForm(post_data)
        # marks_form = MarksForm(post_data)

        if team_form.is_valid():
            team = team_form.save(commit=False)
            team.madrasa = request.user.madrasa
            # On a boys-only fest the girls-leader fields are not part of the
            # flow — never store them, even from a forged POST.



            if team.madrasa and team.madrasa.is_boys_only:
                team.girls_leader = None
                team.girls_leader_assistant = None
            team.save()

            messages.success(request, f"Team '{team.name}' added successfully.")
            return redirect('teams')  # redirect to team list page after save

        messages.error(request, 'Could not add team. Please check the form fields.')
        return redirect('teams')

    # Adding happens inside the team-list modal — there is no standalone
    # page, so a bare GET just shows the team list again.

    return redirect('teams')


def edit_team(request, team_id):
    team = get_object_or_404(Team, id=team_id)

    if request.method == 'POST':
        team_form = TeamForm(_colour_key(request.POST), instance=team, user=request.user)
        if team_form.is_valid():
            updated_team = team_form.save(commit=False)
            updated_team.madrasa = request.user.madrasa
            # On a boys-only fest the girls-leader fields are not part of the
            # flow — never store them, even from a forged POST.
            if updated_team.madrasa and updated_team.madrasa.is_boys_only:
                updated_team.girls_leader = None
                updated_team.girls_leader_assistant = None
            updated_team.save()
            messages.success(request, f"Team '{updated_team.name}' updated successfully.")
        else:
            messages.error(request, 'Could not update team. Please check the form fields.')
        return redirect('teams')

    return redirect('teams')


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

def _build_screening_context(madrasa):
    """Shared context used by the login home view and the public screening view."""
    from applications.program.models import Category, ProgramRule, Student, Program
    context = {}
    context['meelad_fest_name'] = madrasa.meelad_fest_name
    context['madrasa'] = madrasa
    context['fest_type'] = madrasa.fest_type
    context['is_boys_only'] = madrasa.is_boys_only
    context['is_girls_only'] = madrasa.is_girls_only
    context['is_both_sections'] = madrasa.is_both_sections
    categories = Category.objects.filter(madrasa=madrasa)
    context['categories'] = categories
    context['teams'] = Team.objects.filter(madrasa=madrasa)
    context['teams_with_grand_totals'] = Prize.get_team_grand_totals(madrasa, madrasa.fest_type)
    context['total_students'] = Student.objects.filter(team__madrasa=madrasa).count()
    context['total_programs'] = Program.objects.filter(Q(category__in=categories) | Q(madrasa=madrasa)).distinct().count()
    context['rule'] = ProgramRule.objects.filter(madrasa=madrasa).last()
    return context


@login_required
def generate_screening_link(request):
    """Creates (or reuses) a public screening link for the current madrasa."""
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    madrasa = getattr(request.user, "madrasa", None)
    if not madrasa:
        return JsonResponse({"error": "No madrasa associated with account"}, status=400)

    link = ScreeningLink.objects.filter(madrasa=madrasa, active=True).first()
    if not link:
        link = ScreeningLink.objects.create(madrasa=madrasa)

    full_url = request.build_absolute_uri(reverse("screening", kwargs={"token": link.token}))
    return JsonResponse({"link": full_url, "token": link.token})


def screening_view(request, token):
    """Public, login-free full-screen view of a madrasa's screening slides.

    No header, no menu — just the full screening slides for a projector/display.
    """
    link = get_object_or_404(ScreeningLink, token=token, active=True)
    madrasa = link.madrasa
    context = _build_screening_context(madrasa)
    context['is_screening_public'] = True
    return render(request, "screening.html", context)


def _home_madrasa(user):
    """Homepage madrasa resolution, checked through the Judge instance first.

    A linked judge's login account has madrasa=None (they are not a madrasa
    row of their own) — their homepage must be the madrasa of the Judge
    instance they belong to (Judge.madrasa). Madrasa users keep the classic
    per-user madrasa resolution.
    """
    if not getattr(user, "is_authenticated", False):
        return None
    if getattr(user, "pk", None) is not None:
        judge = Judge.objects.filter(user=user, is_active=True).select_related("madrasa").first()
        if judge and judge.madrasa:
            return judge.madrasa
    return user.madrasa


class MarkView(generic.ListView):
    template_name = 'index.html'
    context_object_name = 'teams'

    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return Team.objects.none()
        madrasa = _home_madrasa(self.request.user)
        if madrasa:
            return Team.objects.filter(madrasa=madrasa)
        return Team.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        madrasa = _home_madrasa(user)
        teams_with_totals = Prize.get_team_grand_totals(madrasa, madrasa.fest_type) if madrasa else []
        context['meelad_fest_name'] = madrasa.meelad_fest_name if madrasa else None
        # Fest section structure flags for the home/screening UI.
        context['fest_type'] = madrasa.fest_type
        context['is_boys_only'] = madrasa.is_boys_only
        context['is_girls_only'] = madrasa.is_girls_only
        context['is_both_sections'] = madrasa.is_both_sections
        categories = Category.objects.filter(madrasa=madrasa)
        context['categories'] = categories
        context['teams_with_grand_totals'] = teams_with_totals
        from applications.program.models import Student, Program
        context["total_students"] = Student.objects.filter(team__madrasa=madrasa).count()
        context["total_programs"] = Program.objects.filter(Q(category__in=categories) | Q(madrasa=madrasa)).distinct().count()
        # Fest status flags for the home hero badge. Registration is considered
        # open until the coordinator confirms the schedule; results are considered
        # published once at least one program's result is live.
        context["registration_open"] = not bool(getattr(madrasa, "schedule_consent_confirmed", False))
        context["has_published_results"] = (
            Program.objects.filter(madrasa=madrasa, is_result_published=True).exists()
            if madrasa else False
        )
        context['home_page'] = True

        # ---- Fest Command Center stats ----
        # All metrics are scoped to this madrasa and to the fest section the
        # same way the programs/results pages scope theirs, so these tiles
        # always agree with the numbers shown on those pages.
        from applications.program.views import _fest_section
        from applications.program.models import program_section_q, Venue
        from applications.schedule.models import FestDay

        section_q = program_section_q(madrasa, _fest_section(madrasa))
        programs_qs = Program.objects.filter(section_q).distinct()
        context['cc_total_programs'] = programs_qs.count()
        context['cc_published'] = programs_qs.filter(is_result_published=True).count()
        context['cc_awaiting'] = (
            programs_qs.filter(is_result_published=False, prize__isnull=False).count()
        )
        context['cc_not_entered'] = (
            programs_qs.filter(is_result_published=False, prize__isnull=True).count()
        )
        context['cc_unscheduled'] = programs_qs.filter(schedule_entry__isnull=True).count()
        context['cc_venues'] = Venue.objects.filter(madrasa=madrasa).count()
        context['cc_judges'] = Judge.objects.filter(madrasa=madrasa, is_active=True).count()
        context['cc_days'] = FestDay.objects.filter(madrasa=madrasa).count()
        # Initial mark-configuration is a ONE-TIME, madrasa-owner step
        # (Position/Grade/GroupPosition/... rows + User.config_done). Linked
        # judge logins have their own user row (madrasa=None, config_done
        # unset) and must never see that modal — it is the owner's setup
        # step, and submitting it as a judge would even target madrasa=None.
        # Only surface the modal to users who own a madrasa row directly.
        context['config_done'] = (
            user.config_done if getattr(user, "madrasa", None) is not None else True
        )
        context['subscribed'] = True
        subscription = Subscription.objects.filter(institution=madrasa).last()
        if not subscription or not subscription.is_active:
            context['subscribed'] = False

        # Position/Grade/GroupPosition/GeneralPosition marks are scoped per
        # madrasa (each madrasa can configure its own marks). Always filter by
        # the current madrasa so one madrasa's config never leaks into another.
        first_obj = Position.objects.filter(name='first', madrasa=madrasa).first()
        second_obj = Position.objects.filter(name='second', madrasa=madrasa).first()
        third_obj = Position.objects.filter(name='third', madrasa=madrasa).first()
        a_grade = Grade.objects.filter(name='a_grade', madrasa=madrasa).first()
        b_grade = Grade.objects.filter(name='b_grade', madrasa=madrasa).first()
        c_grade = Grade.objects.filter(name='c_grade', madrasa=madrasa).first()
        group_first = GroupPosition.objects.filter(name='first', madrasa=madrasa).first()
        group_second = GroupPosition.objects.filter(name='second', madrasa=madrasa).first()
        group_third = GroupPosition.objects.filter(name='third', madrasa=madrasa).first()
        general_first = GeneralPosition.objects.filter(name='first', madrasa=madrasa).first()
        general_second = GeneralPosition.objects.filter(name='second', madrasa=madrasa).first()
        general_third = GeneralPosition.objects.filter(name='third', madrasa=madrasa).first()
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

        # Compact display rows for the profile modal's read-only Mark
        # Configuration card: (label, 1st, 2nd, 3rd).
        context['mark_rows'] = [
            ('Individual',
             context.get('first'), context.get('second'), context.get('third')),
            ('Group',
             context.get('group_first'), context.get('group_second'), context.get('group_third')),
            ('General',
             context.get('gen_first'), context.get('gen_second'), context.get('gen_third')),
        ]

        context['rule'] = ProgramRule.objects.filter(madrasa=madrasa).last()
        return context
    
    # need to add redirect url if subscribed is False

    
    def get(self, request, *args, **kwargs):
        # Homepage subscription gate — controlled by the global SubscriptionSettings flag.
        # If the admin has disabled the subscription section, redirect to home.
        # Otherwise, allow the user to see the home page (the subscription paywall
        # is handled by the login view and subscribe view).
        madrasa = _home_madrasa(request.user)
        from applications.subscription.models import SubscriptionSettings
        if not SubscriptionSettings.is_enabled():
            # Subscription section disabled: allow user to see home page normally.
            # (No subscription-required content on this page.)
            pass
        else:
            # Subscription section enabled: check if user needs to subscribe.
            from applications.program.models import Judge
            if not request.user.is_staff and not request.user.is_superuser:
                if not Judge.objects.filter(user=request.user, is_active=True).exists():
                    if not request.user.subscribed:
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

        try:
            madrasa = request.user.madrasa
            categories = Category.objects.filter(madrasa=madrasa)
            context['categories'] = categories
            from applications.program.models import Student, Program
            context["total_students"] = Student.objects.filter(team__madrasa=madrasa).count()
            context["total_programs"] = Program.objects.filter(Q(category__in=categories) | Q(madrasa=madrasa)).distinct().count()
            context['meelad_fest_name'] = madrasa.meelad_fest_name
        except Exception:
            pass

        return context




