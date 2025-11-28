from datetime import timedelta

from django.db import models
from django_extensions.db.fields import AutoSlugField
from django.core.exceptions import ValidationError
from django.db.models import Sum, F, Value, FloatField, ExpressionWrapper, IntegerField
from django.db.models.functions import Coalesce
from django.utils import timezone

from utils.db import DateBaseModel
from applications.scoreboard.models import Team
from applications.accounts.models import Madrasa


# User = get_user_model()


class ProgramRule(DateBaseModel):
    madrasa = models.ForeignKey(Madrasa, on_delete=models.CASCADE, null=True, blank=True)
    max_program_per_head = models.IntegerField(null=True, blank=True)
    program_reg_link_active = models.BooleanField(default=False)
    

    def __str__(self):
        return self.madrasa.name



class Category(DateBaseModel):
    name = models.CharField(max_length=125)
    description = models.CharField(max_length=255, null=True, blank=True)
    madrasa = models.ForeignKey(Madrasa, on_delete=models.CASCADE, null=True, blank=True)
    programs = models.ManyToManyField('Program', blank=True)
    programs_for_girls = models.ManyToManyField('Program', blank=True, related_name='girls_categories')

    def __str__(self):
        return self.name


class Student(DateBaseModel):
    GENDER = (
        ('male', 'Male'),
        ('female', 'Female')
    )
    full_name = models.CharField(max_length=125)
    gender = models.CharField(max_length=15, choices=GENDER, null=True, blank=True)
    code_number = models.IntegerField(null=True, blank=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, null=True, blank=True)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, null=True, blank=True)
    total_point = models.FloatField(default=0)

    def __str__(self):
        return self.full_name

    def clean(self):
        super().clean()
        if self.code_number and self.team:
            qs = Student.objects.filter(
                code_number=self.code_number,
                team__madrasa=self.team.madrasa
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    {"code_number": f"Code number {self.code_number} is already assigned to another student."}
                )


class Venue(DateBaseModel):
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return self.name


class Program(DateBaseModel):
    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)  # rules and regulations
    slug = AutoSlugField(populate_from='title', unique=True)
    image = models.ImageField(max_length=1000, null=True, blank=True)
    participants = models.ManyToManyField(Student, blank=True)
    non_stage = models.BooleanField(default=False)
    is_group = models.BooleanField(default=False)
    is_general = models.BooleanField(default=False)
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, null=True, blank=True)
    scheduled_time = models.DateTimeField(null=True, blank=True)
    is_result_published = models.BooleanField(default=False)

    def __str__(self):
        return self.title


class Position(DateBaseModel):
    POSITIONS = (
        ('first', 'First'),
        ('second', 'Second'),
        ('third', 'Third'),
    )
    name = models.CharField(max_length=15, choices=POSITIONS)
    mark = models.FloatField(default=0)

    def __str__(self):
        return f'{self.name} > {self.mark}'


class Grade(DateBaseModel):
    GRADES = (
        ('a_grade', 'A Grade'),
        ('b_grade', 'B Grade'),
        ('c_grade', 'C Grade'),
    )
    name = models.CharField(max_length=15, choices=GRADES, null=True, blank=True)
    mark = models.FloatField(default=0)

    def __str__(self):
        return f'{self.name} > {self.mark}'


class GeneralPosition(DateBaseModel):
    POSITIONS = (
        ('first', 'First'),
        ('second', 'Second'),
        ('third', 'Third'),
    )
    name = models.CharField(max_length=15, choices=POSITIONS)
    mark = models.FloatField(default=0)

    def __str__(self):
        return self.name


class GroupPosition(DateBaseModel):
    POSITIONS = (
        ('first', 'First'),
        ('second', 'Second'),
        ('third', 'Third'),
    )
    name = models.CharField(max_length=15, choices=POSITIONS)
    mark = models.FloatField(default=0)

    def __str__(self):
        return self.name


class Prize(DateBaseModel):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, null=True, blank=True)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, null=True, blank=True)  # for group and general programs
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    position = models.ForeignKey(Position, on_delete=models.CASCADE, null=True, blank=True)  # for individual programs
    grade = models.ForeignKey(Grade, on_delete=models.CASCADE, null=True, blank=True)  # grades also for individual programs
    group_program_position = models.ForeignKey(GroupPosition, on_delete=models.CASCADE, null=True, blank=True)  # for group programs
    general_program_position = models.ForeignKey(GeneralPosition, on_delete=models.CASCADE, null=True, blank=True)  # for general programs
    remarks = models.CharField(max_length=255, null=True, blank=True)


    def __str__(self):
        return f'{self.program} > {self.position}'

    @staticmethod
    def get_team_grand_totals(madrasa):
        """
        Returns each team in the given madrasa with total position + grade points.
        """
        return (
            Prize.objects
            .filter(student__team__madrasa=madrasa, program__is_result_published=True)
            .values("student__team__id", "student__team__name")
            .annotate(
                pos_total=Coalesce(Sum("position__mark"), 0.0),
                grade_total=Coalesce(Sum("grade__mark"), 0.0),
                group_prgrm_total=Coalesce(Sum("group_program_position__mark"), 0.0),
                general_prgrm_total=Coalesce(Sum("general_program_position__mark"), 0.0),
            )
            .annotate(
                grand_total=ExpressionWrapper(
                    F("pos_total") + F("grade_total") + F('group_prgrm_total') + F('general_prgrm_total'),
                    output_field=FloatField()
                )
            )
            .order_by("grand_total")
        )

    # @staticmethod
    # def get_team_grand_totals():
    #     """
    #     Returns each team with total position + grade points.
    #     """
    #     return (
    #         Prize.objects
    #         .values("student__team__id", "student__team__name")
    #         .annotate(
    #             pos_total=Coalesce(Sum("position__mark"), 0.0),
    #             grade_total=Coalesce(Sum("grade__mark"), 0.0)
    #         )
    #         .annotate(
    #             grand_total=ExpressionWrapper(
    #                 F("pos_total") + F("grade_total"),
    #                 output_field=FloatField()
    #             )
    #         )
    #         .order_by("student__team__name")
    #     )

    # @classmethod
    # def get_team_total(cls, team):
    #     """
    #     Return the grand total (boys + girls, all categories) for a given team.
    #     """
    #     # Position marks
    #     pos_total = (
    #             cls.objects.filter(student__team=team, position__isnull=False)
    #             .aggregate(total=Sum("position__mark"))
    #             .get("total") or 0
    #     )
    #
    #     # Grade marks
    #     grade_total = (
    #             cls.objects.filter(student__team=team, grade__isnull=False)
    #             .aggregate(total=Sum("grade__mark"))
    #             .get("total") or 0
    #     )
    #
    #     return pos_total + grade_total


