from django import forms
from applications.program.models import Category, Student, Program
from applications.scoreboard.models import Team


class CategoryForm(forms.ModelForm):

    class Meta:
        model = Category
        exclude = ['madrasa', 'programs']

    def clean_name(self):
        """Normalize the category name before it is saved.

        Wipes inconsistent user casing so every name is stored in one
        consistent form: outer whitespace is stripped, any runs of inner
        whitespace collapse to a single space, and every word is Capitalized
        ("  SEnIoR   bOYS  " -> "Senior Boys").
        """
        name = self.cleaned_data.get("name")
        if name:
            name = " ".join(name.split())
            name = " ".join(word.capitalize() for word in name.split(" "))
        return name


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

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['gender'].required = True
        # Optional: add a placeholder like "-- Select Gender --"
        self.fields['gender'].empty_label = "-- Select Gender --"
        self.team = team  # inject team from view

    def clean(self):
        cleaned_data = super().clean()
        code_number = cleaned_data.get("code_number")

        if code_number and self.team:
            qs = Student.objects.filter(
                code_number=code_number,
                team__madrasa=self.team.madrasa
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error(
                    "code_number",
                    f"Code number {code_number} is already assigned to another student."
                )

        return cleaned_data


class EditStudentForm(forms.ModelForm):
    """Form used to edit an existing student's details (name/code/team)."""

    class Meta:
        model = Student
        fields = ['full_name', 'gender', 'code_number', 'team']
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
            'team': forms.Select(
                attrs={'class': 'w-full border rounded-lg p-2'}
            ),
        }

    def __init__(self, *args, madrasa=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['gender'].required = True
        self.fields['gender'].empty_label = "-- Select Gender --"
        self.fields['team'].required = True
        if madrasa:
            self.fields['team'].queryset = Team.objects.filter(madrasa=madrasa).order_by('name')
        elif self.instance.pk and self.instance.team:
            # fall back to the madrasa the student currently belongs to
            self.fields['team'].queryset = Team.objects.filter(
                madrasa=self.instance.team.madrasa
            ).order_by('name')

    def clean(self):
        cleaned_data = super().clean()
        code_number = cleaned_data.get("code_number")
        team = cleaned_data.get("team")

        # Validate uniqueness against the (possibly new) selected team's madrasa
        if code_number and team:
            qs = Student.objects.filter(
                code_number=code_number,
                team__madrasa=team.madrasa
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error(
                    "code_number",
                    f"Code number {code_number} is already assigned to another student."
                )

        return cleaned_data


class ProgramForm(forms.ModelForm):

    class Meta:
        model = Program
        fields = ['title', 'description', 'non_stage', 'is_group', 'is_general']
        widgets = {
            'title': forms.TextInput(
                attrs={'class': 'w-full border rounded-lg p-2'}
            ),
            'description': forms.TextInput(
                attrs={'class': 'w-full border rounded-lg p-2'}
            ),
            'non_stage': forms.RadioSelect(choices=[(True, 'Yes'), (False, 'No')]),
            'is_group': forms.RadioSelect(choices=[(True, 'Yes'), (False, 'No')]),
            'is_general': forms.RadioSelect(choices=[(True, 'Yes'), (False, 'No')]),
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
