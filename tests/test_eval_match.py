from decimal import Decimal

from run_eval import results_match


def test_order_insensitive_and_rounding():
    assert results_match([("b", 2.004), ("a", 1)], [("a", 1), ("b", Decimal("2.00"))])


def test_extra_label_column_is_accepted():
    assert results_match([("Electronics", 10.0)], [(10.0,)])


def test_mismatch():
    assert not results_match([(1,)], [(2,)])
    assert not results_match([(1,), (2,)], [(1,)])
