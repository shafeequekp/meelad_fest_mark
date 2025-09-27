from django.db import models
from applications.accounts.models import Madrasa


class Team(models.Model):
    name = models.CharField(max_length=55)
    madrasa = models.ForeignKey(Madrasa, on_delete=models.CASCADE, null=True, blank=True)
    leader = models.CharField(max_length=125, null=True, blank=True)
    assistant = models.CharField(max_length=125, null=True, blank=True)

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
