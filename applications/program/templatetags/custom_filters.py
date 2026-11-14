from django import template
from django.db.models import Sum, Q

from applications.program.models import Student, Prize

register = template.Library()


@register.filter
def non_stage(programs):
    # Group programs are managed on their own page (group_programs), so keep
    # them out of the regular programs list.
    return programs.filter(non_stage=True).exclude(is_group=True)


@register.filter
def stage(programs):
    # Group programs are managed on their own page (group_programs), so keep
    # them out of the regular programs list.
    return programs.filter(non_stage=False).exclude(is_group=True)


@register.simple_tag
def get_participants_count(program):
    return program.participants.all().count()


@register.filter
def is_result_added(program):
    return program.prize_set.exists()

@register.simple_tag
def get_results(program, prize='First'):
    if prize == 'First':
        first_result = program.prize_set.filter(position__name='first').first()
        if first_result:
            return first_result.student.full_name
    elif prize == 'Second':
        second_result = program.prize_set.filter(position__name='second').first()
        if second_result:
            return second_result.student.full_name
    elif prize == 'Third':
        third_result = program.prize_set.filter(position__name='third').first()
        if third_result:
            return third_result.student.full_name
    return 'Not Published'


@register.simple_tag
def get_category_total(category, gender=None, team=None):
    students = Student.objects.filter(category=category)

    if gender:
        students = students.filter(gender=gender)
    if team:
        students = students.filter(team=team)

    student_ids = students.values_list("id", flat=True)

    # Sum position marks
    pos_marks = Prize.objects.filter(
        student_id__in=student_ids, position__isnull=False, program__is_result_published=True
    ).aggregate(
        total=Sum("position__mark")
    )["total"] or 0

    # Sum grade marks
    grade_marks = Prize.objects.filter(
        student_id__in=student_ids, grade__isnull=False, program__is_result_published=True
    ).aggregate(
        total=Sum("grade__mark")
    )["total"] or 0

    return pos_marks + grade_marks


@register.simple_tag
def get_section_total(gender, team):
    students = Student.objects.filter(gender=gender, team=team)

    student_ids = students.values_list("id", flat=True)

    # Sum position marks
    pos_marks = Prize.objects.filter(
        student_id__in=student_ids, position__isnull=False, program__is_result_published=True
    ).aggregate(
        total=Sum("position__mark")
    )["total"] or 0

    # Sum grade marks
    grade_marks = Prize.objects.filter(
        student_id__in=student_ids, grade__isnull=False, program__is_result_published=True
    ).aggregate(
        total=Sum("grade__mark")
    )["total"] or 0

    return int(pos_marks + grade_marks)


@register.filter
def is_equal_to(value, arg):
    """
    Returns True if value equals arg (or their IDs if Django model instances).
    """
    if value is None or arg is None:
        return False
    if hasattr(value, 'id') and hasattr(arg, 'id'):
        return value.id == arg.id
    return value == arg


@register.filter
def get_item(mapping, key):
    """Return ``mapping[key]`` (dict) or None — used for per-criterion scores."""
    if not mapping:
        return None
    try:
        return mapping.get(key)
    except (TypeError, AttributeError):
        return None
@register.simple_tag
def get_team_participants(program, team):
    """
    Returns participants of a program that belong to a specific team.
    """
    return program.participants.filter(team=team)


@register.simple_tag
def get_team_section_students(team, section):
    """Students of a team eligible for a general program's section.

    Boys section → male students, Girls section → female students, matching
    the gender filter used by the ``load_team_students`` AJAX endpoint.

    Fallback: if the section filter would exclude every student of the team
    (e.g. the team only has students whose gender was left blank on upload),
    return the full team roster instead of an empty list so the participant
    picker is never silently empty.
    """
    students = team.student_set.all()
    if section not in ('boys', 'girls'):
        return students
    gender = 'male' if section == 'boys' else 'female'
    filtered = students.filter(gender=gender)
    if filtered.exists():
        return filtered
    return students


@register.filter
def is_linked_judge(user):
    """True when the logged-in user is an active linked judge.

    Judge logins are portal-only staff accounts (spec #20): the header uses
    this to swap the admin "Judges" link for their own portal link.
    Defensive on purpose: template tests render the header with stub user
    objects, so only query when this is a real, saved user.
    """
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return False
    if getattr(user, "pk", None) is None:
        return False
    try:
        from applications.program.models import Judge
        return Judge.objects.filter(user=user, is_active=True).exists()
    except (TypeError, ValueError):
        return False
