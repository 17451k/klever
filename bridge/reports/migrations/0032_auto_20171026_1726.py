# -*- coding: utf-8 -*-
# Generated by Django 1.11.3 on 2017-10-26 14:26
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [('reports', '0031_set_leaf_resources')]

    operations = [
        migrations.RemoveField(model_name='tasksnumbers', name='root'),
        migrations.DeleteModel(name='TaskStatistic'),
        migrations.RemoveField(model_name='reportroot', name='average_time'),
        migrations.RemoveField(model_name='reportroot', name='tasks_total'),
        migrations.DeleteModel(name='TasksNumbers')
    ]
