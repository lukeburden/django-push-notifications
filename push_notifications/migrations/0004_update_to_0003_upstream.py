# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('push_notifications', '0003_auto_20151018_2112'),
    ]

    operations = [
        migrations.CreateModel(
            name='WNSDevice',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(max_length=255, null=True, verbose_name='Name', blank=True)),
                ('active', models.BooleanField(default=True, help_text='Inactive devices will not be sent notifications', verbose_name='Is active')),
                ('date_created', models.DateTimeField(auto_now_add=True, verbose_name='Creation date', null=True)),
                ('device_id', models.UUIDField(blank=True, help_text='GUID()', null=True, verbose_name='Device ID', db_index=True)),
                ('registration_id', models.TextField(verbose_name='Notification URI')),
                ('user', models.ForeignKey(blank=True, to=settings.AUTH_USER_MODEL, null=True)),
            ],
            options={
                'verbose_name': 'WNS device',
            },
        ),
        migrations.AlterField(
            model_name='apnsdevice',
            name='registration_id',
            field=models.CharField(max_length=200, verbose_name='Registration ID'),
        ),
    ]
