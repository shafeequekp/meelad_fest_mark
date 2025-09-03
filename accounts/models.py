from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator

from utils.db import DateBaseModel


# class UserRole(DateBaseModel):
#     role = models.CharField(max_length=123)
#
#     def __str__(self):
#         return self.role
#
#     class Meta:
#         verbose_name = _('User Role')
#         verbose_name_plural = _('User Roles')


class Madrasa(DateBaseModel):
    name = models.CharField(max_length=255)
    reg_number = models.CharField(max_length=30, null=True, blank=True)
    sadr = models.CharField(max_length=123, null=True, blank=True)
    meelad_fest_name = models.CharField(max_length=123, null=True, blank=True)

    def __str__(self):
        return self.name


class CustomUserManager(BaseUserManager):
    def create_user(self, password=None, **extra_fields):
        email = extra_fields.get('email')
        phone_number = extra_fields.get('phone_number')

        if not email and not phone_number:
            raise ValueError('At least one of Email or Phone number must be set.')

        user = self.model(**extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if not extra_fields.get('phone_number') and not extra_fields.get('email'):
            raise ValueError('Superuser must have at least Email or Phone number.')

        return self.create_user(password, **extra_fields)


class CaseInsensitiveEmailValidator(EmailValidator):
    def __call__(self, value):
        super().__call__(value.lower())


class User(AbstractUser):
    username = None  # Remove username field
    email = models.EmailField(_('email address'), unique=True, null=True, blank=True, validators=[CaseInsensitiveEmailValidator()])
    country_code = models.CharField(max_length=5, null=True, blank=True, default='+91')
    phone_number = models.CharField(max_length=15, unique=True, null=True, blank=True)
    permanent_address = models.CharField(max_length=255, null=True, blank=True)
    madrasa = models.OneToOneField(Madrasa, on_delete=models.CASCADE, null=True, blank=True)

    # user_role = models.ForeignKey(UserRole, on_delete=models.SET_NULL, null=True, blank=True)

    USERNAME_FIELD = 'email'  # Default login is via email
    REQUIRED_FIELDS = []  # Nothing extra

    objects = CustomUserManager()

    def clean(self):
        # Extra validation on save
        if not self.email and not self.phone_number:
            raise ValidationError('At least one of Email or Phone number must be provided.')

    def __str__(self):
        return self.phone_number or self.email or "Unknown User"

    class Meta:
        verbose_name = _('User')
        verbose_name_plural = _('Users')
