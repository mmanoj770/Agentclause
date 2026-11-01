import pytest
from pydantic import ValidationError
from app.findings.schemas import FindingIn


def test_valid_finding():
    FindingIn(layer=2, severity="critical", description="Non-compete void under s.27")


@pytest.mark.parametrize("bad", [
    dict(layer=7, severity="low", description="x"),
    dict(layer=2, severity="urgent", description="x"),
    dict(layer=2, severity="low", description=""),
])
def test_invalid_finding(bad):
    with pytest.raises(ValidationError):
        FindingIn(**bad)
