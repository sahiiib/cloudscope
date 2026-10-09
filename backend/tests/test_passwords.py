import pytest
from argon2 import PasswordHasher, extract_parameters
from argon2.low_level import Type

from cloudscope.auth.passwords import hash_password, verify_and_rehash, verify_password

PASSWORD = "test-password-placeholder"


def test_argon2id_hashes_are_salted_and_verify() -> None:
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)
    assert first != second and first != PASSWORD
    assert extract_parameters(first).type is Type.ID
    assert verify_password(PASSWORD, first)
    assert verify_password(PASSWORD, second)
    assert not verify_password("incorrect-password-placeholder", first)
    assert verify_and_rehash(PASSWORD, first) == (True, None)


@pytest.mark.parametrize("password", ["", "x" * 11])
def test_minimum_password_length(password: str) -> None:
    with pytest.raises(ValueError, match="at least 12"):
        hash_password(password)


@pytest.mark.parametrize("password", ["x" * 12, " " * 12, "پ" * 12])
def test_length_is_only_password_policy(password: str) -> None:
    assert verify_password(password, hash_password(password))


@pytest.mark.parametrize("encoded", ["", "invalid-placeholder", "$argon2id$bad"])
def test_malformed_hash_is_rejected(encoded: str) -> None:
    assert verify_password(PASSWORD, encoded) is False
    assert verify_and_rehash(PASSWORD, encoded) == (False, None)


@pytest.mark.parametrize("kind", [Type.I, Type.ID])
def test_rehash_only_after_successful_verification(kind: Type) -> None:
    old_hash = PasswordHasher(type=kind, time_cost=1, memory_cost=8192, parallelism=1).hash(
        PASSWORD
    )
    assert verify_and_rehash("incorrect-password-placeholder", old_hash) == (False, None)
    valid, replacement = verify_and_rehash(PASSWORD, old_hash)
    assert valid is True and replacement is not None
    assert replacement != old_hash
    assert extract_parameters(replacement).type is Type.ID
    assert verify_password(PASSWORD, replacement)
    assert not PasswordHasher().check_needs_rehash(replacement)
