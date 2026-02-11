from django.db import migrations
from django.contrib.postgres.operations import TrigramExtension

class Migration(migrations.Migration):
    dependencies = [
        ('quiz', '0001_initial'), # Ensure this points to your previous migration!
    ]

    operations = [
        TrigramExtension(),
    ]