from __future__ import annotations

from app.core.config import _non_empty_env, _positive_float_env, _positive_int_env


def test_non_empty_env_falls_back_for_missing_or_empty_values(monkeypatch) -> None:
    monkeypatch.delenv("FAMAS_TEST_OPTIONAL_VALUE", raising=False)
    assert _non_empty_env("FAMAS_TEST_OPTIONAL_VALUE", "default-value") == "default-value"

    monkeypatch.setenv("FAMAS_TEST_OPTIONAL_VALUE", "")
    assert _non_empty_env("FAMAS_TEST_OPTIONAL_VALUE", "default-value") == "default-value"

    monkeypatch.setenv("FAMAS_TEST_OPTIONAL_VALUE", "configured-value")
    assert _non_empty_env("FAMAS_TEST_OPTIONAL_VALUE", "default-value") == "configured-value"


def test_positive_int_env_falls_back_for_empty_or_invalid_values(monkeypatch) -> None:
    monkeypatch.setenv("FAMAS_TEST_INT_VALUE", "")
    assert _positive_int_env("FAMAS_TEST_INT_VALUE", 10) == 10

    monkeypatch.setenv("FAMAS_TEST_INT_VALUE", "not-a-number")
    assert _positive_int_env("FAMAS_TEST_INT_VALUE", 10) == 10

    monkeypatch.setenv("FAMAS_TEST_INT_VALUE", "-5")
    assert _positive_int_env("FAMAS_TEST_INT_VALUE", 10) == 1

    monkeypatch.setenv("FAMAS_TEST_INT_VALUE", "20")
    assert _positive_int_env("FAMAS_TEST_INT_VALUE", 10) == 20


def test_positive_float_env_falls_back_for_empty_or_invalid_values(monkeypatch) -> None:
    monkeypatch.setenv("FAMAS_TEST_FLOAT_VALUE", "")
    assert _positive_float_env("FAMAS_TEST_FLOAT_VALUE", 2.5) == 2.5

    monkeypatch.setenv("FAMAS_TEST_FLOAT_VALUE", "not-a-number")
    assert _positive_float_env("FAMAS_TEST_FLOAT_VALUE", 2.5) == 2.5

    monkeypatch.setenv("FAMAS_TEST_FLOAT_VALUE", "-5")
    assert _positive_float_env("FAMAS_TEST_FLOAT_VALUE", 2.5) == 0.1

    monkeypatch.setenv("FAMAS_TEST_FLOAT_VALUE", "3.5")
    assert _positive_float_env("FAMAS_TEST_FLOAT_VALUE", 2.5) == 3.5
