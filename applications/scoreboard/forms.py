from django import forms
from applications.scoreboard.models import Team


class TeamForm(forms.ModelForm):

    class Meta:
        model = Team
        fields = ['name', 'madrasa', 'leader', 'assistant', 'mentor', 'assistant_mentor', 'colour', 'girls_leader', 'girls_leader_assistant']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full border rounded-md p-2'}),
            'madrasa': forms.Select(attrs={'class': 'w-full border rounded-md p-2'}),
            'leader': forms.TextInput(attrs={'class': 'w-full border rounded-md p-2'}),
            'assistant': forms.TextInput(attrs={'class': 'w-full border rounded-md p-2'}),
            'mentor': forms.TextInput(attrs={'class': 'w-full border rounded-md p-2'}),
            'assistant_mentor': forms.TextInput(attrs={'class': 'w-full border rounded-md p-2'}),
            'colour': forms.Select(attrs={'class': 'w-full border rounded-md p-2'}),
            'girls_leader': forms.TextInput(attrs={'class': 'w-full border rounded-md p-2'}),
            'girls_leader_assistant': forms.TextInput(attrs={'class': 'w-full border rounded-md p-2'}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if user and hasattr(user, "madrasa"):
            self.fields["madrasa"].initial = user.madrasa
            self.fields["madrasa"].disabled = True


# class MarksForm(forms.Form):
#     # Boys
#     super_senior_boys = forms.FloatField(label="Super Senior (Boys)", required=False, initial=0,
#                                          widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
#     senior_boys = forms.FloatField(label="Senior (Boys)", required=False, initial=0,
#                                    widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
#     junior_boys = forms.FloatField(label="Junior (Boys)", required=False, initial=0,
#                                    widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
#     subjunior_boys = forms.FloatField(label="Sub Junior (Boys)", required=False, initial=0,
#                                       widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
#     kiddies_boys = forms.FloatField(label="Kiddies (Boys)", required=False, initial=0,
#                                     widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
#     general_boys = forms.FloatField(label="General (Boys)", required=False, initial=0,
#                                     widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
#
#     # Girls
#     super_senior_girls = forms.FloatField(label="Super Senior (Girls)", required=False, initial=0,
#                                           widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
#     senior_girls = forms.FloatField(label="Senior (Girls)", required=False, initial=0,
#                                     widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
#     junior_girls = forms.FloatField(label="Junior (Girls)", required=False, initial=0,
#                                     widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
#     subjunior_girls = forms.FloatField(label="Sub Junior (Girls)", required=False, initial=0,
#                                        widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
#     kiddies_girls = forms.FloatField(label="Kiddies (Girls)", required=False, initial=0,
#                                      widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
#     general_girls = forms.FloatField(label="General (Girls)", required=False, initial=0,
#                                      widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
#
#
# class MarkEditForm(forms.ModelForm):
#     class Meta:
#         model = Mark
#         fields = [
#             "super_senior",
#             "senior",
#             "junior",
#             "subjunior",
#             "kiddies",
#             "general",
#         ]
#         widgets = {
#             field: forms.NumberInput(attrs={
#                 "class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-500",
#                 "step": "0.01",  # allow decimals
#             }) for field in fields
#         }
