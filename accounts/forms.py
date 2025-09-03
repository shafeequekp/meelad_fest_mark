from django import forms
from django.contrib.auth import get_user_model

from accounts.models import Madrasa
User = get_user_model()


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


# class SignupForm(forms.ModelForm):
#     password1 = forms.CharField(
#         label="Password",
#         widget=forms.PasswordInput(attrs={
#             "placeholder": "Password",
#             "class": "w-full p-2 border rounded-md"
#         })
#     )
#     password2 = forms.CharField(
#         label="Confirm Password",
#         widget=forms.PasswordInput(attrs={
#             "placeholder": "Confirm Password",
#             "class": "w-full p-2 border rounded-md"
#         })
#     )
#
#     class Meta:
#         model = User
#         fields = ["email", "phone_number"]  # ✅ no "username"
#
#         widgets = {
#             "email": forms.EmailInput(attrs={
#                 "placeholder": "Email",
#                 "class": "w-full p-2 border rounded-md"
#             }),
#             "phone_number": forms.TextInput(attrs={
#                 "placeholder": "Phone Number",
#                 "class": "w-full p-2 border rounded-md"
#             }),
#         }
#
#     def clean(self):
#         cleaned_data = super().clean()
#         p1 = cleaned_data.get("password1")
#         p2 = cleaned_data.get("password2")
#         if p1 and p2 and p1 != p2:
#             self.add_error("password2", "Passwords do not match.")
#         return cleaned_data
#
#     def save(self, commit=True):
#         user = super().save(commit=False)
#         user.set_password(self.cleaned_data["password1"])
#         if commit:
#             user.save()
#         return user


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
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Madrasa Name",
            "class": "w-full p-2 border rounded-md"
        })
    )
    # madrasa_reg_number = forms.CharField(
    #     required=False,
    #     widget=forms.TextInput(attrs={
    #         "placeholder": "Registration Number",
    #         "class": "w-full p-2 border rounded-md"
    #     })
    # )
    meelad_fest_name = forms.CharField(
        required=False,
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
    meelad_fest_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            "placeholder": "Meelad Fest Name",
            "class": "w-full p-2 border rounded-md"
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

            # Create Madrasa and link to User
            madrasa = Madrasa.objects.create(
                name=self.cleaned_data["madrasa_name"],
                reg_number=self.cleaned_data.get("madrasa_reg_number"),
                sadr=self.cleaned_data.get("madrasa_sadr"),
                meelad_fest_name=self.cleaned_data.get("meelad_fest_name"),
            )
            user.madrasa = madrasa
            user.save()

        return user

