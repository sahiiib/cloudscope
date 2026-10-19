# SSO login with Keycloak (OIDC)

Saheb, 2026-10-19. The cluster admin wants the whole team to log in with the
cluster's Keycloak. This adds OpenID Connect login next to local users; local
login with TOTP stays as the fallback (break-glass admin).

## Decisions

| Topic | Decision |
| --- | --- |
| Protocol | OIDC Authorization Code flow with PKCE (S256), confidential client. The browser never sees tokens; only the API talks to Keycloak's token endpoint. |
| Who may log in | Users with client role `cloudscope-user` or `cloudscope-admin` on client `cloudscope`. Anyone else gets "Not authorized" and no session. |
| Admin | Client role `cloudscope-admin` makes the user admin. Synced on every SSO login (role removed in Keycloak → admin removed at next login). |
| User record | Auto-created on first SSO login. Linked by `(issuer, sub)`, never by username or email. `username` = `preferred_username`; on a clash with an existing user it gets the suffix `@sso`. |
| Password and MFA | SSO users have no local password and cannot use password login. App TOTP does not apply to them; MFA is Keycloak's job. |
| Session | Same `cloudscope_session` cookie and lifetimes as local login ([auth](auth.md#sessions)), created with `mfa_passed = true`. Keycloak tokens are not stored. |
| Logout | Deletes the local session, then redirects to Keycloak's `end_session_endpoint` with `client_id` and `post_logout_redirect_uri` = app root (Keycloak may show a confirmation page; no ID token is stored for `id_token_hint`). |
| Local login | Only for local **admin** users (Saheb, 2026-10-19). When SSO is enabled, password login for a local non-admin user returns the same 401 as a wrong password, and `POST /api/users` and the Users page only create local admins (everyone else signs in with Keycloak). Turning `is_admin` off for a local user is rejected while SSO is enabled. With SSO off, local login works as today. |
| Disabled users | `is_active = false` blocks both SSO and local login, as today. |

## Flow

```
GET /api/auth/oidc/login?next=/path
  → 302 to Keycloak authorize (state, nonce, code_challenge)
GET /api/auth/oidc/callback?code&state
  ├─ state unknown/expired, or error param → 302 /login?error=sso
  ├─ token exchange, ID token checks fail   → 302 /login?error=sso
  ├─ no cloudscope role                     → 302 /login?error=not-authorized
  └─ ok → user upserted, session cookie set → 302 next (same-origin path only)
POST /api/auth/logout
  → {logout_url} for SSO sessions (UI navigates there), {} for local ones
GET /api/auth/config
  → {local_login: bool, sso: {enabled: bool, label: "Sign in with Keycloak"}}
```

- `state`, `nonce`, PKCE verifier and `next` live in a server-side row
  (`oidc_login_states`, 10-minute TTL, deleted on use), keyed by the SHA-256 of a
  random value kept in an `HttpOnly`, `SameSite=Lax` cookie `cloudscope_oidc`.
  This works with several API pods.
- ID token checks: signature against the issuer JWKS (cached, refreshed on
  unknown `kid`), `iss`, `aud` contains the client ID, `exp`/`iat` with 60 s
  leeway, `nonce`. Roles come from `resource_access.<client_id>.roles` in the
  ID token (Keycloak client mapper "Add to ID token" on).
- `next` must start with `/` and not `//`; otherwise `/`.
- The callback URL is `<public base URL>/api/auth/oidc/callback`. The public base
  URL is configured, never taken from request headers.
- Logs: SSO login result with username, `sub` and IP; never tokens or codes.
  Same per-IP rate limit as password login applies to the callback.

## Configuration

| Setting | Meaning |
| --- | --- |
| `CLOUDSCOPE_OIDC_ISSUER` | Realm URL, e.g. `https://keycloak.example.com/realms/team`. Empty = SSO off. Discovery via `/.well-known/openid-configuration`. |
| `CLOUDSCOPE_OIDC_CLIENT_ID` | Default `cloudscope`. |
| `CLOUDSCOPE_OIDC_CLIENT_SECRET` | From the app Secret, never in values. |
| `CLOUDSCOPE_PUBLIC_URL` | e.g. `https://cloudscope.example.com`; builds redirect URIs. |

Helm: `oidc.issuer`, `oidc.clientId`, `publicUrl` values with
template defaults (SSO off when `oidc.issuer` is empty), and
`CLOUDSCOPE_OIDC_CLIENT_SECRET` read from the existing Secret as an optional key.
The API pods reach the issuer through its **public URL** (the same URL the
browser uses), so discovery, JWKS and token calls need outbound HTTPS from the
API pods to that host; the issuer string must match the token's `iss`.

## Data model (migration `0014`)

- `users.oidc_issuer` (text, null), `users.oidc_subject` (text, null), unique
  together when not null. `users.password_hash` becomes nullable; a null hash
  never verifies.
- `oidc_login_states(id_hash pk, state, nonce, code_verifier, next_path,
  created_at)`, rows older than 10 minutes deleted on each new login.

## UI

- Login page: "Sign in with Keycloak" as the main button when SSO is enabled;
  below it a small "Admin sign-in" link that opens the password form. `?error=`
  shows a short message.
- Users page: column "Sign-in" (`Local` / `SSO`); SSO users have no password or
  MFA actions; admin toggle is read-only for SSO users (Keycloak decides). With
  SSO enabled, "Add user" creates a local admin and says so.
- Settings → Security: MFA setup is hidden for SSO users.

## Keycloak setup (cluster admin)

- Client `cloudscope`: OpenID Connect, client authentication on, standard flow
  only, PKCE method S256.
- Valid redirect URI `<public URL>/api/auth/oidc/callback`; post-logout
  redirect URI `<public URL>/`; web origin `<public URL>`.
- Client roles `cloudscope-user`, `cloudscope-admin`, assigned to users or groups.
- Mapper: client roles → token claim `resource_access.${client_id}.roles`,
  "Add to ID token" on (Keycloak's default `roles` scope adds it to the access
  token only).
- The client secret goes into the app Secret as `CLOUDSCOPE_OIDC_CLIENT_SECRET`.
