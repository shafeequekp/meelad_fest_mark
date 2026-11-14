import os
import csv

from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from applications.program.models import Student, Program, Category
from applications.scoreboard.models import Team


class Command(BaseCommand):
    help = 'update programs'

    def handle(self, *args, **options):
        file_path = os.path.join(settings.BASE_DIR, "MAHABBA_programs.csv")

        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f"File not found: {file_path}"))
            return

        with open(file_path, newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)

            for row in reader:
                # Example: reading CSV values
                full_name = row.get("full_name")
                category_name = row.get("category")
                program_title = row.get("program")
                team = row.get('Select team')

                # # Get or create Category
                # category, _ = Category.objects.get_or_create(name=category_name)
                #
                # # Get or create Program
                # program, _ = Program.objects.get_or_create(title=program_title)
                #
                # # Get or create Student
                # student, _ = Student.objects.get_or_create(
                #     full_name=full_name,
                #     defaults={"category": category}
                # )
                #
                # # Add student to program participants
                # program.participants.add(student)

                self.stdout.write(self.style.SUCCESS(f"Processed: {full_name}"))

        self.stdout.write(self.style.SUCCESS('CSV import completed successfully'))
