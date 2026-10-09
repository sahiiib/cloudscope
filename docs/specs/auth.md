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
  to that max.
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
