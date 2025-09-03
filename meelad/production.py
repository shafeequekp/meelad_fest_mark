import os

DEBUG = False


# CSRF_TRUSTED_ORIGINS = [
#     'https://3106-103-181-40-57.ngrok-free.app',
# ]

#
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql_psycopg2',
#         'NAME': 'inthikabdb',
#         'USER': 'prodigy1_user',
#         'PASSWORD': 'mind@123',
#          'HOST': 'localhost',
#         'PORT': '5432',
#     }
# }


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'meelad_db',          # your MySQL database name
        'USER': 'root',      # your MySQL username
        'PASSWORD': 'mind@123',       # your MySQL password
        'HOST': 'localhost',
        'PORT': '3306',               # default MySQL port
    }
}
