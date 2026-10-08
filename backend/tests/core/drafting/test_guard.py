"""Guardrail chain: syntax gate → IR → lint (spec §5.3 step 4)."""

from ontoworkbench.core.drafting.guard import run_guardrails
from ontoworkbench.core.errors import CoreError

GOOD_TTL = b"""@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix shop: <https://local/shop#> .

shop:Customer a owl:Class ;
    rdfs:label "customer" .
"""


def test_good_ttl_passes_chain() -> None:
    """Valid Turtle returns lint findings (possibly empty) without raising."""
    findings = run_guardrails(GOOD_TTL)
    assert isinstance(findings, list)


def test_broken_ttl_raises_parse_failed() -> None:
    """Garbage TTL fails the syntax gate with PARSE_FAILED."""
    try:
        run_guardrails(b"this is not <<< turtle")
    except CoreError as e:
        assert e.code == "PARSE_FAILED"
    else:
        raise AssertionError("expected CoreError PARSE_FAILED")
