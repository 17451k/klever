# -*- coding: utf-8 -*-
# Generated by Django 1.11 on 2017-05-26 14:27
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0006_auto_20170523_1336'),
    ]

    operations = [
        migrations.AddField(
            model_name='reportsafe',
            name='has_confirmed',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='reportunsafe',
            name='has_confirmed',
            field=models.BooleanField(default=False),
        ),
    ]
