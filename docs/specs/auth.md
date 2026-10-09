# Authentication and MFA

Local users only for now. SSO (OIDC) is a later phase.

## Passwords

- Hash: argon2id via `argon2-cffi` defaults. Rehash on login if parameters changed.
- Minimum length 12. No other composition rules.
- First admin is created with `cloudscope create-user <name> --admin` (prompts
  for the password, never takes it as an argument).

`cloudscope.auth.passwords` provides `hash_password`, `verify_password` and
`verify_and_rehash`. The last returns `(valid, replacement_hash)`; the login
handler added in T-021 must persist a non-null replacement after successful
verification. Wrong passwords and malformed stored hashes return failure and
never trigger rehash. Minimum length applies when creating/changing passwords.

`create-user` uses the exported database URL and an already-migrated schema;
it does not need the Fernet key. The password is entered twice with input
hidden and is never accepted as an argument or option. Users are active,
non-admin by default, and have MFA disabled; `--admin` explicitly grants admin.
Duplicate usernames fail without updating existing users. Database/hash errors
are reported without their underlying exception details or local variables.

## Login flow

```
POST /api/auth/login {username, password}
  ├─ bad credentials → 401 (same message for unknown user and wrong password)
  ├─ MFA disabled    → session created, mfa_passed = true  → {mfa_required: false}
  └─ MFA enabled     → session created, mfa_passed = false → {mfa_required: true}
POST /api/auth/mfa/verify-login {code}
  ├─ valid TOTP      → mfa_passed = true, session id rotated
  └─ invalid         → 401; 5 failures → session deleted
```

A session with `mfa_passed = false` can only call `verify-login` and `logout`,
and expires after 5 minutes.

## Sessions

- Token: 32 random bytes, URL-safe base64, in cookie `cloudscope_session`
  (`HttpOnly`, `SameSite=Lax`, `Secure` when `CLOUDSCOPE_COOKIE_SECURE=true`,
  `Path=/`).
- Only the SHA-256 of the token is stored (`sessions.id_hash`).
- Lifetime `CLOUDSCOPE_SESSION_TTL_HOURS` (default 12), sliding on activity up
  to that max. This is an idle timeout: each authenticated request refreshes
  the database expiration and browser cookie by the configured duration. There
  is no separate absolute lifetime; half-authenticated sessions never slide.
- CSRF: state-changing requests must send header `X-Requested-With: cloudscope`
  (the UI always does); combined with `SameSite=Lax` this blocks cross-site
  form posts.

## TOTP (Google Authenticator)

- `pyotp`, RFC 6238, SHA-1, 6 digits, 30 s step, `valid_window=1`.
- Issuer `cloudscope`, account name = username.
- Secret is stored encrypted with Fernet (`CLOUDSCOPE_SECRET_KEY`).
- Setup: `mfa/setup` returns the `otpauth://` URI and a QR code SVG (generated
  server-side with `segno`), user scans it, then confirms with `mfa/enable`.
- Reject reuse of the same code within its window (store last used timestep).
- MFA is optional per user. An admin can reset a user's MFA.

## Brute-force protection

- Per user: after 5 failed logins, lock for 15 minutes (`locked_until`).
- Per IP: in-memory limit of 20 login attempts per minute per API pod.
- Failed and successful logins are logged (username, IP, result), never passwords
  or codes.

## API implementation

T-021 provides login, logout, current-user and password endpoints. API startup
loads `Settings` (including database URL and Fernet key); missing/invalid settings
leave authentication unavailable (503) while health probes remain usable. The
Fernet key is validated now and used by MFA in T-022. `create_app` also accepts an
injected engine/settings/clock for tests. `current_user` checks expiration, active
user status and completed MFA; `require_admin` additionally checks admin status.

Login rotates an existing cookie, stores only the new token hash, persists any
Argon2 rehash, and resets failure counters on success. Five wrong passwords lock
the user for 15 minutes; after that window a fresh set of attempts is allowed.
Unknown, inactive and locked users receive the same 401 as a wrong password.
Per-IP limiting counts known and unknown usernames, returns 429 after 20 attempts
in a sliding minute, and is independent per API process. The client address is
`request.client.host`; forwarded headers must only be trusted from configured
proxies at the server layer. Audit log values are quoted to prevent newlines
from forging log entries. Exception payloads and passwords are not logged.

All implemented mutation endpoints, including login and logout, require the
CSRF header. Logout also accepts a still-valid half-authenticated session.
Password changes require the current password and a new password of at least
12 characters, revoke **all** sessions, and clear the cookie; the user logs in
again. Validation errors omit submitted input values. The session table already
exists from T-005; migration `0002` indexes `sessions.user_id` and adds cascading
deletion when its user is deleted. Successful login also removes that user’s
expired sessions in the same transaction. TOTP verification remains T-022.

`/api/docs` and `/api/openapi.json` require an authenticated admin, including in
local development. A secure cookie requires HTTPS; use the documented
`CLOUDSCOPE_COOKIE_SECURE=false` only for local HTTP development.
