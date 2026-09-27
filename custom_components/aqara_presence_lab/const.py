"""Constants for Aqara Presence Lab."""

from homeassistant.const import Platform

DOMAIN = "aqara_presence_lab"
VERSION = "0.3.0b1"
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
