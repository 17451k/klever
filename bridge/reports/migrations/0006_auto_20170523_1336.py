# -*- coding: utf-8 -*-
# Generated by Django 1.10.4 on 2017-05-23 13:36
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0005_set_verification'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='attrstatistic',
            name='attr',
        ),
        migrations.RemoveField(
            model_name='attrstatistic',
            name='name',
        ),
        migrations.RemoveField(
            model_name='attrstatistic',
            name='report',
        ),
        migrations.DeleteModel(
            name='AttrStatistic',
        ),
    ]
