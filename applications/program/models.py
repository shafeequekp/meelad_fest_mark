from datetime import timedelta
import json

from django.conf import settings
from django.db import models
from django_extensions.db.fields import AutoSlugField
from django.core.exceptions import ValidationError
from django.db.models import Sum, F, Value, FloatField, ExpressionWrapper, IntegerField, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from utils.db import DateBaseModel
from applications.scoreboard.models import Team
from applications.accounts.models import Madrasa


# User = get_user_model()


def program_section_q(madrasa, section):
    """Return a Q filter scoping ``Program`` querysets to a fest section mode.

    ``section`` is one of ``Madrasa.FEST_TYPE_BOTH`` / ``FEST_TYPE_BOYS`` /
    ``FEST_TYPE_GIRLS``.

    Regular (individual) and group programs get their section from their
    category links: boys programs are linked via ``Category.programs`` (which
    shows up as ``program.category_set``) and girls programs via
    ``Category.programs_for_girls`` (``program.girls_categories``). General
    (team-wise) programs carry their section directly on ``Program.section``
    and belong to the madrasa through the ``Program.madrasa`` FK.
    """
    if section == Madrasa.FEST_TYPE_BOYS:
        return Q(category__madrasa=madrasa) | Q(
            is_general=True, section=Program.SECTION_BOYS, madrasa=madrasa
        )
    if section == Madrasa.FEST_TYPE_GIRLS:
        return Q(girls_categories__madrasa=madrasa) | Q(
            is_general=True, section=Program.SECTION_GIRLS, madrasa=madrasa
        )
    # 'both' (or any unrecognised value) -> everything owned by the madrasa.
    return (
        Q(category__madrasa=madrasa)
        | Q(girls_categories__madrasa=madrasa)
        | Q(madrasa=madrasa)
    )


class ProgramRule(DateBaseModel):
    madrasa = models.ForeignKey(Madrasa, on_delete=models.CASCADE, null=True, blank=True)
    max_program_per_head = models.IntegerField(null=True, blank=True)
    program_reg_link_active = models.BooleanField(default=False)
    parent_view_link_active = models.BooleanField(default=False)
    

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


class TrashItem(models.Model):
    """Restorable snapshot of a deleted Student/Program (undo delete).

    Deletes stay hard deletes (so every FK/queryset behaviour is unchanged);
    each delete first stores a full serialized snapshot here. The toast on the
    admin pages then offers an "Undo" button that hits ``restore_trash`` within
    the retention window, recreating the object with its original pk.
    """

    model_name = models.CharField(max_length=60)  # 'Student' / 'Program'
    object_id = models.PositiveIntegerField()
    summary = models.CharField(max_length=255)    # human label for the toast
    payload = models.TextField()                  # django serialize('json') of 1 obj
    # Reverse M2M links the serializer cannot see (JSON: {"Category.programs": [pk, ...]}).
    # Category.programs / programs_for_girls point AT Program, so a deleted
    # program would be restored orphaned from its category without this.
    reverse_links = models.TextField(blank=True, default='')
    madrasa = models.ForeignKey(Madrasa, on_delete=models.CASCADE, null=True, blank=True)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    deleted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-deleted_at']
        verbose_name_plural = 'Trash items'

    def __str__(self):
        return f'{self.model_name} #{self.object_id} — {self.summary}'

    RESTORE_WINDOW = timedelta(hours=24)

    # Reverse M2M links declared on the *other* model, as
    #   model_name -> ((accessor on obj, 'OwnerModel.field_name'), ...)
    # Django's serializer only walks fields declared on the model itself, so
    # these must be captured separately (see snapshot()/restore()).
    REVERSE_M2M = {
        'Program': (
            ('category_set', 'Category.programs'),
            ('girls_categories', 'Category.programs_for_girls'),
        ),
    }

    def is_restorable(self):
        return timezone.now() - self.deleted_at <= self.RESTORE_WINDOW

    def reverse_links_data(self):
        """Parsed reverse-link map: {'Category.programs': [pk, ...]}."""
        if not self.reverse_links:
            return {}
        try:
            return json.loads(self.reverse_links)
        except (TypeError, ValueError):
            return {}

    @classmethod
    def snapshot(cls, obj, user, madrasa):
        """Capture ``obj`` into a TrashItem and return it (not yet saved)."""
        from django.core import serializers
        payload = serializers.serialize('json', [obj])
        reverse = {}
        for accessor, owner_field in cls.REVERSE_M2M.get(type(obj).__name__, ()):
            pks = list(getattr(obj, accessor).values_list('pk', flat=True))
            if pks:
                reverse[owner_field] = pks
        return cls(
            model_name=type(obj).__name__,
            object_id=obj.pk,
            summary=str(obj),
            payload=payload,
            reverse_links=json.dumps(reverse) if reverse else '',
            madrasa=madrasa,
            deleted_by=user if getattr(user, 'pk', None) else None,
        )

    def restore(self):
        """Recreate the object from the snapshot. Returns the live instance."""
        from django.apps import apps
        from django.core import serializers
        obj = None
        for deserialized in serializers.deserialize('json', self.payload):
            obj = deserialized.object
            obj.pk = self.object_id  # keep the original pk
            obj.save(force_insert=True)
            # m2m links declared on the object itself (Program.participants ...)
            for field_name, pks in deserialized.m2m_data.items():
                getattr(obj, field_name).set(pks)
        # Re-attach links declared on the other side (Program -> Category.programs)
        for owner_field, pks in self.reverse_links_data().items():
            model_name, field_name = owner_field.split('.')
            model = apps.get_model('program', model_name)
            for owner in model.objects.filter(pk__in=pks):
                getattr(owner, field_name).add(obj)
        return obj


