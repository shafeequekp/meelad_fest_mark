from django.db import models
from django_extensions.db.fields import AutoSlugField
from django.core.exceptions import ValidationError

from utils.db import DateBaseModel
from applications.scoreboard.models import Team
from applications.accounts.models import Madrasa


# User = get_user_model()


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
        if self.code_number:
            qs = Student.objects.filter(code_number=self.code_number)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    {"code_number": _(f"Code number {self.code_number} is already assigned to another student.")}
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
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, null=True, blank=True)
    scheduled_time = models.DateTimeField(null=True, blank=True)

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


class Prize(DateBaseModel):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    program = models.ForeignKey(Program, on_delete=models.CASCADE)
    position = models.ForeignKey(Position, on_delete=models.CASCADE, null=True, blank=True)
    grade = models.ForeignKey(Grade, on_delete=models.CASCADE, null=True, blank=True)
    remarks = models.CharField(max_length=255, null=True, blank=True)


    def __str__(self):
        return f'{self.program} > {self.position}'

