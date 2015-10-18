# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('push_notifications', '0002_gcm_registration_id_unique'),
    ]

    operations = [
        migrations.AlterField(
            model_name='gcmdevice',
            name='registration_id',
            field=models.TextField(verbose_name='Registration ID'),
        ),
        migrations.AlterUniqueTogether(
            name='gcmdevice',
            unique_together=set([('user', 'registration_id')]),
        ),
    ]
