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
