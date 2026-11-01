from dataclasses import dataclass
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.config import settings

bearer = HTTPBearer(auto_error=False)

# Supabase stamps `iat` with its own clock. A server or laptop whose clock runs a moment behind would reject a
# freshly issued token as "not yet valid". A few seconds of leeway absorbs that normal drift; it is not a
# way to accept old tokens (exp still applies, at most this many seconds late).
CLOCK_SKEW_LEEWAY_SECONDS = 10
_jwks = PyJWKClient(f"{settings.supabase_url}/auth/v1/.well-known/jwks.json")

# The only algorithms accepted, pinned so any change shows up in review. Shared-secret (HS*) and "none" are never valid.
ALLOWED_ALGORITHMS = ("ES256", "RS256")
# Tokens must come from this project's auth service.
_ISSUER = f"{settings.supabase_url.rstrip('/')}/auth/v1"

@dataclass
class CurrentUser:
    id: str
    email: str | None
    role: str
    org_id: str | None

def _unauthorized(msg: str = "Invalid or missing token") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, msg, headers={"WWW-Authenticate": "Bearer"})

def _decode(token: str) -> dict:
    try:
        alg = jwt.get_unverified_header(token).get("alg")
        if alg not in ALLOWED_ALGORITHMS:
            raise _unauthorized()
        key = _jwks.get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=[alg], audience="authenticated", issuer=_ISSUER,
                          leeway=CLOCK_SKEW_LEEWAY_SECONDS, options={"require": ["exp", "iss", "aud"]})
    except jwt.PyJWTError:
        raise _unauthorized()

def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> CurrentUser:
    if creds is None:
        raise _unauthorized()
    
    claims = _decode(creds.credentials)
    role = claims.get("user_role")
    
    if role is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Token has no user_role claim")
        
    return CurrentUser(
        id=claims["sub"],
        email=claims.get("email"),
        role=role,
        org_id=claims.get("org_id") or None,  # an empty claim means no org, never a blank id
    )

def require_role(*allowed: str):
    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")
        return user
    return checker
