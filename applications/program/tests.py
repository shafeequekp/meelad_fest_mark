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

    def test_delete_student_endpoint(self):
        self.client.force_login(self.user)

        student = Student.objects.create(
            full_name="Delete Me",
            gender="male",
            code_number=999,
            category=self.category,
            team=self.team
        )

        url = reverse('delete_student', kwargs={'student_id': student.id})
        response = self.client.post(url, {'next': reverse('category_detail', kwargs={'pk': self.category.id})})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Student.objects.filter(id=student.id).exists())

    def test_edit_team_endpoint(self):
        self.client.force_login(self.user)

        url = reverse('edit_team', kwargs={'team_id': self.team.id})
        response = self.client.post(url, {
            'name': 'Updated Team',
            'leader': 'Updated Leader',
            'assistant': 'Updated Assistant',
        })

        self.assertEqual(response.status_code, 302)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, 'Updated Team')
        self.assertEqual(self.team.leader, 'Updated Leader')
        self.assertEqual(self.team.assistant, 'Updated Assistant')

    def test_delete_program_endpoint(self):
        self.client.force_login(self.user)

        url = reverse('delete_program', kwargs={'program_id': self.program.id})
        response = self.client.post(url, {'next': reverse('program_list')})

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Program.objects.filter(id=self.program.id).exists())

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
