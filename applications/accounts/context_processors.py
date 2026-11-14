"""Context processors that give the shared header / profile modal consistent data."""


def profile_context(request):
    """Inject madrasa info + dashboard summary used by the header profile popup.

    Previously each view had to re-compute ``total_students`` / ``total_programs``
    / ``meelad_fest_name`` on its own; this processor makes those values (plus the
    current user's madrasa) available on *every* page so the profile modal always
    renders with a standard, complete layout.
    """
    context = {}
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return context

    from applications.program.models import Category, Program, Student, Judge

    # A linked judge account is fest staff, not a madrasa row of its own
    # (user.madrasa is None), so its homepage/profile madrasa must be read
    # through the Judge instance — the same rule the scoreboard home uses.
    madrasa = getattr(user, "madrasa", None)
    if (getattr(user, "pk", None) is not None
            and not getattr(user, "is_staff", False)
            and not getattr(user, "is_superuser", False)):
        judge = Judge.objects.filter(user=user, is_active=True).select_related("madrasa").first()
        if judge and judge.madrasa:
            madrasa = judge.madrasa
    context["profile_madrasa"] = madrasa
    context["meelad_fest_name"] = getattr(madrasa, "meelad_fest_name", None)

    if madrasa:
        # Fest section structure (both / boys only / girls only) plus a couple of
        # convenient booleans so templates can collapse the Boys/Girls UI.
        context["fest_type"] = madrasa.fest_type
        context["is_boys_only"] = madrasa.is_boys_only
        context["is_girls_only"] = madrasa.is_girls_only
        context["is_both_sections"] = madrasa.is_both_sections

        categories = Category.objects.filter(madrasa=madrasa)
        context["total_students"] = Student.objects.filter(team__madrasa=madrasa).count()
        context["total_programs"] = (
            Program.objects.filter(category__in=categories).distinct().count()
        )
        context["total_teams"] = madrasa.team_set.count()
    else:
        context["fest_type"] = "both"
        context["is_boys_only"] = False
        context["is_girls_only"] = False
        context["is_both_sections"] = True
        context["total_students"] = 0
        context["total_programs"] = 0
        context["total_teams"] = 0

    # Global subscription gate: controls whether the subscription section
    # is available on login for the entire web app.
    from applications.subscription.models import SubscriptionSettings
    context['SUBSCRIPTION_ENABLED'] = SubscriptionSettings.is_enabled()

    return context


def team_theme_context(request):
    """When ?team= is present, wash inner pages in that team's colour."""
    raw = request.GET.get("team")
    if not raw:
        return {"has_team_theme": False}
    try:
        team_id = int(raw)
    except (TypeError, ValueError):
        return {"has_team_theme": False}

    from applications.scoreboard.models import Team

    team = Team.objects.filter(pk=team_id).first()
    if not team:
        return {"has_team_theme": False}
    return team.theme_context()
