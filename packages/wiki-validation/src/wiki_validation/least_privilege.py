"""Verify seat skill bundles only request scopes they actually use."""



class ScopeError(Exception):
    """Scope validation failed."""
    pass


# Hardcoded scope requirements for each bundle (from Business Plan 4, Architecture §2)
BUNDLE_SCOPES = {
    "inbox-triage": {"mail.readonly", "drive.readonly"},
    "follow-up": {"mail.readonly", "calendar.readonly"},
    "meeting-to-action": {"calendar.readonly", "drive.readonly"},
    "pipeline-watchdog": {"crm.read"},
    "proposal-drafter": {"crm.read", "drive.readonly"},
    "knowledge-concierge": {"wiki.read"},  # Internal wiki access
    "knowledge-wiki": {"wiki.read"},  # Alias for knowledge-concierge (backward compat)
}


def get_required_scopes_for_bundles(
    enabled_bundles: list[str],
) -> set[str]:
    """Compute required scopes for a set of enabled bundles.

    Args:
        enabled_bundles: list of bundle names (e.g. ["inbox-triage", "follow-up"])

    Returns:
        Union of all scopes needed by the bundles

    Raises:
        ScopeError: unknown bundle name
    """
    required = set()
    for bundle in enabled_bundles:
        if bundle not in BUNDLE_SCOPES:
            raise ScopeError(f"Unknown bundle: {bundle}")
        required.update(BUNDLE_SCOPES[bundle])
    return required


def verify_seat_least_privilege(
    seat_config: dict,
) -> dict:
    """Verify seat requests only scopes its bundles need.

    Args:
        seat_config: seat config dict with 'skill_bundles' and 'integrations'

    Returns:
        {
            'compliant': bool,
            'required_scopes': [...],
            'requested_scopes': [...],
            'violations': [
                {'scope': 'admin.read', 'reason': 'not required by any enabled bundle'}
            ]
        }

    Raises:
        ScopeError: if validation logic fails
    """
    bundles = seat_config.get("skill_bundles", [])
    integrations = seat_config.get("integrations", {})

    # Get required scopes
    required = get_required_scopes_for_bundles(bundles)

    # Get requested scopes
    requested = set()
    for _integration_name, integration_config in integrations.items():
        scopes = integration_config.get("scopes", [])
        if isinstance(scopes, list):
            requested.update(scopes)
        elif isinstance(scopes, str):
            requested.update(scopes.split(","))

    # Check for violations
    violations = []
    for scope in requested:
        if scope not in required:
            violations.append({
                "scope": scope,
                "reason": "not required by any enabled bundle",
            })

    compliant = len(violations) == 0

    return {
        "compliant": compliant,
        "required_scopes": sorted(required),
        "requested_scopes": sorted(requested),
        "violations": violations,
    }
