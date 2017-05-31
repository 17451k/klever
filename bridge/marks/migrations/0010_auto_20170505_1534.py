# -*- coding: utf-8 -*-
# Generated by Django 1.10.4 on 2017-05-05 15:34
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marks', '0009_unsafeassociationlike'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='marksafereport',
            name='manual',
        ),
        migrations.RemoveField(
            model_name='markunknownreport',
            name='manual',
        ),
        migrations.RemoveField(
            model_name='markunsafereport',
            name='manual',
        ),
        migrations.AddField(
            model_name='marksafereport',
            name='type',
            field=models.CharField(choices=[('0', 'Automatic'), ('1', 'Confirmed'), ('2', 'Unconfirmed')], default='0', max_length=1),
        ),
        migrations.AddField(
            model_name='markunknownreport',
            name='type',
            field=models.CharField(choices=[('0', 'Automatic'), ('1', 'Confirmed'), ('2', 'Unconfirmed')], default='0', max_length=1),
        ),
        migrations.AddField(
            model_name='markunsafereport',
            name='type',
            field=models.CharField(choices=[('0', 'Automatic'), ('1', 'Confirmed'), ('2', 'Unconfirmed')], default='0', max_length=1),
        ),
    ]
