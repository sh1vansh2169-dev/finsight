"""Service-level errors. The API maps each to an HTTP status."""


class NotFoundError(LookupError):
    """404: the requested record does not exist."""


class ConflictError(RuntimeError):
    """409: the request clashes with the record's current state."""


class InvalidRequestError(ValueError):
    """422: the request is well-formed but not allowed."""


class PayloadTooLargeError(ValueError):
    """413: the uploaded file is too big."""
