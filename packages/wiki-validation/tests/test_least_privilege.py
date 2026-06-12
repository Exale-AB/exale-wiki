import pytest

from wiki_validation.least_privilege import (
    ScopeError,
    get_required_scopes_for_bundles,
    verify_seat_least_privilege,
)


def test_get_required_scopes_single_bundle():
    """Single bundle returns its scopes."""
    scopes = get_required_scopes_for_bundles(["inbox-triage"])
    assert scopes == {"mail.readonly", "drive.readonly"}


def test_get_required_scopes_multiple_bundles():
    """Multiple bundles return union of scopes."""
    scopes = get_required_scopes_for_bundles(["inbox-triage", "follow-up"])
    assert scopes == {"mail.readonly", "drive.readonly", "calendar.readonly"}


def test_get_required_scopes_unknown_bundle():
    """Unknown bundle raises ScopeError."""
    with pytest.raises(ScopeError, match="Unknown bundle"):
        get_required_scopes_for_bundles(["nonexistent-bundle"])


def test_verify_seat_least_privilege_compliant():
    """Compliant seat: only requests scopes it needs."""
    config = {
        "skill_bundles": ["inbox-triage"],
        "integrations": {
            "gmail": {"scopes": ["mail.readonly"]},
            "drive": {"scopes": ["drive.readonly"]},
        },
    }

    result = verify_seat_least_privilege(config)

    assert result["compliant"] is True
    assert result["required_scopes"] == ["drive.readonly", "mail.readonly"]
    assert result["violations"] == []


def test_verify_seat_least_privilege_over_privileged():
    """Non-compliant seat: requests scopes it doesn't need."""
    config = {
        "skill_bundles": ["inbox-triage"],
        "integrations": {
            "gmail": {"scopes": ["mail.readonly", "mail.send"]},
            "crm": {"scopes": ["crm.admin"]},
        },
    }

    result = verify_seat_least_privilege(config)

    assert result["compliant"] is False
    assert "mail.send" in [v["scope"] for v in result["violations"]]
    assert "crm.admin" in [v["scope"] for v in result["violations"]]


def test_verify_seat_least_privilege_scopes_as_string():
    """Parse scopes if they're comma-separated string."""
    config = {
        "skill_bundles": ["inbox-triage"],
        "integrations": {
            "gmail": {"scopes": "mail.readonly,drive.readonly"},
        },
    }

    result = verify_seat_least_privilege(config)

    assert result["compliant"] is True


def test_verify_seat_least_privilege_empty_bundles():
    """Empty bundles means no scopes required."""
    config = {
        "skill_bundles": [],
        "integrations": {
            "gmail": {"scopes": ["mail.readonly"]},
        },
    }

    result = verify_seat_least_privilege(config)

    assert result["compliant"] is False
    assert len(result["violations"]) == 1
    assert result["violations"][0]["scope"] == "mail.readonly"
