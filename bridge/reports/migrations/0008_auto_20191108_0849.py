# Generated by Django 2.1.7 on 2019-11-08 08:49

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0007_auto_20190923_1304'),
    ]

    operations = [
        migrations.AlterField(
            model_name='report',
            name='level',
            field=models.PositiveIntegerField(editable=False),
        ),
        migrations.AlterField(
            model_name='report',
            name='lft',
            field=models.PositiveIntegerField(editable=False),
        ),
        migrations.AlterField(
            model_name='report',
            name='rght',
            field=models.PositiveIntegerField(editable=False),
        ),
    ]
