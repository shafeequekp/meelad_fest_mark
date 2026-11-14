import secrets

from django.db import models
from applications.accounts.models import Madrasa


class ScreeningLink(models.Model):
    """A shareable, public link that screens a madrasa's slides without login."""
    madrasa = models.ForeignKey(Madrasa, on_delete=models.CASCADE, related_name='screening_links')
    token = models.CharField(max_length=64, unique=True, editable=False)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.madrasa.name} screening ({self.token[:8]}...)"

    class Meta:
        ordering = ['-created_at']


class Team(models.Model):
    COLOR_CHOICES = (
        ('blue', 'Blue'),
        ('green', 'Green'),
        ('red', 'Red'),
        ('white', 'White'),
        ('yellow', 'Yellow'),
        ('orange', 'Orange'),
        ('purple', 'Purple'),
        ('pink', 'Pink'),
        ('indigo', 'Indigo'),
        ('violet', 'Violet'),
        ('fuchsia', 'Fuchsia'),
        ('rose', 'Rose'),
        ('cyan', 'Cyan'),
        ('sky', 'Sky'),
        ('teal', 'Teal'),
        ('emerald', 'Emerald'),
        ('lime', 'Lime'),
        ('amber', 'Amber'),
        ('slate', 'Slate'),
        ('gray', 'Gray'),
    )

    COLOR_HEX = {
        'blue': '#2563eb',
        'green': '#16a34a',
        'red': '#dc2626',
        'white': '#ffffff',
        'yellow': '#eab308',
        'orange': '#ea580c',
        'purple': '#9333ea',
        'pink': '#db2777',
        'indigo': '#4f46e5',
        'violet': '#7c3aed',
        'fuchsia': '#c026d3',
        'rose': '#e11d48',
        'cyan': '#0891b2',
        'sky': '#0284c7',
        'teal': '#0d9488',
        'emerald': '#059669',
        'lime': '#65a30d',
        'amber': '#d97706',
        'slate': '#475569',
        'gray': '#64748b',
    }

    name = models.CharField(max_length=55)
    madrasa = models.ForeignKey(Madrasa, on_delete=models.CASCADE, null=True, blank=True)
    leader = models.CharField(max_length=125, null=True, blank=True)
    assistant = models.CharField(max_length=125, null=True, blank=True)
    mentor = models.CharField(max_length=125, null=True, blank=True)
    assistant_mentor = models.CharField(max_length=125, null=True, blank=True)
    colour = models.CharField(max_length=55, null=True, blank=True, choices=COLOR_CHOICES)
    girls_leader = models.CharField(max_length=125, null=True, blank=True)
    girls_leader_assistant = models.CharField(max_length=125, null=True, blank=True)
    # general_point = models.FloatField(default=0)
    # group_point = models.FloatField(default=0)

    def get_colour_hex(self):
        return self.COLOR_HEX.get(self.colour, '#6366f1')

    def theme_context(self):
        """CSS variables + flags for team-coloured inner pages."""
        hex_color = self.get_colour_hex()
        h = hex_color.lstrip('#')
        try:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except ValueError:
            r, g, b = 99, 102, 241
            hex_color = '#6366f1'
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        is_light = luma >= 180
        dark_hex = '#{:02x}{:02x}{:02x}'.format(
            max(0, int(r * 0.42)), max(0, int(g * 0.42)), max(0, int(b * 0.42)))
        if is_light:
            header_hex = dark_hex if dark_hex != '#000000' else '#334155'
            on_accent = '#1e293b'
        else:
            header_hex = hex_color
            on_accent = '#ffffff'
        return {
            'has_team_theme': True,
            'active_team': self,
            'team_theme_hex': hex_color,
            'team_theme_rgb': f'{r}, {g}, {b}',
            'team_theme_dark_hex': dark_hex,
            'team_theme_header_hex': header_hex,
            'team_theme_on_accent': on_accent,
            'team_theme_is_light': is_light,
            'team_theme_label': self.get_colour_display() if self.colour else '',
        }

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