class Venue(DateBaseModel):
    name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, null=True, blank=True)
    # Every venue belongs to the madrasa that created it so venue lists are
    # scoped per account and other madrasas' venues never leak.
    madrasa = models.ForeignKey(
        Madrasa, on_delete=models.CASCADE, null=True, blank=True,
        related_name='venues',
    )

    def __str__(self):
        return self.name


class Program(DateBaseModel):
    title = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)  # rules and regulations
    slug = AutoSlugField(populate_from='title', unique=True)
    image = models.ImageField(max_length=1000, null=True, blank=True)
    participants = models.ManyToManyField(Student, blank=True)
    # For general programs the competing units are teams, not a single category.
    # Any student from any category within these teams counts as a participant,
    # and scores are awarded to the team as a whole.
    general_teams = models.ManyToManyField(Team, blank=True, related_name='general_programs')
    non_stage = models.BooleanField(default=False)
    is_group = models.BooleanField(default=False)
    is_general = models.BooleanField(default=False)

    # Boys/Girls section for GENERAL programs and group programs only. General programs are held
    # between teams irrespective of category (any team member can take part),
    # so their section is stored directly instead of via category links.
    # Group programs still derive their section from the category M2M links.
    SECTION_BOYS = 'boys'
    SECTION_GIRLS = 'girls'
    SECTION_CHOICES = ((SECTION_BOYS, 'Boys'), (SECTION_GIRLS, 'Girls'))
    section = models.CharField(max_length=10, choices=SECTION_CHOICES, null=True, blank=True)

    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, null=True, blank=True)
    scheduled_time = models.DateTimeField(null=True, blank=True)
    is_result_published = models.BooleanField(default=False)
    
    # Every program belongs to a madrasa. General (and group) programs get this
    # set when they are created. It mirrors Category.madrasa but lives on the
    # program itself, so team-wise general programs (which have no category
    # link) can still be scoped to their madrasa and appear in the list even
    # before/without any teams / categories are attached.
    madrasa = models.ForeignKey(
        Madrasa, on_delete=models.CASCADE, null=True, blank=True,
        related_name='programs',
    )

    def __str__(self):
        return self.title
    
    def participants_count(self):
        return self.participants.count()
    
    def program_category(self):
        if self.category_set.exists():
            return self.category_set.last().name
            # return f'{self.category_set.last().name} (Boys)'
        if self.girls_categories.exists():
            return self.girls_categories.last().name
            # return f'{self.girls_categories.last().name} (Girls)'


class Position(DateBaseModel):
    POSITIONS = (
        ('first', 'First'),
        ('second', 'Second'),
        ('third', 'Third'),
    )
    madrasa = models.ForeignKey(Madrasa, on_delete=models.CASCADE, null=True, blank=True, related_name='positions')
    name = models.CharField(max_length=15, choices=POSITIONS)
    mark = models.FloatField(default=0)

    class Meta:
        unique_together = (('madrasa', 'name'),)

    def __str__(self):
        return f'{self.name} > {self.mark}'


