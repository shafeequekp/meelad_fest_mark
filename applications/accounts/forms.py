from django import forms
from django.contrib.auth import get_user_model

from applications.accounts.models import Madrasa
User = get_user_model()


class MadrasaForm(forms.ModelForm):
    """Allows editing every editable field of the Madrasa model."""

    class Meta:
        model = Madrasa
        fields = [
            "name",
            "reg_number",
            "sadr",
            "committee_name",
            "meelad_fest_name",
            "convenor_name_1",
            "convenor_name_2",
            "fest_logo",
            "sadr_signature",
            "madrasa_profile_pic",
            "fest_type",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "w-full p-2 border rounded-lg", "placeholder": "Madrasa Name"}),
            "reg_number": forms.TextInput(attrs={"class": "w-full p-2 border rounded-lg", "placeholder": "Registration Number"}),
            "sadr": forms.TextInput(attrs={"class": "w-full p-2 border rounded-lg", "placeholder": "Sadr Name"}),
            "committee_name": forms.TextInput(attrs={"class": "w-full p-2 border rounded-lg", "placeholder": "Committee Name"}),
            "meelad_fest_name": forms.TextInput(attrs={"class": "w-full p-2 border rounded-lg", "placeholder": "Meelad Fest Name"}),
            "convenor_name_1": forms.TextInput(attrs={"class": "w-full p-2 border rounded-lg", "placeholder": "Convenor 1"}),
            "convenor_name_2": forms.TextInput(attrs={"class": "w-full p-2 border rounded-lg", "placeholder": "Convenor 2"}),
            "fest_logo": forms.FileInput(attrs={"class": "w-full text-sm p-2 border rounded-lg", "accept": "image/*"}),
            "sadr_signature": forms.FileInput(attrs={"class": "w-full text-sm p-2 border rounded-lg", "accept": "image/*"}),
            "madrasa_profile_pic": forms.FileInput(attrs={"class": "w-full text-sm p-2 border rounded-lg", "accept": "image/*"}),
            "fest_type": forms.Select(attrs={"class": "w-full p-2 border rounded-lg focus:ring-2 focus:ring-indigo-300"}),
        }


class LoginForm(forms.Form):  # better than AuthenticationForm since USERNAME_FIELD=email
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "placeholder": "Email",
            "class": "w-full p-2 border rounded-md"
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "placeholder": "Password",
            "class": "w-full p-2 border rounded-md"
        })
    )


class SignupForm(forms.ModelForm):
    # User fields
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            "placeholder": "Password",
            "class": "w-full p-2 border rounded-md"
        })
    )
    password2 = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={
            "placeholder": "Confirm Password",
            "class": "w-full p-2 border rounded-md"
        })
    )

    # Madrasa fields
    madrasa_name = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "Madrasa Name",
            "class": "w-full p-2 border rounded-md"
        })
    )
    madrasa_reg_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Registration Number",
            "class": "w-full p-2 border rounded-md"
        })
    )
    meelad_fest_name = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "placeholder": "Meelad Fest Name",
            "class": "w-full p-2 border rounded-md"
        })
    )
    madrasa_sadr = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Sadr Name",
            "class": "w-full p-2 border rounded-md"
        })
    )
    convenor_name_1 = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Convenor Name 1",
            "class": "w-full p-2 border rounded-md"
        })
    )
    convenor_name_2 = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Convenor Name 2",
            "class": "w-full p-2 border rounded-md"
        })
    )
    sadr_signature = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={
            "class": "w-full p-2 border rounded-md",
            "accept": "image/png,image/jpeg,image/jpg"
        })
    )

    # Festival section structure chosen during signup (defaults to both).
    fest_type = forms.ChoiceField(
        required=True,
        choices=Madrasa.FEST_TYPE_CHOICES,
        initial=Madrasa.FEST_TYPE_BOTH,
        # Same visual language as the hand-written auth inputs; appearance-none
        # hides the native arrow so the template's custom chevron shows.
        widget=forms.Select(attrs={
            "class": "w-full appearance-none rounded-xl border border-gray-300 bg-white px-4 py-2.5 pr-10 text-gray-900 outline-none ring-indigo-200 focus:ring"
        })
    )

    class Meta:
        model = User
        fields = ["email", "phone_number"]  # ✅ no username

        widgets = {
            "email": forms.EmailInput(attrs={
                "placeholder": "Email",
                "class": "w-full p-2 border rounded-md"
            }),
            "phone_number": forms.TextInput(attrs={
                "placeholder": "Phone Number",
                "class": "w-full p-2 border rounded-md"
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get("password1")
        p2 = cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        return cleaned_data

    def save(self, commit=True):
        # Save User first
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()

            # Create Madrasa and link to User. The fest structure (both / boys
            # only / girls only) chosen at signup is stored on the madrasa.
            madrasa = Madrasa.objects.create(
                name=self.cleaned_data["madrasa_name"],
                reg_number=self.cleaned_data.get("madrasa_reg_number"),
                sadr=self.cleaned_data.get("madrasa_sadr"),
                meelad_fest_name=self.cleaned_data.get("meelad_fest_name"),
                convenor_name_1=self.cleaned_data.get("convenor_name_1"),
                convenor_name_2=self.cleaned_data.get("convenor_name_2"),
                sadr_signature=self.cleaned_data.get("sadr_signature"),
                fest_type=self.cleaned_data.get("fest_type") or Madrasa.FEST_TYPE_BOTH,
            )
            user.madrasa = madrasa
            user.save()

        return user

