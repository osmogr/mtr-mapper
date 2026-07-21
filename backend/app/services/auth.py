import hmac

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings

SESSION_COOKIE_NAME = "mtrmapper_admin_session"
_SALT = "mtrmapper-admin-session"


def _serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    return URLSafeTimedSerializer(settings.admin_session_secret, salt=_SALT)


def check_password(candidate: str) -> bool:
    settings = get_settings()
    return hmac.compare_digest(candidate, settings.admin_password)


def create_session_token() -> str:
    return _serializer().dumps({"admin": True})


def verify_session_token(token: str | None) -> bool:
    if not token:
        return False
    settings = get_settings()
    try:
        data = _serializer().loads(token, max_age=settings.admin_session_ttl_seconds)
    except (BadSignature, SignatureExpired):
        return False
    return bool(data.get("admin"))
