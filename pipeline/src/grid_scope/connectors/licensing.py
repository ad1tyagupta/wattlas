from __future__ import annotations

import re


_ALLOWED_LICENCES = {
    "ccby40",
    "cc010",
    "odbl10",
    "uspublicdomain",
    "publicdomain",
    "ogl",
    "ogl10",
    "ogl20",
    "ogl30",
}


def normalize_licence(value: str) -> str:
    """Return a comparison token for the deliberately small public-data allowlist."""

    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def is_redistributable_licence(value: str) -> bool:
    token = normalize_licence(value)
    return token in _ALLOWED_LICENCES or token.startswith(
        ("ogl", "opengovernmentlicence", "opengovernmentlicense")
    )


def require_redistributable_licence(value: str, *, label: str) -> None:
    if not is_redistributable_licence(value):
        raise ValueError(f"{label} licence is not redistributable")
