from app.documents.states import DocState, TRANSITIONS


def test_nothing_leaves_delivered():
    assert all(frm != DocState.DELIVERED for frm, _ in TRANSITIONS)


def test_approval_is_one_way():
    for frm, to in TRANSITIONS:
        if frm == DocState.LAWYER_APPROVED:
            assert to == DocState.DELIVERED


def test_only_lawyers_approve():
    for (frm, to), who in TRANSITIONS.items():
        if to == DocState.LAWYER_APPROVED:
            assert who == {"lawyer"}


def test_only_system_delivers():
    for (frm, to), who in TRANSITIONS.items():
        if to == DocState.DELIVERED:
            assert who == {"system"}


def test_a_failed_ai_review_goes_back_only_to_a_reviewable_state_and_only_by_the_system():
    # R10: the pipeline returns a document it couldn't review to the state the review started from.
    out_of_review = {to: who for (frm, to), who in TRANSITIONS.items() if frm == DocState.UNDER_AI_REVIEW}
    assert set(out_of_review) == {DocState.PENDING_LAWYER_REVIEW, DocState.DRAFTED, DocState.REVISION_IN_PROGRESS}
    assert all(who == frozenset({"system"}) for who in out_of_review.values())
