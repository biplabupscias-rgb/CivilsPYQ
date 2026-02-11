from django.db import migrations
from django.contrib.postgres.operations import TrigramExtension

class Migration(migrations.Migration):
    dependencies = [
        # CHANGE THIS LINE: Point to 0002 instead of 0001
        ('quiz', '0002_examcutoff'), 
    ]

    operations = [
        TrigramExtension(),
    ]