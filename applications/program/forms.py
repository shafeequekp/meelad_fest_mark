from django import forms
from applications.program.models import Category, Student, Program
from applications.scoreboard.models import Team


class CategoryForm(forms.ModelForm):

    class Meta:
        model = Category
        exclude = ['madrasa', 'programs']


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = ['full_name', 'gender', 'code_number']
        widgets = {
            'full_name': forms.TextInput(
                attrs={'class': 'w-full border rounded-lg p-2'}
            ),
            'gender': forms.Select(
                attrs={'class': 'w-full border rounded-lg p-2'}
            ),
            'code_number': forms.NumberInput(
                attrs={'class': 'w-full border rounded-lg p-2'}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['gender'].required = True
        # Optional: add a placeholder like "-- Select Gender --"
        self.fields['gender'].empty_label = "-- Select Gender --"


class ProgramForm(forms.ModelForm):

    class Meta:
        model = Program
        fields = ['title', 'description', 'non_stage']
        widgets = {
            'title': forms.TextInput(
                attrs={'class': 'w-full border rounded-lg p-2'}
            ),
            'description': forms.TextInput(
                attrs={'class': 'w-full border rounded-lg p-2'}
            ),
            'non_stage': forms.RadioSelect(choices=[(True, 'Yes'), (False, 'No')])
        }


# class ProgramRegisterForm(forms.Form):
#     team = forms.ModelChoiceField(
#         queryset=Team.objects.none(),
#         label="Select Team",
#         widget=forms.Select(attrs={'class': 'form-select'})
#     )
#     gender = forms.ChoiceField(
#         choices=[('male', 'Male'), ('female', 'Female')],
#         label="Select Gender",
#         widget=forms.Select(attrs={'class': 'form-select'})
#     )
#     category = forms.ModelChoiceField(
#         queryset=Category.objects.none(),
#         label="Select Category",
#         widget=forms.Select(attrs={'class': 'form-select'})
#     )
#     student = forms.ModelChoiceField(
#         queryset=Student.objects.none(),
#         label="Select Student",
#         widget=forms.Select(attrs={'class': 'form-select'})
#     )
#     programs = forms.ModelMultipleChoiceField(
#         queryset=Program.objects.all(),
#         label="Select Programs",
#         widget=forms.CheckboxSelectMultiple
#     )
#
#     def __init__(self, *args, **kwargs):
#         user = kwargs.pop('user', None)
#         super().__init__(*args, **kwargs)
#         if user and user.madrasa:
#             self.fields['team'].queryset = Team.objects.filter(madrasa=user.madrasa)
