# Security

GalactiLog authentication and security implementation details.

## Authentication

Cookie-based JWT authentication, same-origin behind nginx reverse proxy.

- **Access token:** JWT (HS256), 30-minute expiry, stored in an HttpOnly cookie
- **Refresh token:** Opaque random string, 7-day expiry, SHA-256 hashed in PostgreSQL, stored in an HttpOnly cookie
- **CSRF:** SameSite=Strict cookies; no CSRF tokens needed (same-origin only)
- **Timing safety:** Failed logins with unknown usernames hash a dummy password to prevent enumeration

## Password Policy

| Rule | Detail |
|------|--------|
| Length | 12-128 characters |
| Characters | Any Unicode, no restrictions |
| Hashing | Argon2id via `pwdlib` (`PasswordHash.recommended()` defaults) |
| Defaults | None; CLI forces interactive password input |
| Changes | Requires current password |

## Token Lifecycle

### Access Token

| Property | Value |
|----------|-------|
| Format | JWT (HS256) |
| Expiry | 30 minutes |
| Claims | `sub` (user ID), `role`, `exp`, `iat`, `jti` |
| Storage | HttpOnly cookie only; never stored server-side |

### Refresh Token

| Property | Value |
|----------|-------|
| Format | Opaque random string |
| Expiry | 7 days |
| Storage | SHA-256 hash in PostgreSQL; plaintext in HttpOnly cookie |
| Rotation | New token issued on every use; old token revoked |
| Theft detection | Reuse of a revoked token revokes the entire token family |

Token families group all refresh tokens descended from a single login. If a revoked token is presented, all tokens in that family are revoked immediately, forcing re-authentication.

## Cookie Security

| Attribute | Access Token Cookie | Refresh Token Cookie |
|-----------|--------------------|--------------------|
| HttpOnly | Yes | Yes |
| Secure | Yes (configurable via `ASTRO_HTTPS`) | Yes (configurable via `ASTRO_HTTPS`) |
| SameSite | Strict | Strict |
| Path | `/` | `/api/auth/refresh` |

Set `ASTRO_HTTPS=false` for local development without HTTPS.

## Security Headers

Applied by nginx to all responses:

| Header | Value |
|--------|-------|
| Strict-Transport-Security | `max-age=63072000; includeSubDomains` (2 years) |
| X-Frame-Options | `DENY` |
| X-Content-Type-Options | `nosniff` |
| Referrer-Policy | `strict-origin-when-cross-origin` |
| Content-Security-Policy | `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:` |

Applied to `/api` responses only:

| Header | Value |
|--------|-------|
| Cache-Control | `no-store` |

## Rate Limiting

Implemented via `slowapi` middleware. Account lockout tracked in Redis with auto-expiry.

| Scope | Limit | Action on Exceed |
|-------|-------|------------------|
| Per account (login) | 5 failed attempts per 15 minutes | 30-minute account lockout |
| Per IP (login) | 20 attempts per minute | 429 response |
| Per user (refresh) | 10 attempts per minute | 429 response |

## Audit Logging

Structured JSON logs emitted to stdout, captured by Docker logging.

### Events

- Login success/failure
- Logout
- Token refresh (success, failure, reuse detection)
- Password change
- User created, updated, deleted

### Log Entry Fields

| Field | Description |
|-------|-------------|
| `timestamp` | ISO 8601 |
| `event` | Event type |
| `user_id` | UUID (null for failed login with unknown user) |
| `username` | For login events |
| `source_ip` | From X-Forwarded-For |
| `success` | Boolean |
| `detail` | Optional context (e.g., "account locked", "refresh token reuse detected") |

### Exclusions

Passwords, tokens, hashes, and request bodies are never logged.

### Retention

Minimum 30 days, configurable via Docker log rotation settings.

## Roles

| Action | Admin | Viewer |
|--------|-------|--------|
| Browse targets, images, stats | Yes | Yes |
| View settings | Yes | Yes |
| Trigger/stop scans | Yes | No |
| Change settings | Yes | No |
| Merge/unmerge targets | Yes | No |
| Manage users | Yes | No |

Backend enforces role permissions on all endpoints. Frontend hides controls for unauthorized actions as a cosmetic convenience only.

## CORS

Not needed in production (frontend and API are same-origin behind nginx).

For development: set `ASTRO_CORS_ORIGINS` environment variable with an explicit allowlist (e.g., `http://localhost:3000`). Credentials are allowed (`allow_credentials=True`).

## User Management

### First-Time Setup

Set `ASTRO_ADMIN_PASSWORD` in `.env`. On first start, if no users exist, an admin account is created automatically:

| Variable | Default | Purpose |
|----------|---------|---------|
| `ASTRO_ADMIN_PASSWORD` | *(none)* | Admin password. Required for auto-creation. |
| `ASTRO_ADMIN_USERNAME` | `admin` | Admin username. |

Once a user exists in the database, these variables are ignored.

### CLI

```
python -m app.cli create-user --username <name> --role <admin|viewer>
```

Prompts for password interactively. Useful for creating additional users without the web UI.

### Admin API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/auth/users` | POST | Create user |
| `/api/auth/users/:id` | PUT | Update user (role, active status) |
| `/api/auth/users/:id` | DELETE | Delete user |

Admin cannot delete or deactivate their own account.

## Sensitive Data Inventory

| Data | Location | Protection |
|------|----------|------------|
| Password hashes | PostgreSQL `user.password_hash` | Argon2id, never logged |
| Refresh token hashes | PostgreSQL `refresh_token.token_hash` | SHA-256, revocable |
| JWT access tokens | HttpOnly cookie (browser) | HS256 signed, 30-min expiry, Secure + SameSite=Strict |
| Refresh tokens | HttpOnly cookie (browser), hashed server-side | 7-day expiry, rotation, family revocation |
| JWT signing secret | Environment variable or auto-generated at startup | Never in source code, never logged |
| User IPs | Audit logs (stdout) | 30-day retention via Docker log rotation |

## Vulnerability Reporting

Report security issues by email to the repository maintainer. Fix SLA: 90 days.
