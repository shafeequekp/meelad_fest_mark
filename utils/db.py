from django.db import models

from django_extensions.db.fields import (ModificationDateTimeField,
                                         CreationDateTimeField)


class DateBaseModel(models.Model):
    """
    Base model that provides:
        * self managed created field
        * self managed modified field
    """
    created = CreationDateTimeField('Created')
    modified = ModificationDateTimeField('Modified')

    class Meta:
        get_latest_by = 'modified'
        abstract = True
