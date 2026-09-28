"""Constants for Aqara Presence Lab."""

from homeassistant.const import Platform

DOMAIN = "aqara_presence_lab"
VERSION = "0.4.0b1"
PLATFORMS = (Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON)
CONF_TOKEN = "token"
CONF_USER_ID = "user_id"
CONF_DEVICE_IDS = "device_ids"
CONF_INTERVAL = "poll_interval"
CONF_REGION = "region"
CONF_ACCOUNT_SECRET = "account_secret"
CONF_PASSWORD_SECRET = "password_secret"
CONF_SESSION_STORE_ID = "session_store_id"
CONF_CONSENT = "allow_experimental_cloud"
DEFAULT_INTERVAL = 300
MIN_INTERVAL = 60
MAX_INTERVAL = 3600
REFRESH_COOLDOWN = 30
TRANSPORT_TIMEOUT = 20
CONNECTION_STATES = [
    "ready",
    "retry_wait",
    "reauth_required",
    "protocol_unsupported",
    "unconfigured",
]
QUALITY_STATES = [
    "unverified",
    "reported",
    "current_validated",
    "missing",
    "invalid",
    "transport_unavailable",
    "stale_confirmed",
    "clock_anomaly",
]

# Independent scheduling: live status groups and slowly changing settings.
CONF_RESOURCE_INTERVAL = "resource_interval"
CONF_SETTINGS_INTERVAL = "settings_interval"
CONF_REQUEST_SPACING = "request_spacing"
DEFAULT_RESOURCE_INTERVAL = 60
DEFAULT_SETTINGS_INTERVAL = 3600
DEFAULT_REQUEST_SPACING = 30
MIN_RESOURCE_INTERVAL = 10
MAX_RESOURCE_INTERVAL = 3600
MIN_SETTINGS_INTERVAL = 900
MAX_SETTINGS_INTERVAL = 86400
REQUEST_SPACINGS = (30, 15, 10, 5)
