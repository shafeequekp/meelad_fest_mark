from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator

from utils.db import DateBaseModel



class Madrasa(DateBaseModel):
    # Festival section structure. 'both' keeps the classic Boys & Girls fest,
    # 'boys' reduces every page/flow to the Boys section only and 'girls'
    # reduces it to the Girls section only.
    FEST_TYPE_BOTH = 'both'
    FEST_TYPE_BOYS = 'boys'
    FEST_TYPE_GIRLS = 'girls'
    FEST_TYPE_CHOICES = (
        (FEST_TYPE_BOTH, 'Both Sections'),
        (FEST_TYPE_BOYS, 'Boys Only'),
        (FEST_TYPE_GIRLS, 'Girls Only'),
    )

    name = models.CharField(max_length=255)
    reg_number = models.CharField(max_length=30, null=True, blank=True)
    madrasa_profile_pic = models.ImageField(upload_to='madrasa_profile_pics/', null=True, blank=True)
    sadr = models.CharField(max_length=123, null=True, blank=True)
    committee_name = models.CharField(max_length=123, null=True, blank=True)
    meelad_fest_name = models.CharField(max_length=123, null=True, blank=True)
    fest_logo = models.ImageField(upload_to='madrasa_logos/', null=True, blank=True)
    sadr_signature = models.ImageField(upload_to='madrasa_signatures/', null=True, blank=True)
    convenor_name_1 = models.CharField(max_length=123, null=True, blank=True)
    convenor_name_2 = models.CharField(max_length=123, null=True, blank=True)
    topper = models.ManyToManyField('program.Student', blank=True)

    fest_type = models.CharField(
        max_length=10,
        choices=FEST_TYPE_CHOICES,
        default=FEST_TYPE_BOTH,
        help_text="Festival structure: both sections, boys only, or girls only.",
    )

    schedule_consent_confirmed = models.BooleanField(
        default=False,
        help_text=(
            "Coordinator confirms all programs are added and program "
            "participation is complete before scheduling starts. While this "
            "is on, the generated registration link stops accepting new "
            "student → program registrations so scheduling conflicts are "
            "computed on final participant data."
        ),
    )
    schedule_consent_confirmed_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the schedule-ready consent was confirmed (tracking).",
    )

    # Fest rules & regulations document (per madrasa). The extracted text
    # feeds the AI assistant's knowledge base (RAG) so it can answer
    # "what do the rules say about ...?" questions from THIS madrasa's rules.
    fest_rules = models.FileField(
        upload_to='fest_rules/',
        null=True, blank=True,
        help_text="Fest rules & regulations PDF. Used by the AI assistant "
                  "to answer rules questions (RAG).",
    )
    fest_rules_text = models.TextField(
        null=True, blank=True,
        help_text="Plain-text extraction of the rules PDF, stored at upload "
                  "time so the AI service never parses PDFs itself.",
    )
    fest_rules_updated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name

    @property
    def is_boys_only(self):
        """True when the fest is configured as boys-only."""
        return self.fest_type == self.FEST_TYPE_BOYS

    @property
    def is_girls_only(self):
        """True when the fest is configured as girls-only."""
        return self.fest_type == self.FEST_TYPE_GIRLS

    @property
    def is_both_sections(self):
        """True when both boys & girls sections take part (default)."""
        return (self.fest_type or self.FEST_TYPE_BOTH) == self.FEST_TYPE_BOTH

    @property
    def active_fest_sections(self):
        """List of section ids ('boys' / 'girls') active for this fest."""
        if self.is_boys_only:
            return [self.FEST_TYPE_BOYS]
        if self.is_girls_only:
            return [self.FEST_TYPE_GIRLS]
        return [self.FEST_TYPE_BOYS, self.FEST_TYPE_GIRLS]

    def active_genders(self):
        """List of Student.gender values active for this fest."""
        if self.is_boys_only:
            return ['male']
        if self.is_girls_only:
            return ['female']
        return ['male', 'female']


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

    config_done = models.BooleanField(default=False)
    subscribed = models.BooleanField(default=False)

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
