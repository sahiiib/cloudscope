"""Browser-bound redirects; callback failures never expose provider responses."""

from typing import cast

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response

from cloudscope.api.routes.auth import Auth, set_session_cookie
from cloudscope.auth.oidc import COOKIE, NotAuthorized, OIDCService
from cloudscope.auth.sessions import COOKIE_NAME

router = APIRouter(prefix="/api/auth")


def service(request: Request) -> OIDCService:
    oidc = cast(OIDCService | None, request.app.state.oidc)
    if oidc is None:
        raise HTTPException(404, "SSO is not enabled")
    return oidc


@router.get("/config")
def config(auth: Auth) -> dict[str, object]:
    return {
        "local_login": True,
        "sso": {"enabled": auth.sso_enabled, "label": "Sign in with Keycloak"},
    }


@router.get("/oidc/login")
def login(request: Request, auth: Auth, next: str = "/") -> Response:
    oidc = service(request)
    try:
        cookie, url = oidc.begin(next, request.cookies.get(COOKIE))
    except Exception:
        return RedirectResponse(
            "/login?error=sso", status_code=302, headers={"Cache-Control": "no-store"}
        )
    response = RedirectResponse(
        url,
        status_code=302,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
    response.set_cookie(
        COOKIE,
        cookie,
        max_age=600,
        httponly=True,
        secure=auth.cookie_secure,
        samesite="lax",
        path="/api/auth/oidc",
    )
    return response


@router.get("/oidc/callback")
def callback(request: Request, auth: Auth) -> Response:
    oidc = service(request)
    ip = request.client.host if request.client else "unknown"
    response: Response
    allowed = auth.limiter.allow(ip)
    try:
        if not allowed:
            oidc.audit("", "", ip, "rate_limited")
            response = Response("Too many login attempts", status_code=429)
        else:
            data = oidc.consume(request.cookies.get(COOKIE), request.query_params.get("state", ""))
            if request.query_params.get("error") or not request.query_params.get("code"):
                raise ValueError()
            result, target = oidc.complete(
                data,
                request.query_params["code"],
                ip,
                request.headers.get("user-agent", "")[:1024],
                request.cookies.get(COOKIE_NAME),
            )
            response = RedirectResponse(target, status_code=302)
            set_session_cookie(response, result.token, auth, result.max_age)
    except NotAuthorized:
        response = RedirectResponse("/login?error=not-authorized", status_code=302)
    except Exception:
        oidc.audit("", "", ip, "failed")
        response = RedirectResponse("/login?error=sso", status_code=302)
    response.delete_cookie(
        COOKIE, httponly=True, secure=auth.cookie_secure, samesite="lax", path="/api/auth/oidc"
    )
    response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    return response
