import uuid


def new_uuid() -> uuid.UUID:
    """Generate a new UUID4."""
    return uuid.uuid4()


def short_id(uid: uuid.UUID) -> str:
    """Return a short hex representation of a UUID (no dashes)."""
    return uid.hex


def parse_uuid(value: str) -> uuid.UUID:
    """Parse a UUID from string or hex."""
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.UUID(hex=value)
