from __future__ import unicode_literals

import json
import requests

from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import ugettext_lazy as _

from pyfcm import FCMNotification

from .fields import HexIntegerField
from .settings import PUSH_NOTIFICATIONS_SETTINGS as SETTINGS


conversion_url = "https://iid.googleapis.com/iid/v1:batchImport"


@python_2_unicode_compatible
class Device(models.Model):
	name = models.CharField(max_length=255, verbose_name=_("Name"), blank=True, null=True)
	active = models.BooleanField(
		verbose_name=_("Is active"), default=True,
		help_text=_("Inactive devices will not be sent notifications")
	)
	user = models.ForeignKey(SETTINGS["USER_MODEL"], blank=True, null=True)
	date_created = models.DateTimeField(
		verbose_name=_("Creation date"), auto_now_add=True, null=True
	)

	class Meta:
		abstract = True

	def __str__(self):
		return (
			self.name or str(self.device_id or "") or
			"%s for %s" % (self.__class__.__name__, self.user or "unknown user")
		)


class GCMDeviceManager(models.Manager):
	def get_queryset(self):
		return GCMDeviceQuerySet(self.model)


class GCMDeviceQuerySet(models.query.QuerySet):
	def send_message(self, message, **kwargs):
		if self:
			from .gcm import gcm_send_bulk_message

			data = kwargs.pop("extra", {})
			if message is not None:
				data["message"] = message

			reg_ids = list(self.filter(active=True).values_list('registration_id', flat=True))
			return gcm_send_bulk_message(registration_ids=reg_ids, data=data, **kwargs)


class GCMDevice(Device):
	# device_id cannot be a reliable primary key as fragmentation between different devices
	# can make it turn out to be null and such:
	# http://android-developers.blogspot.co.uk/2011/03/identifying-app-installations.html
	device_id = HexIntegerField(
		verbose_name=_("Device ID"), blank=True, null=True, db_index=True,
		help_text=_("ANDROID_ID / TelephonyManager.getDeviceId() (always as hex)")
	)
	registration_id = models.TextField(verbose_name=_("Registration ID"), blank=False)

	objects = GCMDeviceManager()

	class Meta:
		verbose_name = _("GCM device")
		unique_together = (('user', 'registration_id'),)

	def send_message(self, message, **kwargs):
		from .gcm import gcm_send_message
		data = kwargs.pop("extra", {})
		if message is not None:
			data["message"] = message
		return gcm_send_message(registration_id=self.registration_id, data=data, **kwargs)


class APNSDeviceManager(models.Manager):
	def get_queryset(self):
		return APNSDeviceQuerySet(self.model)


class APNSDeviceQuerySet(models.query.QuerySet):
	def send_message(self, message, **kwargs):
		if self:
			from .apns import apns_send_bulk_message
			reg_ids = list(self.filter(active=True).values_list('registration_id', flat=True))
			return apns_send_bulk_message(registration_ids=reg_ids, alert=message, **kwargs)


def resolve_fcm_token(device):
	"""
	Use a Google API to convert an APNS token to one we can use with Firebase.
	"""

	if device.fcm_token:
		# already set, nothing to do
		return

	headers = {
		'Authorization': 'key={}'.format(SETTINGS["GCM_API_KEY"]),
		'Content-type': 'application/json'
	}

	body = {
		# hardcode this for now
		"application": "com.hitchplanet.app",
		"sandbox": True if 'sandbox' in (SETTINGS["APNS_HOST"] or '') else False,
		"apns_tokens": [
			device.registration_id
		]
	}

	response = requests.post(
		conversion_url, headers=headers, data=json.dumps(body)
	)

	fcm_token = None
	for r in response.json()["results"]:
		if r["apns_token"] == device.registration_id and r["status"] == "OK":
			fcm_token = r["registration_token"]
			break

	if fcm_token:
		device.fcm_token = fcm_token
		device.save(update_fields=('fcm_token',))


configuration_errors = set(
	['MismatchSenderId']
)

unrecoverable_errors = set(
	['MissingRegistration', 'InvalidRegistration', 'NotRegistered']
)


def deactivate_device_on_fcm_error(device, result):
	"""
	Deactive a device if it fails to be sent a message due to an unrecoverable issue.

	An example error:

		{
			'multicast_ids': [4926029746364504051],
			'success': 0,
			'failure': 1,
			'canonical_ids': 0,
			'results': [
				{'error': 'InvalidRegistration'}
			],
			'topic_message_id': None
		}
	"""
	if result['failure'] > 0:
		if result['results'][0]['error'] in unrecoverable_errors:
			device.active = False
			device.save(update_fields=('active',))
		elif result['results'][0]['error'] in configuration_errors:
			raise ImproperlyConfigured(
				'FCM config issue when sending to device {}: {}'.format(
					device.id,
					result['results'][0]['error']
				)
			)


class APNSDevice(Device):
	device_id = models.UUIDField(
		verbose_name=_("Device ID"), blank=True, null=True, db_index=True,
		help_text="UDID / UIDevice.identifierForVendor()"
	)
	registration_id = models.CharField(
		verbose_name=_("Registration ID"), max_length=200, blank=False
	)
	# we create an FCM token for this device and send via FCM rather than
	# terrible APNS
	fcm_token = models.TextField(null=True)

	objects = APNSDeviceManager()

	class Meta:
		verbose_name = _("APNS device")
		unique_together = (('user', 'registration_id'),)

	def send_message(self, message, sound=None, category=None, extra=None, **kwargs):

		use_fcm = SETTINGS.get("APNS_USE_FCM", False)
		if use_fcm and not self.fcm_token:
			resolve_fcm_token(self)

		if use_fcm and self.fcm_token:
			# great, let's use it!
			push_service = FCMNotification(api_key=SETTINGS["GCM_API_KEY"])
			result = push_service.notify_single_device(
				registration_id=self.fcm_token,
				# if we include message_title, the payload includes `alert` as a hash
				# rather than a string. By excluding it, only a string is delivered.
				# message_title=message,
				message_body=message,
				data_message=extra
			)
			deactivate_device_on_fcm_error(self, result)
		else:
			from .apns import apns_send_message
			return apns_send_message(registration_id=self.registration_id, alert=message, **kwargs)


class WNSDeviceManager(models.Manager):
	def get_queryset(self):
		return WNSDeviceQuerySet(self.model)


class WNSDeviceQuerySet(models.query.QuerySet):
	def send_message(self, message, **kwargs):
		if self:
			from .wns import wns_send_bulk_message

			reg_ids = list(self.filter(active=True).values_list('registration_id', flat=True))
			return wns_send_bulk_message(uri_list=reg_ids, message=message, **kwargs)


class WNSDevice(Device):
	device_id = models.UUIDField(
		verbose_name=_("Device ID"), blank=True, null=True, db_index=True,
		help_text=_("GUID()")
	)
	registration_id = models.TextField(verbose_name=_("Notification URI"))

	objects = WNSDeviceManager()

	class Meta:
		verbose_name = _("WNS device")

	def send_message(self, message, **kwargs):
		from .wns import wns_send_message

		return wns_send_message(uri=self.registration_id, message=message, **kwargs)


# This is an APNS-only function right now, but maybe GCM will implement it
# in the future.  But the definition of 'expired' may not be the same. Whatevs
def get_expired_tokens(cerfile=None):
	from .apns import apns_fetch_inactive_ids
	return apns_fetch_inactive_ids(cerfile)
