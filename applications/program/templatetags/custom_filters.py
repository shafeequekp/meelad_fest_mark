from django import template
from django.db.models import Sum, Q

from applications.program.models import Student, Prize

register = template.Library()


@register.filter
def non_stage(programs):
    return programs.filter(non_stage=True)


@register.filter
def stage(programs):
    return programs.filter(non_stage=False)


@register.simple_tag
def get_category_total(category, gender=None, team=None):
    students = Student.objects.filter(category=category)

    if gender:
        students = students.filter(gender=gender)
    if team:
        students = students.filter(team=team)

    student_ids = students.values_list("id", flat=True)

    # Sum position marks
    pos_marks = Prize.objects.filter(student_id__in=student_ids, position__isnull=False).aggregate(
        total=Sum("position__mark")
    )["total"] or 0

    # Sum grade marks
    grade_marks = Prize.objects.filter(student_id__in=student_ids, grade__isnull=False).aggregate(
        total=Sum("grade__mark")
    )["total"] or 0

    return pos_marks + grade_marks


@register.simple_tag
def get_section_total(gender, team):
    students = Student.objects.filter(gender=gender, team=team)

    student_ids = students.values_list("id", flat=True)

    # Sum position marks
    pos_marks = Prize.objects.filter(student_id__in=student_ids, position__isnull=False).aggregate(
        total=Sum("position__mark")
    )["total"] or 0

    # Sum grade marks
    grade_marks = Prize.objects.filter(student_id__in=student_ids, grade__isnull=False).aggregate(
        total=Sum("grade__mark")
    )["total"] or 0

    return int(pos_marks + grade_marks)
