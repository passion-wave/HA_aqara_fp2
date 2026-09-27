"""Classified failures with deliberately credential-free exception messages."""


class AqaraError(Exception):
    """Base error. Untrusted response/error text is never rendered."""

    error_key = "aqara_error"

    def __init__(self, *_details: object) -> None:
        super().__init__(self.error_key)


class InvalidResponse(AqaraError):
    error_key = "api_changed"


class ResponseTooLarge(InvalidResponse):
    error_key = "response_too_large"


class ProtocolUnsupported(AqaraError):
    error_key = "protocol_unsupported"


class AuthenticationRequired(AqaraError):
    error_key = "auth_required"


class AccountMismatch(AqaraError):
    error_key = "account_mismatch"


class TransportError(AqaraError):
    error_key = "cannot_connect"


class RequestRejected(AqaraError):
    error_key = "request_rejected"


class AccessDenied(RequestRejected):
    error_key = "access_denied"


class SignatureRejected(RequestRejected):
    error_key = "signature_rejected"


class ApplicationError(RequestRejected):
    error_key = "application_error"

    def __init__(
        self, code: int | None = None, *_details: object, http_status: int | None = None
    ) -> None:
        self.code = code if type(code) is int else None
        self.http_status = (
            http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        )
        super().__init__()


class RateLimited(TransportError):
    error_key = "rate_limited"

    def __init__(self, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__()
