from django.contrib import admin

from .models import Category, Student, Program, Prize, Position, Grade, Venue


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    filter_horizontal = ['programs', 'programs_for_girls']


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'gender', 'code_number', 'category', 'team', 'total_point')
    list_filter = ('gender', 'category', 'team')
    search_fields = ('full_name', 'code_number')


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ('title', 'category_display', 'slug', 'non_stage')
    list_editable = ['non_stage']
    search_fields = ('title',)
    filter_horizontal = ['participants']

    def category_display(self, obj):
        # show categories linked to program (ManyToManyField on Category)
        return ", ".join([c.name for c in obj.category_set.all()])
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
    pass
