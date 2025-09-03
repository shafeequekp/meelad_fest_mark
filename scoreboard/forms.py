# from django import forms
# from .models import Team
#
#
# class TeamForm(forms.ModelForm):
#     class Meta:
#         model = Team
#         fields = ['name', 'madrasa', 'leader', 'assistant']
#
#
# class MarksForm(forms.Form):
#     # categories for both boys & girls
#     super_senior_boys = forms.FloatField(label="Super Senior (Boys)", required=False, initial=0)
#     senior_boys = forms.FloatField(label="Senior (Boys)", required=False, initial=0)
#     junior_boys = forms.FloatField(label="Junior (Boys)", required=False, initial=0)
#     subjunior_boys = forms.FloatField(label="Sub Junior (Boys)", required=False, initial=0)
#     kiddies_boys = forms.FloatField(label="Kiddies (Boys)", required=False, initial=0)
#     general_boys = forms.FloatField(label="General (Boys)", required=False, initial=0)
#
#     super_senior_girls = forms.FloatField(label="Super Senior (Girls)", required=False, initial=0)
#     senior_girls = forms.FloatField(label="Senior (Girls)", required=False, initial=0)
#     junior_girls = forms.FloatField(label="Junior (Girls)", required=False, initial=0)
#     subjunior_girls = forms.FloatField(label="Sub Junior (Girls)", required=False, initial=0)
#     kiddies_girls = forms.FloatField(label="Kiddies (Girls)", required=False, initial=0)
#     general_girls = forms.FloatField(label="General (Girls)", required=False, initial=0)



from django import forms
from .models import Team


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['name', 'madrasa', 'leader', 'assistant']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'w-full border rounded-md p-2'}),
            'madrasa': forms.Select(attrs={'class': 'w-full border rounded-md p-2'}),
            'leader': forms.TextInput(attrs={'class': 'w-full border rounded-md p-2'}),
            'assistant': forms.TextInput(attrs={'class': 'w-full border rounded-md p-2'}),
        }


class MarksForm(forms.Form):
    # Boys
    super_senior_boys = forms.FloatField(label="Super Senior (Boys)", required=False, initial=0,
                                         widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
    senior_boys = forms.FloatField(label="Senior (Boys)", required=False, initial=0,
                                   widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
    junior_boys = forms.FloatField(label="Junior (Boys)", required=False, initial=0,
                                   widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
    subjunior_boys = forms.FloatField(label="Sub Junior (Boys)", required=False, initial=0,
                                      widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
    kiddies_boys = forms.FloatField(label="Kiddies (Boys)", required=False, initial=0,
                                    widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
    general_boys = forms.FloatField(label="General (Boys)", required=False, initial=0,
                                    widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))

    # Girls
    super_senior_girls = forms.FloatField(label="Super Senior (Girls)", required=False, initial=0,
                                          widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
    senior_girls = forms.FloatField(label="Senior (Girls)", required=False, initial=0,
                                    widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
    junior_girls = forms.FloatField(label="Junior (Girls)", required=False, initial=0,
                                    widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
    subjunior_girls = forms.FloatField(label="Sub Junior (Girls)", required=False, initial=0,
                                       widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
    kiddies_girls = forms.FloatField(label="Kiddies (Girls)", required=False, initial=0,
                                     widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))
    general_girls = forms.FloatField(label="General (Girls)", required=False, initial=0,
                                     widget=forms.NumberInput(attrs={'class': 'w-full border rounded-md p-2'}))



# # forms.py
# from django import forms
# from django.forms import inlineformset_factory
# from .models import Team, Mark
#
# class TeamForm(forms.ModelForm):
#     class Meta:
#         model = Team
#         fields = ['name', 'madrasa', 'leader', 'assistant']
#
# class MarkForm(forms.ModelForm):
#     class Meta:
#         model = Mark
#         fields = ['section', 'super_senior', 'senior', 'junior', 'subjunior', 'kiddies', 'general']
#
# # Each team can have 2 marks rows (boys, girls)
# MarkFormSet = inlineformset_factory(
#     Team, Mark, form=MarkForm,
#     extra=2, can_delete=True
# )
