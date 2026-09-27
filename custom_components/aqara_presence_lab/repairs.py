"""Actionable, credential-free repair notifications."""

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

ISSUES = (
    "protocol_unsupported",
    "auth_required",
    "cannot_connect",
    "secret_store_failed",
    "freshness_unverified",
)


@callback
def async_set_issue(hass: HomeAssistant, entry_id: str, key: str) -> None:
    """Create an explanatory issue without remote data in its text."""
    if key not in ISSUES:
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{entry_id}_{key}",
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=key,
    )


@callback
def async_clear_connection_issues(hass: HomeAssistant, entry_id: str) -> None:
    """A successful read resolves connection issues, not unknown semantics."""
    for key in ISSUES[:-1]:
        ir.async_delete_issue(hass, DOMAIN, f"{entry_id}_{key}")


@callback
def async_remove_issues(hass: HomeAssistant, entry_id: str) -> None:
    """Remove integration-owned issues when its configuration is removed."""
    for key in ISSUES:
        ir.async_delete_issue(hass, DOMAIN, f"{entry_id}_{key}")
