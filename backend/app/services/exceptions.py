"""Service-level errors. The API layer will translate them into HTTP responses."""


class ServiceError(Exception):
    """Base class for the service-level errors."""


class InvalidUserError(ServiceError):
    """The user data has neither an email nor a phone."""


class UserAlreadyExistsError(ServiceError):
    """A user with the same email or phone already exists."""


class UserNotFoundError(ServiceError):
    """The user does not exist."""


class UserProfileAlreadyExistsError(ServiceError):
    """The user already has a profile."""


class UserProfileNotFoundError(ServiceError):
    """The user has no profile."""


class InvalidProfileUpdateError(ServiceError):
    """The profile update sets a required field to null."""
