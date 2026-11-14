"""Management command to load default prize values for existing madrasas.

Usage:
    python manage.py load_default_prizes

This command sets the default prize values for all madrasas that don't have
mark configurations yet:
    1st: 5, 2nd: 3, 3rd: 1
    Grades: A=3, B=2, C=1
    Group: 1st=10, 2nd=7, 3rd=5
    General: 1st=10, 2nd=7, 3rd=5
"""

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from applications.program.models import ProgramRule, Program, Position, Grade, GroupPosition, GeneralPosition


class Command(BaseCommand):
    help = 'Load default prize values for existing madrasas'

    def handle(self, *args, **options):
        User = get_user_model()
        users = User.objects.filter(madrasa__isnull=False).distinct()

        self.stdout.write(self.style.WARNING('Loading default prize values...'))
        self.stdout.write(f'Found {users.count()} users with madrasa assigned.')

        count = 0
        for user in users:
            madrasa = user.madrasa
            config, created = ProgramRule.objects.get_or_create(madrasa=madrasa)

            # Only set defaults if they haven't been configured yet
            # (i.e., if existing marks are None or 0)
            positions = {
                'first': 5,
                'second': 3,
                'third': 1,
            }
            grades = {
                'a_grade': 3,
                'b_grade': 2,
                'c_grade': 1,
            }
            group_positions = {
                'first': 10,
                'second': 7,
                'third': 5,
            }
            general_prizes = {
                'first': 10,
                'second': 7,
                'third': 5,
            }

            for name, mark in positions.items():
                obj, created = Position.objects.update_or_create(
                    name=name,
                    madrasa=madrasa,
                    defaults={'mark': mark}
                )
                if created:
                    self.stdout.write(f'  Created Position: {name} = {mark}')

            for name, mark in grades.items():
                obj, created = Grade.objects.update_or_create(
                    name=name,
                    madrasa=madrasa,
                    defaults={'mark': mark}
                )
                if created:
                    self.stdout.write(f'  Created Grade: {name} = {mark}')

            for name, mark in group_positions.items():
                obj, created = GroupPosition.objects.update_or_create(
                    name=name,
                    madrasa=madrasa,
                    defaults={'mark': mark}
                )
                if created:
                    self.stdout.write(f'  Created GroupPosition: {name} = {mark}')

            for name, mark in general_prizes.items():
                obj, created = GeneralPosition.objects.update_or_create(
                    name=name,
                    madrasa=madrasa,
                    defaults={'mark': mark}
                )
                if created:
                    self.stdout.write(f'  Created GeneralPosition: {name} = {mark}')

            count += 1

        self.stdout.write(self.style.SUCCESS(
            f'Successfully loaded default prize values for {count} madrasas.'
        ))
