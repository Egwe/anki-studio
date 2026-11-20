"""Tests for hashing and verifying the login password."""

import pytest

from anki_studio.passwords import (
    PasswordHashError,
    hash_password,
    parse_hash,
    verify_password,
)


def test_hash_roundtrip() -> None:
    """A hashed password verifies; another password does not."""
    encoded = hash_password("richtig-geheim")

    assert verify_password("richtig-geheim", encoded)
    assert not verify_password("falsch-geheim", encoded)


def test_hash_format_has_no_dollar_and_fresh_salt() -> None:
    """Hashes are safe for environment files and salted individually."""
    first, second = hash_password("richtig-geheim"), hash_password("richtig-geheim")

    assert first.startswith("scrypt:32768:8:1:")
    assert "$" not in first
    assert first != second


def test_short_password_is_rejected() -> None:
    """Passwords below eight characters are refused."""
    with pytest.raises(ValueError, match="mindestens 8"):
        hash_password("kurz")


@pytest.mark.parametrize(
    "encoded",
    [
        "",
        "bcrypt:1:2:3:4:5",
        "scrypt:32768:8:1:c2FsdA",
        "scrypt:abc:8:1:c2FsdA:a2V5",
        "scrypt:1000:8:1:c2FsdA:a2V5",
        "scrypt:2097152:8:1:c2FsdA:a2V5",
        "scrypt:32768:8:1::a2V5",
        "scrypt:32768:8:1:c2FsdA:!!!",
    ],
)
def test_invalid_hashes_are_rejected(encoded: str) -> None:
    """Malformed hashes, bad parameters, and bad Base64 raise an error.

    Args:
        encoded: Invalid stored hash.
    """
    with pytest.raises(PasswordHashError):
        parse_hash(encoded)


def test_verify_rejects_invalid_hash() -> None:
    """Verification does not silently accept a broken hash."""
    with pytest.raises(PasswordHashError):
        verify_password("richtig-geheim", "scrypt:broken")
