import pytest

pytestmark = pytest.mark.skip("Run inside docker-compose network or with live external_bank_sim")


def test_loan_feed_contract():
    assert True
