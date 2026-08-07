from django.test import TestCase
from django.urls import reverse
from applications.accounts.models import Madrasa, User
from applications.program.models import Category, Program, Student, Prize, Position
from applications.scoreboard.models import Team

class ResultPosterPDFTests(TestCase):
    def setUp(self):
        # Create Madrasa
        self.madrasa = Madrasa.objects.create(
            name="Test Madrasa",
            meelad_fest_name="Meelad Fest 2026",
            sadr="Test Sadr"
        )
        
        # Create User
        self.user = User.objects.create_user(
            email="sadr@test.com",
            phone_number="9876543210",
            madrasa=self.madrasa,
            password="testpassword"
        )
        
        # Create Category
        self.category = Category.objects.create(
            name="Sub Juniors",
            madrasa=self.madrasa
        )
        
        # Create Program
        self.program = Program.objects.create(
            title="Qira'at",
            is_result_published=True
        )
        # Associate category with program (M2M)
        self.category.programs.add(self.program)
        
        # Create Team
        self.team = Team.objects.create(
            name="Al Hilal",
            madrasa=self.madrasa
        )
        
        # Create Student
        self.student = Student.objects.create(
            full_name="Ahmad",
            gender="male",
            code_number=101,
            category=self.category,
            team=self.team
        )
        
        # Create Position
        self.position = Position.objects.create(
            name="first",
            mark=5.0
        )
        
        # Create Prize
        self.prize = Prize.objects.create(
            student=self.student,
            program=self.program,
            position=self.position
        )

    def test_download_results_poster_pdf_status_and_content_type(self):
        # Force login
        self.client.force_login(self.user)
        
        # Get poster download URL
        url = reverse('download_results_poster_pdf', kwargs={
            'program_id': self.program.id,
            'section': 'boys'
        })
        
        # Call the endpoint
        response = self.client.get(url)
        
        # Assert status and type
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
