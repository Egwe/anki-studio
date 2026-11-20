"""Hash and verify the login password with scrypt from the standard library.

A stored hash looks like ``scrypt:32768:8:1:<salt>:<key>`` with URL-safe
Base64 values. It contains no ``$``, so environment files can hold it
without quoting or variable expansion.
"""

import base64
import binascii
import hashlib
import hmac
import os
from dataclasses import dataclass

SCHEME = "scrypt"
COST = 2**15
BLOCK_SIZE = 8
PARALLELISM = 1
SALT_BYTES = 16
KEY_BYTES = 32
MAX_MEMORY = 64 * 2**20
MAX_COST = 2**20
MIN_PASSWORD_LENGTH = 8


class PasswordHashError(ValueError):
    """Report a stored password hash that cannot be parsed."""


@dataclass(frozen=True)
class ScryptHash:
    """Hold the parts of a parsed scrypt hash.

    Attributes:
        cost: CPU and memory cost ``n``; a power of two up to 2**20.
        block_size: Block size ``r``.
        parallelism: Parallelization ``p``.
        salt: Random salt bytes.
        key: Derived key bytes.
    """

    cost: int
    block_size: int
    parallelism: int
    salt: bytes
    key: bytes


def hash_password(password: str) -> str:
    """Derive a storable hash from a password with a fresh random salt.

    Args:
        password: Plain password; at least 8 characters.

    Returns:
        The encoded hash, for example ``scrypt:32768:8:1:<salt>:<key>``.

    Raises:
        ValueError: If the password is shorter than 8 characters.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Das Passwort braucht mindestens {MIN_PASSWORD_LENGTH} Zeichen.")
    salt = os.urandom(SALT_BYTES)
    key = _derive(password, salt, COST, BLOCK_SIZE, PARALLELISM, KEY_BYTES)
    parts = (SCHEME, str(COST), str(BLOCK_SIZE), str(PARALLELISM), _encode(salt), _encode(key))
    return ":".join(parts)


def verify_password(password: str, encoded: str) -> bool:
    """Check a password against a stored hash in constant time.

    Args:
        password: Password entered by the user.
        encoded: Hash created by ``hash_password``.

    Returns:
        True if the password matches.

    Raises:
        PasswordHashError: If ``encoded`` is no valid scrypt hash.
    """
    stored = parse_hash(encoded)
    key = _derive(
        password, stored.salt, stored.cost, stored.block_size, stored.parallelism, len(stored.key)
    )
    return hmac.compare_digest(key, stored.key)


def parse_hash(encoded: str) -> ScryptHash:
    """Split and check an encoded scrypt hash.

    Args:
        encoded: Hash in the format ``scrypt:n:r:p:salt:key``.

    Returns:
        The parsed parts.

    Raises:
        PasswordHashError: If the format, the numbers, or the Base64 values
            are invalid, or the cost exceeds 2**20.
    """
    parts = encoded.strip().split(":")
    if len(parts) != 6 or parts[0] != SCHEME:
        raise PasswordHashError("Kein scrypt-Hash im Format scrypt:n:r:p:salt:key.")
    try:
        cost, block_size, parallelism = (int(value) for value in parts[1:4])
        salt, key = _decode(parts[4]), _decode(parts[5])
    except (ValueError, binascii.Error) as error:
        raise PasswordHashError("Der scrypt-Hash enthält ungültige Werte.") from error
    if not _valid_parameters(cost, block_size, parallelism) or not salt or not key:
        raise PasswordHashError("Der scrypt-Hash enthält ungültige Parameter.")
    return ScryptHash(cost, block_size, parallelism, salt, key)


def _valid_parameters(cost: int, block_size: int, parallelism: int) -> bool:
    """Check scrypt parameters against safe bounds.

    Args:
        cost: CPU and memory cost ``n``.
        block_size: Block size ``r``.
        parallelism: Parallelization ``p``.

    Returns:
        True if ``n`` is a power of two between 2 and 2**20 and ``r`` and
        ``p`` are between 1 and 16.
    """
    power_of_two = cost > 1 and cost & (cost - 1) == 0
    return power_of_two and cost <= MAX_COST and 1 <= block_size <= 16 and 1 <= parallelism <= 16


def _derive(
    password: str, salt: bytes, cost: int, block_size: int, parallelism: int, length: int
) -> bytes:
    """Run scrypt with a memory limit large enough for the parameters.

    Args:
        password: Plain password, encoded as UTF-8.
        salt: Salt bytes.
        cost: CPU and memory cost ``n``.
        block_size: Block size ``r``.
        parallelism: Parallelization ``p``.
        length: Length of the derived key in bytes.

    Returns:
        The derived key.
    """
    memory = max(MAX_MEMORY, 256 * cost * block_size * parallelism)
    return hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=cost,
        r=block_size,
        p=parallelism,
        maxmem=memory,
        dklen=length,
    )


def _encode(data: bytes) -> str:
    """Encode bytes as URL-safe Base64 without padding.

    Args:
        data: Bytes to encode.

    Returns:
        ASCII text without ``=``, ``+``, or ``/``.
    """
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _decode(text: str) -> bytes:
    """Decode URL-safe Base64 with or without padding.

    Args:
        text: Encoded text.

    Returns:
        The decoded bytes.

    Raises:
        binascii.Error: If the text is no valid Base64.
    """
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
