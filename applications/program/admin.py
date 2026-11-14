from django.contrib import admin

from .models import Category, Student, Program, Prize, Position, Grade, Venue, GeneralPosition, GroupPosition, ProgramRule, Judge, Evaluation, EvaluationCriterion


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    filter_horizontal = ['programs', 'programs_for_girls']


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'gender', 'code_number', 'category', 'team', 'total_point')
    list_filter = ('gender', 'category', 'team', 'team__madrasa')
    search_fields = ('full_name', 'code_number')


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ('title', 'category_display', 'slug', 'non_stage', 'is_result_published')
    list_editable = ['non_stage', 'is_result_published']
    list_filter = ['non_stage', 'venue', 'madrasa', 'is_result_published']
    search_fields = ('title',)
    filter_horizontal = ['participants']

    def category_display(self, obj):
        # show categories linked to program (ManyToManyField on Category)
        return ", ".join([c.name for c in obj.category_set.all()] + [f'{cat.name} (girls)' for cat in obj.girls_categories.all()])
    category_display.short_description = "Categories"


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = ('name', 'mark')


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ('name', 'mark')


@admin.register(Prize)
class PrizeAdmin(admin.ModelAdmin):
    list_display = ('student', 'program', 'position', 'grade', 'remarks')
    list_filter = ('program', 'position', 'grade')
    search_fields = ('student__full_name', 'program__title')


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ('name', 'madrasa', 'description')
    list_filter = ('madrasa',)
    search_fields = ('name', 'description')

admin.site.register(GeneralPosition)
admin.site.register(GroupPosition)
admin.site.register(ProgramRule)


@admin.register(Judge)
class JudgeAdmin(admin.ModelAdmin):
    list_display = ('name', 'madrasa', 'expertise', 'is_active', 'program_count')
    list_filter = ('madrasa', 'is_active')
    search_fields = ('name', 'expertise')
    filter_horizontal = ['programs']

    def program_count(self, obj):
        return obj.programs.count()
    program_count.short_description = "Programs"


@admin.register(EvaluationCriterion)
class EvaluationCriterionAdmin(admin.ModelAdmin):
    list_display = ('program', 'name', 'max_marks')
    list_filter = ('program__madrasa',)
    search_fields = ('name', 'program__title')


@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
    list_display = ('judge', 'program', 'student', 'team', 'total_marks')
    list_filter = ('program__madrasa', 'judge')
    search_fields = ('student__full_name', 'program__title', 'judge__name')
