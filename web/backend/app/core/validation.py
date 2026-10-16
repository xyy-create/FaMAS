from __future__ import annotations

import re

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 80
PASSWORD_MIN_LENGTH = 8

PASSWORD_POLICY_MESSAGE = (
    "Password must be at least 8 characters and include at least one letter and one number."
)
USERNAME_POLICY_MESSAGE = (
    "Username must be between 3 and 80 characters and can only contain letters, "
    "numbers, hyphens, and underscores."
)


def validate_username(username: str) -> str:
    if len(username) < USERNAME_MIN_LENGTH or len(username) > USERNAME_MAX_LENGTH:
        return USERNAME_POLICY_MESSAGE
    if not username.replace("_", "").replace("-", "").isalnum():
        return USERNAME_POLICY_MESSAGE
    return ""


def validate_password_strength(password: str) -> str:
    if len(password) < PASSWORD_MIN_LENGTH:
        return PASSWORD_POLICY_MESSAGE
    if not re.search(r"[A-Za-z]", password):
        return PASSWORD_POLICY_MESSAGE
    if not re.search(r"\d", password):
        return PASSWORD_POLICY_MESSAGE
    return ""
