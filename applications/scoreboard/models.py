from django.db import models
from applications.accounts.models import Madrasa


class Team(models.Model):
    COLOR_CHOICES = (
        ('indigo', 'Indigo'),
        ('emerald', 'Emerald'),
        ('rose', 'Rose'),
        ('amber', 'Amber'),
        ('sky', 'Sky'),
        ('violet', 'Violet'),
        ('slate', 'Slate'),
        ('gray', 'Gray'),
        ('blue', 'Blue'),
        ('green', 'Green'),
        ('red', 'Red'),
        ('white', 'White'),
    )

    COLOR_HEX = {
        'indigo': '#4f46e5',
        'emerald': '#059669',
        'rose': '#e11d48',
        'amber': '#d97706',
        'sky': '#0284c7',
        'violet': '#7c3aed',
        'slate': '#475569',
        'gray': '#64748b',
        'blue': '#2563eb',
        'green': '#16a34a',
        'red': '#dc2626',
        'white': '#ffffff',
    }

    name = models.CharField(max_length=55)
    madrasa = models.ForeignKey(Madrasa, on_delete=models.CASCADE, null=True, blank=True)
    leader = models.CharField(max_length=125, null=True, blank=True)
    assistant = models.CharField(max_length=125, null=True, blank=True)
    mentor = models.CharField(max_length=125, null=True, blank=True)
    assistant_mentor = models.CharField(max_length=125, null=True, blank=True)
    colour = models.CharField(max_length=55, null=True, blank=True, choices=COLOR_CHOICES)
    # general_point = models.FloatField(default=0)
    # group_point = models.FloatField(default=0)

    def get_colour_hex(self):
        return self.COLOR_HEX.get(self.colour, '#6366f1')

    def __str__(self):
        return self.name



# ## this model will be removed.. temporary one
# class Mark(models.Model):
#     SECTIONS = (
#         ('boys', 'Boys'),
#         ('girls', 'Girls'),
#     )
#     team = models.ForeignKey(Team, on_delete=models.CASCADE)
#     section = models.CharField(max_length=20, choices=SECTIONS, default='boys')
#     super_senior = models.FloatField(default=0)
#     senior = models.FloatField(default=0)
#     junior = models.FloatField(default=0)
#     subjunior = models.FloatField(default=0)
#     kiddies = models.FloatField(default=0)
#     general = models.FloatField(default=0)
#
#     def __str__(self):
#         return f'{self.team.name} > {self.section}'
#
#     def get_section_total(self):
#         return sum([
#             self.super_senior,
#             self.senior,
#             self.junior,
#             self.subjunior,
#             self.kiddies,
#             self.general
#         ])
#
#     @classmethod
#     def get_team_grand_total(cls, team):
#         """Grand total for all sections of a team."""
#         marks = cls.objects.filter(team=team)
#         return sum(mark.get_section_total() for mark in marks)
