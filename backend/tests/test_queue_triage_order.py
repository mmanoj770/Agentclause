"""The lawyer queue's triage sort must put senior_counsel first, then enhanced, then standard.

The tier values are the ones documents.triage_tier allows (migration 04). A stale 'critical'
value is not one of them, so it must not appear in the sort.
"""
from app.lawyer_queue.service import ORDER_TRIAGE_TIER


def test_triage_sort_order():
    sql = ORDER_TRIAGE_TIER
    assert sql.index("'senior_counsel' then 1") < sql.index("'enhanced' then 2") < sql.index("'standard' then 3")


def test_triage_sort_has_no_stale_tier():
    assert "'critical'" not in ORDER_TRIAGE_TIER
