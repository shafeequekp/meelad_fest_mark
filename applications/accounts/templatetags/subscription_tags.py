"""Template tags for the subscription-enabled toggle.

Usage in templates::

    {% load subscription_tags %}
    {% if user.is_subscription_enabled %}
        <!-- show subscription section -->
    {% endif %}
"""

from django import template

from applications.accounts.models import User

register = register = template.Library()


@register.filter
def is_subscription_enabled(user):
    """Return True when this user's subscription section is enabled (admin toggle).

    Used as a template filter so views can check the flag without hard-coding
    model logic in the template.
    """
    if user is None or not isinstance(user, User):
        return False
    return user.is_subscription_enabled


@register.simple_tag
def subscription_enabled_default():
    """Return the hardcoded default for the subscription-enable flag (False = disabled).

    Kept in sync with the model definition so templates can show the correct
    'default disabled' hint.
    """
    return User.subscription_enabled.field.default
