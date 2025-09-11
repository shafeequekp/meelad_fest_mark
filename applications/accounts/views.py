from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages

from .forms import LoginForm, SignupForm


# def login_view(request):
#     if request.user.is_authenticated:
#         return redirect("home")  # already logged in
#
#     if request.method == "POST":
#         form = LoginForm(request, data=request.POST)
#         if form.is_valid():
#             user = form.get_user()
#             login(request, user)
#             return redirect("home")
#         else:
#             messages.error(request, "Invalid login credentials")
#     else:
#         form = LoginForm()
#
#     signup_form = SignupForm()  # for combined template
#     return render(request, "auth/login_signup.html", {"login_form": form, "signup_form": signup_form})

def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")  # already logged in

    if request.method == "POST":
        form = LoginForm(request.POST)  # ✅ only POST data

        if form.is_valid():
            email = form.cleaned_data["email"]
            password = form.cleaned_data["password"]
            user = authenticate(request, username=email, password=password)
            print(user)
            if user is not None:
                login(request, user)
                return redirect("home")
            else:
                messages.error(request, "Invalid login credentials")
        else:
            return render(request, "auth/login_signup.html", form.errors)
    else:
        form = LoginForm()

    signup_form = SignupForm()
    return render(
        request,
        "auth/login_signup.html",
        {"login_form": form, "signup_form": signup_form},
    )



# def signup_view(request):
#     if request.user.is_authenticated:
#         return redirect("home")
#
#     if request.method == "POST":
#         form = SignupForm(request.POST)
#         if form.is_valid():
#             user = form.save()
#             login(request, user)  # auto login after signup
#             return redirect("home")
#         else:
#             messages.error(request, "Signup failed, please fix errors")
#     else:
#         form = SignupForm()
#
#     login_form = LoginForm(request)  # for combined template
#     return render(request, "auth/login_signup.html", {"signup_form": form, "login_form": login_form})


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        form = SignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)  # auto login after signup
            return redirect("home")
        else:
            messages.error(request, "Signup failed, please fix errors")
    else:
        form = SignupForm()

    login_form = LoginForm(request.POST or None)
    return render(request, "auth/login_signup.html", {
        "signup_form": form,
        "login_form": login_form
    })



def logout_view(request):
    logout(request)
    return redirect("login")
