"""How Formiq compares email addresses: one rule for signing up, for telling
whether an address already has an account, and for logging in.

An address is one account whatever its case: "Asha@Example.com" and
"asha@example.com" are the same. New accounts store it normalized, so the
database's unique email constraint holds the rule for them; accounts made
before it may differ from each other only in case, and are never merged.
"""


def normalize_email(email: str) -> str:
    """The email as Formiq stores and matches it: without surrounding spaces,
    in lower case."""
    return email.strip().lower()