class Grade(DateBaseModel):
    GRADES = (
        ('a_grade', 'A Grade'),
        ('b_grade', 'B Grade'),
        ('c_grade', 'C Grade'),
    )
    madrasa = models.ForeignKey(Madrasa, on_delete=models.CASCADE, null=True, blank=True, related_name='grades')
    name = models.CharField(max_length=15, choices=GRADES, null=True, blank=True)
    mark = models.FloatField(default=0)

    class Meta:
        unique_together = (('madrasa', 'name'),)

    def __str__(self):
        return f'{self.name} > {self.mark}'


class GeneralPosition(DateBaseModel):
    POSITIONS = (
        ('first', 'First'),
        ('second', 'Second'),
        ('third', 'Third'),
    )
    madrasa = models.ForeignKey(Madrasa, on_delete=models.CASCADE, null=True, blank=True, related_name='general_positions')
    name = models.CharField(max_length=15, choices=POSITIONS)
    mark = models.FloatField(default=0)

    class Meta:
        unique_together = (('madrasa', 'name'),)

    def __str__(self):
        return self.name


class GroupPosition(DateBaseModel):
    POSITIONS = (
        ('first', 'First'),
        ('second', 'Second'),
        ('third', 'Third'),
    )
    madrasa = models.ForeignKey(Madrasa, on_delete=models.CASCADE, null=True, blank=True, related_name='group_positions')
    name = models.CharField(max_length=15, choices=POSITIONS)
    mark = models.FloatField(default=0)

    class Meta:
        unique_together = (('madrasa', 'name'),)

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

    participants = models.ManyToManyField(Student, blank=True, related_name='prizes')  # for group and general programs


    def __str__(self):
        return f'{self.program} > {self.position}'

    @staticmethod
    def get_team_grand_totals(madrasa, section='both'):
        """
        Returns each team in the given madrasa with total position + grade points.

        ``section`` scopes the totals to the active fest section mode
        ('both' / 'boys' / 'girls') so a boys-only fest never counts girls'
        individual prizes.
        """
        genders = {
            Madrasa.FEST_TYPE_BOYS: ['male'],
            Madrasa.FEST_TYPE_GIRLS: ['female'],
        }.get(section, ['male', 'female'])

        return (
            Prize.objects
            .filter(
                student__team__madrasa=madrasa,
                student__gender__in=genders,
                program__is_result_published=True
            )
            .values(
                "student__team__id",
                "student__team__name"
            )
            .annotate(
                pos_total=Coalesce(
                    Sum("position__mark"),
                    Value(0.0),
                    output_field=FloatField()
                ),
                grade_total=Coalesce(
                    Sum("grade__mark"),
                    Value(0.0),
                    output_field=FloatField()
                ),
                group_prgrm_total=Coalesce(
                    Sum("group_program_position__mark"),
                    Value(0.0),
                    output_field=FloatField()
                ),
                general_prgrm_total=Coalesce(
                    Sum("general_program_position__mark"),
                    Value(0.0),
                    output_field=FloatField()
                ),
            )
            .annotate(
                grand_total=ExpressionWrapper(
                    F("pos_total")
                    + F("grade_total")
                    + F("group_prgrm_total")
                    + F("general_prgrm_total"),
                    output_field=FloatField(),
                )
            )
            .order_by("-grand_total")
        )

    @staticmethod
    def get_team_leaderboard(madrasa, section='both'):
        """Build a full team scoreboard for ``madrasa`` from published results.

        ``section`` scopes the leaderboard to the active fest section mode
        ('both' / 'boys' / 'girls'): individual prizes are restricted to the
        section's gender and group/general prizes to the section's programs.

        Returns a list sorted by grand total (highest first) of dicts::

            {
                'team': Team,
                'rank': int,
                'category_rows': [
                    {'category': Category, 'boys': float, 'girls': float, 'total': float},
                    ...
                ],
                'individual_total': float,  # position + grade marks (all categories)
                'group_total': float,       # team-level group program marks
                'general_total': float,     # team-level general program marks
                'grand_total': float,       # individual + group + general
            }

        Only published programs contribute points so the public parents' view
        never leaks in-progress results.
        """
        from applications.program.models import Category

        genders = {
            Madrasa.FEST_TYPE_BOYS: ['male'],
            Madrasa.FEST_TYPE_GIRLS: ['female'],
        }.get(section, ['male', 'female'])

        teams = list(Team.objects.filter(madrasa=madrasa).order_by('name'))
        if not teams:
            return []

        categories = list(Category.objects.filter(madrasa=madrasa).order_by('name'))
        team_ids = [team.pk for team in teams]
        category_ids = [cat.pk for cat in categories]

        # Individual-program points (position + grade) per team/category/gender.
        # Each mark is coalesced individually so a prize that only has a grade
        # (or only a position) still counts correctly. When the fest runs a
        # single section, only that section's gender contributes.
        individual_rows = (
            Prize.objects
            .filter(
                student__team_id__in=team_ids,
                student__category_id__in=category_ids,
                student__gender__in=genders,
                program__is_result_published=True,
            )
            .exclude(Q(position__isnull=True) & Q(grade__isnull=True))
            .values('student__team_id', 'student__category_id', 'student__gender')
            .annotate(
                total=Coalesce(
                    Sum(
                        Coalesce(F('position__mark'), Value(0.0))
                        + Coalesce(F('grade__mark'), Value(0.0)),
                        output_field=FloatField(),
                    ),
                    Value(0.0),
                    output_field=FloatField(),
                )
            )
        )

        individual_map = {}
        for row in individual_rows:
            team_scores = individual_map.setdefault(row['student__team_id'], {})
            cat_scores = team_scores.setdefault(
                row['student__category_id'], {'male': 0.0, 'female': 0.0}
            )
            cat_scores[row['student__gender']] = row['total']

        # Team-level group + general program points. On a single-section fest
        # only that section's programs contribute (group programs via their
        # category links, general programs via their own section field). In
        # the default 'both' mode every published team prize counts — matching
        # the original behaviour, since legacy programs may carry no madrasa
        # link at all.
        team_program_filters = Q(team_id__in=team_ids) & Q(
            program__is_result_published=True
        )
        if section in (Madrasa.FEST_TYPE_BOYS, Madrasa.FEST_TYPE_GIRLS):
            team_program_filters &= Q(
                program__in=Program.objects.filter(program_section_q(madrasa, section))
            )
        team_program_rows = (
            Prize.objects
            .filter(team_program_filters)
            .values('team_id')
            .annotate(
                group_total=Coalesce(
                    Sum('group_program_position__mark'),
                    Value(0.0),
                    output_field=FloatField(),
                ),
                general_total=Coalesce(
                    Sum('general_program_position__mark'),
                    Value(0.0),
                    output_field=FloatField(),
                ),
            )
        )
        team_program_map = {row['team_id']: row for row in team_program_rows}

        leaderboard = []
        for team in teams:
            team_cat_map = individual_map.get(team.pk, {})

            category_rows = []
            individual_total = 0.0
            for category in categories:
                cat_scores = team_cat_map.get(category.pk, {'male': 0.0, 'female': 0.0})
                boys = cat_scores.get('male', 0.0) or 0.0
                girls = cat_scores.get('female', 0.0) or 0.0
                subtotal = boys + girls
                individual_total += subtotal
                category_rows.append({
                    'category': category,
                    'boys': boys,
                    'girls': girls,
                    'total': subtotal,
                })

            prog = team_program_map.get(team.pk, {})
            group_total = prog.get('group_total', 0.0) or 0.0
            general_total = prog.get('general_total', 0.0) or 0.0
            grand_total = individual_total + group_total + general_total

            leaderboard.append({
                'team': team,
                'category_rows': category_rows,
                'individual_total': individual_total,
                'group_total': group_total,
                'general_total': general_total,
                'grand_total': grand_total,
            })

        leaderboard.sort(key=lambda row: row['grand_total'], reverse=True)
        for rank, row in enumerate(leaderboard, start=1):
            row['rank'] = rank

        return leaderboard

        # return (
        #     Prize.objects
        #     .filter(student__team__madrasa=madrasa, program__is_result_published=True)
        #     .values("student__team__id", "student__team__name")
        #     .annotate(
        #         pos_total=Coalesce(Sum("position__mark"), 0.0),
        #         grade_total=Coalesce(Sum("grade__mark"), 0.0),
        #         group_prgrm_total=Coalesce(Sum("group_program_position__mark"), 0.0),
        #         general_prgrm_total=Coalesce(Sum("general_program_position__mark"), 0.0),
        #     )
        #     .annotate(
        #         grand_total=ExpressionWrapper(
        #             F("pos_total") + F("grade_total") + F('group_prgrm_total') + F('general_prgrm_total'),
        #             output_field=FloatField()
        #         )
        #     )
        #     .order_by("-grand_total")
        # )


        

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


