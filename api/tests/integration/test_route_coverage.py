"""Structural guards over the whole API surface.

These are the tests that cannot go stale. The behavioural tables in
`test_setup_authz.py` and `test_teacher_authz.py` only cover the endpoints
somebody remembered to list; these two make forgetting fail:

- every `/api/v1` route outside `/auth` declares a capability gate
- every such route appears in one of those tables

An endpoint added in a later milestone without a gate, or with a gate but no
behavioural row, fails here the day it lands. Both were verified against a
deliberately ungated route planted for the purpose, then removed.
"""

import pytest
from fastapi.routing import APIRoute

from tests.integration.routes import capability_gated, guarded_routes, normalise
from tests.integration.test_setup_authz import SETUP_ENDPOINTS
from tests.integration.test_teacher_authz import (
    STAFF_ENDPOINTS,
    TEACHER_ONLY_ENDPOINTS,
)

TABLED = SETUP_ENDPOINTS + TEACHER_ONLY_ENDPOINTS + STAFF_ENDPOINTS


def test_there_are_routes_to_check() -> None:
    """Guards against the scan passing because it found nothing.

    Counts distinct paths, not table rows: a table may list one endpoint twice
    to exercise two query strings, which it should be free to do.
    """
    tabled_paths = {normalise(path) for _, path, _ in TABLED}
    scanned_paths = {normalise(path) for path, _ in guarded_routes()}

    assert scanned_paths >= tabled_paths
    # A floor, not a count: it only has to fail if the scan ever finds
    # nothing, so it is well below the real number and needs no maintenance.
    assert len(scanned_paths) >= 25


@pytest.mark.parametrize(
    "case", guarded_routes(), ids=lambda case: f"{sorted(case[1].methods)[0]} {case[0]}"
)
def test_every_route_declares_a_capability(case: tuple[str, APIRoute]) -> None:
    path, route = case

    assert capability_gated(route), (
        f"{path} is mounted without a capability gate. Declare one of "
        "authz.dependencies' annotations in the signature (§5.2)."
    )


def test_the_tables_cover_every_mounted_route() -> None:
    """If an endpoint is added without a row, the 403 tables would quietly
    stop covering it."""
    mounted = {
        (method, normalise(path))
        for path, route in guarded_routes()
        for method in route.methods
        if method != "HEAD"
    }
    tabled = {(method, normalise(path)) for method, path, _ in TABLED}

    assert mounted - tabled == set()