class EvaluationCriterion(DateBaseModel):
    """One marking criterion of a program's digital judging sheet.

    Criteria are per-program so each competition can define its own marking
    scheme (e.g. Content /25, Pronunciation /20, Presentation /20). Judges
    score every participant against these criteria on the evaluation sheet.
    """

    program = models.ForeignKey(
        Program, on_delete=models.CASCADE, related_name="evaluation_criteria"
    )
    name = models.CharField(max_length=125)
    max_marks = models.FloatField(default=10)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.program.title} > {self.name} ({self.max_marks:g})"


class Judge(DateBaseModel):
    """A fest judge who can be assigned programs to evaluate digitally.

    Every judge belongs to one madrasa (list/assignment scoping). A judge may
    optionally link to a login account (accounts.User) — that user then sees
    only the judge portal, never the admin screens. Admin/staff users can also
    access the portal to preview each judge's evaluation sheet.
    """

    madrasa = models.ForeignKey(
        Madrasa, on_delete=models.CASCADE, null=True, blank=True,
        related_name="judges",
    )
    name = models.CharField(max_length=125)
    # Short display code (e.g. roll/chit number) shown in the judge's profile
    # and portal heading. Unique per madrasa — validated in the judges view.
    code = models.CharField(max_length=50, null=True, blank=True)
    expertise = models.CharField(max_length=255, null=True, blank=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="judge_profile",
        help_text="Optional login account that unlocks the judge portal.",
    )
    is_active = models.BooleanField(default=True)
    programs = models.ManyToManyField(
        Program, blank=True, related_name="judges",
        help_text="Programs this judge is assigned to evaluate.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Evaluation(DateBaseModel):
    """A judge's scores for one participant (student or team) in a program.

    ``scores`` stores the per-criterion marks as a JSON object string
    (``{criterion_id: mark}``) so no JSON-field DB support is assumed. The
    sum of those marks is cached in ``total_marks`` for ranking queries.
    """

    madrasa = models.ForeignKey(
        Madrasa, on_delete=models.CASCADE, null=True, blank=True,
        related_name="evaluations",
    )
    judge = models.ForeignKey(
        Judge, on_delete=models.CASCADE, related_name="evaluations"
    )
    program = models.ForeignKey(
        Program, on_delete=models.CASCADE, related_name="evaluations"
    )
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, null=True, blank=True,
        related_name="evaluations",
    )
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, null=True, blank=True,
        related_name="evaluations",
    )
    scores = models.TextField(default="{}")  # JSON object: {criterion_id: mark}
    total_marks = models.FloatField(default=0)

    class Meta:
        unique_together = (("judge", "program", "student", "team"),)
        ordering = ["-modified"]

    def __str__(self):
        who = self.student or self.team or "?"
        return f"{self.judge} > {self.program.title} > {who} = {self.total_marks:g}"

    def get_scores(self):
        """Return the scores dict (``{criterion_id: mark}``)."""
        try:
            return json.loads(self.scores or "{}")
        except (ValueError, TypeError):
            return {}

    @staticmethod
    def rankings(program, madrasa):
        """Aggregate all evaluations for ``program`` into ranked contestant rows.

        Each contestant's final score is the *mean* of all active judges'
        totals (so multiple judges are treated equally regardless of how
        many forms they've filled). Returns a list of dicts sorted descending::

            {
                'student': Student | None,
                'team': Team | None,
                'contestant_name': str,
                'avg': float,
                'evaluations_count': int,
            }
        """
        evals = (
            Evaluation.objects
            .filter(program=program, madrasa=madrasa)
            .select_related("judge", "student", "team")
        )
        grouped = {}
        for ev in evals:
            if not ev.judge or not ev.judge.is_active:
                continue
            key = ("student", ev.student_id) if ev.student else ("team", ev.team_id)
            row = grouped.setdefault(key, {
                "student": ev.student,
                "team": ev.team,
                "total": 0.0,
                "count": 0,
            })
            row["total"] += ev.total_marks or 0.0
            row["count"] += 1

        ranked = []
        for key, row in grouped.items():
            if row["count"] == 0:
                continue
            who = row["student"] or row["team"]
            ranked.append({
                "student": row["student"],
                "team": row["team"],
                "contestant_name": getattr(who, "full_name", None) or getattr(who, "name", "—"),
                "avg": round(row["total"] / row["count"], 2),
                "evaluations_count": row["count"],
            })
        ranked.sort(key=lambda r: r["avg"], reverse=True)
        return ranked


