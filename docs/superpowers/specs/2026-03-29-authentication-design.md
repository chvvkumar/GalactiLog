# Authentication Design Spec

**Date:** 2026-03-29
**Status:** Approved
**Scope:** Add JWT-based authentication with role-based access control to GalactiLog

## Goals

1. Gate access when the app is exposed to the public internet (single admin account)
2. Basic access control for trusted LAN users (1-2 read-only viewer accounts)
3. Follow MVSP (Minimum Viable Secure Product) controls for application design and implementation
4. Ensure the app works correctly behind an external reverse proxy with TLS termination

## Non-Goals

- Multi-tenancy or per-user data isolation (all users see the same catalog)
- Self-registration or OAuth/SSO (accounts are created by admin via CLI)
- MVSP business controls (formal vulnerability disclosure program, external pen testing, compliance certifications) -- note: `docs/security.md` will include lightweight vulnerability reporting guidance, but not a full VDP
- MVSP operational controls (physical access, sub-processors, DR)

---

## Section 1: Token Strategy

### Access Token

- JWT stored in an HttpOnly cookie
- Algorithm: HS256 with a 256-bit cryptographically random secret (`openssl rand -hex 32`)
- Expiry: 30 minutes
- Claims: `sub` (user ID), `role`, `exp`, `iat`, `jti` (unique ID for revocation)
- Cookie attributes: `httponly=True`, `secure=True` (disabled in dev via `ASTRO_SECURE_COOKIES=false`), `samesite="strict"`, `path="/"`

### Refresh Token

- Opaque random token (not JWT), stored hashed (SHA-256) in PostgreSQL
- Expiry: 7 days
- Cookie attributes: `httponly=True`, `secure=True` (disabled in dev), `samesite="strict"`, `path="/api/auth/refresh"`
- Rotation: every use issues a new token and revokes the old one
- Theft detection: if a revoked token is reused, the entire token family is revoked

### CSRF Protection

- `SameSite=Strict` on all cookies is sufficient since frontend and API are same-origin behind nginx
- No CSRF tokens needed

---

## Section 2: Reverse Proxy Hardening

Three fixes to the existing setup for production readiness behind an external proxy:

### A. Complete nginx proxy headers

Add missing `X-Forwarded-For` and `X-Forwarded-Proto` to the `/thumbnails` location block, matching the `/api` location:

```nginx
location /thumbnails {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

### B. Health check endpoint

`GET /api/health` returns `{"status": "ok"}`. Unauthenticated so the external proxy can use it for monitoring.

### C. Uvicorn --proxy-headers

Add `--proxy-headers` flag to the uvicorn command in supervisord.conf so Starlette reads `X-Forwarded-*` headers and `request.client.host` reflects the real client IP (required for rate limiting by IP).

---

## Section 3: User Model & Roles

### User Table

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `username` | String | Unique, for login |
| `password_hash` | String | Argon2id via pwdlib |
| `role` | Enum | `admin` or `viewer` |
| `is_active` | Boolean | Disable without deleting |
| `created_at` | DateTime | Auto-set |
| `updated_at` | DateTime | Auto-updated |

### Refresh Token Table

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID | Primary key |
| `user_id` | UUID | FK to User |
| `token_hash` | String | SHA-256 of the opaque token |
| `family_id` | UUID | Groups tokens for theft detection |
| `expires_at` | DateTime | 7-day expiry |
| `revoked` | Boolean | Set true on rotation or logout |
| `created_at` | DateTime | Auto-set |

### Role Permissions

| Action | Admin | Viewer |
|--------|-------|--------|
| Browse targets, images, stats | Yes | Yes |
| View settings | Yes | Yes |
| Trigger/stop scans | Yes | No |
| Change settings | Yes | No |
| Merge/unmerge targets | Yes | No |
| Manage users | Yes | No |

### User Management

- CLI command: `python -m app.cli create-user --username <name> --role <admin|viewer>`
- Prompts for password interactively (no default passwords)
- Admin can manage users through API endpoints (`POST/PUT/DELETE /api/auth/users`)
- Admin cannot delete or deactivate their own account (prevents lockout)
- No self-registration

### Password Hashing

- Argon2id via `pwdlib` with `PasswordHash.recommended()` defaults
- On failed login with unknown username, hash a dummy password to prevent timing-based enumeration

---

## Section 4: Auth Endpoints & Flow

### Endpoints

| Endpoint | Method | Auth Required | Purpose |
|----------|--------|---------------|---------|
| `POST /api/auth/login` | POST | No | Authenticate, set access + refresh cookies |
| `POST /api/auth/refresh` | POST | Refresh cookie | Rotate refresh token, issue new access token |
| `POST /api/auth/logout` | POST | Access cookie | Clear cookies, revoke refresh token family |
| `GET /api/auth/me` | GET | Access cookie | Return current user info (username, role) |
| `POST /api/auth/users` | POST | Admin | Create user |
| `PUT /api/auth/users/:id` | PUT | Admin | Update user (role, active status) |
| `DELETE /api/auth/users/:id` | DELETE | Admin | Delete user |
| `PUT /api/auth/password` | PUT | Access cookie | Change own password (requires current password) |
| `GET /api/health` | GET | No | Health check |

### Login Flow

1. Frontend sends `POST /api/auth/login` with `{ "username": "...", "password": "..." }`
2. Backend looks up user, verifies password (or hashes dummy on unknown user)
3. Generates JWT access token (30 min) and opaque refresh token
4. Hashes refresh token (SHA-256), stores in `refresh_token` table with a new `family_id`
5. Sets both as HttpOnly cookies in the response
6. Returns `{ "username": "...", "role": "..." }`
7. Frontend redirects to dashboard

### Token Refresh Flow

1. Frontend gets a 401 on any request
2. Frontend calls `POST /api/auth/refresh` (browser sends refresh cookie automatically)
3. Backend looks up the hashed token in DB, checks not revoked and not expired
4. If the token was already revoked (reuse detection): revoke entire family, return 401
5. Otherwise: revoke old token, issue new refresh + access tokens with the same `family_id`
6. Frontend retries the original request

### Logout Flow

1. `POST /api/auth/logout`
2. Backend revokes all tokens in the user's current refresh token family
3. Both cookies cleared with `max_age=0`
4. Frontend redirects to `/login`

### Route Protection (Backend)

- `get_current_user` dependency: reads JWT from cookie, decodes, validates expiry and signature, returns User
- `require_admin` dependency: wraps `get_current_user`, checks `role == admin`
- All existing routers get `get_current_user` added (viewers can access GET routes)
- Mutation endpoints (scan, settings, merge, user management) get `require_admin`
- `GET /api/health` has no auth dependency

---

## Section 5: Frontend Changes

### New Route: `/login`

- Simple login form: username, password, submit button, error display
- No auth context needed to render this page
- On success, redirect to `/` (dashboard)

### Auth Guard: `ProtectedRoute`

- Wrapper component that calls `GET /api/auth/me` on mount
- On 401, redirects to `/login`
- Stores user info (username, role) in a SolidJS `AuthProvider` context

### Route Structure

```
/login         -> LoginPage (unprotected)
/              -> ProtectedRoute -> DashboardPage
/targets/:id   -> ProtectedRoute -> TargetDetailPage
/statistics    -> ProtectedRoute -> StatisticsPage
/settings      -> ProtectedRoute -> SettingsPage
```

### Role-Based UI

- Viewer role: hide/disable scan trigger buttons, settings mutation controls, merge/unmerge actions
- Role read from `AuthProvider` context
- Cosmetic only -- backend enforces permissions regardless

### API Client Changes

- Add `credentials: "same-origin"` to fetch calls (explicit, though same-origin is the default)
- Response interceptor: on 401, call `/api/auth/refresh`. If refresh also 401s, redirect to `/login`. Otherwise retry original request.
- Prevent refresh loop (only retry once)

### NavBar

- Add logout button (visible to all roles)
- Calls `POST /api/auth/logout`, redirects to `/login`

---

## Section 6: Security Hardening (MVSP Compliance)

### Nginx Security Headers

Added to all responses:

```
Strict-Transport-Security: max-age=63072000; includeSubDomains
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:
```

Added to `/api` responses only:

```
Cache-Control: no-store
```

### Password Policy

- Minimum 12 characters
- Maximum 128 characters
- No character restrictions (any Unicode allowed)
- No default passwords (CLI forces interactive input)
- Require current password to change password
- No secret questions

### Audit Logging

Structured JSON logs to stdout (captured by Docker logging).

**Events logged:**
- Login success / failure
- Logout
- Token refresh (success / failure / reuse detection)
- Password change
- User created / updated / deleted
- Role changed

**Fields per entry:**
- `timestamp` (ISO 8601)
- `event` (event type)
- `user_id` (UUID, or null for failed login with unknown user)
- `username` (for login events)
- `source_ip` (from X-Forwarded-For)
- `success` (boolean)
- `detail` (optional context, e.g., "account locked" or "refresh token reuse detected")

**Excluded from logs:** passwords, tokens, hashes, request bodies.

**Retention:** minimum 30 days, configurable via Docker log rotation settings.

### Rate Limiting

Using `slowapi` middleware:

| Scope | Limit | Action on exceed |
|-------|-------|------------------|
| Per account (login) | 5 attempts per 15 minutes | 30-minute lockout |
| Per IP (login) | 20 attempts per minute | 429 response |
| Per user (refresh) | 10 per minute | 429 response |

Account lockout tracked in Redis (auto-expires).

### CORS

- Not needed in production (same origin behind nginx)
- Dev mode: explicit allowlist for `http://localhost:3000` with `allow_credentials=True`

---

## Section 7: Testing Strategy

### Backend pytest Suite

| Test Category | Cases |
|---------------|-------|
| **Credentials** | Valid login, invalid password, invalid username, disabled user, timing-safe rejection |
| **JWT validation** | Valid token accepted, expired rejected, tampered rejected, wrong algorithm rejected, missing cookie rejected |
| **Refresh flow** | Successful rotation, reuse detection (family revoked), expired refresh rejected, refresh after logout rejected |
| **Role enforcement** | Viewer blocked on every mutation endpoint (scan, settings, merge, unmerge, user CRUD), viewer allowed on all GET endpoints |
| **Password policy** | Reject under 12 chars, accept 128 chars, accept Unicode, require current password for change |
| **Rate limiting** | Lockout after 5 failures, IP-based limiting, lockout expiry |
| **Audit logging** | Verify log entries emitted for each event type with correct fields |
| **Health endpoint** | Returns 200 with no auth |

### OWASP ZAP Post-Deploy Scan

Run against the deployed instance behind the reverse proxy. Validates:
- No auth bypass on protected endpoints
- Cookie flags (HttpOnly, Secure, SameSite)
- Security headers present and correct
- HSTS active
- No sensitive data leaked in responses or cache
- Results documented in `docs/security.md`

---

## Section 8: Documentation

### Design Spec (this document)

`docs/superpowers/specs/2026-03-29-authentication-design.md`

### Security Implementation Details

`docs/security.md` -- living document, updated as auth behavior changes.

Sections:
- Authentication overview
- Password policy
- Token lifecycle (access, refresh, rotation, revocation, theft detection)
- Cookie security (all attributes with rationale)
- Security headers (full list with rationale)
- Rate limiting (thresholds, lockout behavior)
- Audit logging (event types, fields, retention, exclusions)
- Sensitive data inventory
- Data flow diagrams (login, refresh, authenticated request)
- MVSP compliance matrix
- Vulnerability reporting guidance
- Test results (pytest summary, last ZAP scan date and findings)
- Patch policy (90-day fix SLA per MVSP 3.4)

---

## Sensitive Data Inventory (MVSP 3.1)

| Data | Location | Protection |
|------|----------|------------|
| Password hashes | PostgreSQL `user.password_hash` | Argon2id, never logged |
| Refresh token hashes | PostgreSQL `refresh_token.token_hash` | SHA-256, revocable |
| JWT access tokens | HttpOnly cookie (browser), never stored server-side | HS256 signed, 30-min expiry, Secure + SameSite=Strict |
| Refresh tokens (plaintext) | HttpOnly cookie (browser), hashed server-side | 7-day expiry, rotation, family revocation |
| JWT signing secret | Environment variable `ASTRO_JWT_SECRET` | Never in source code, never logged |
| User IPs | Audit logs (stdout) | 30-day retention, no long-term storage |

## Auth Data Flow (MVSP 3.2)

### Login Flow

```
Browser                    Nginx                    FastAPI                  PostgreSQL
  |                          |                         |                        |
  |-- POST /api/auth/login ->|-- proxy_pass ---------->|                        |
  |                          |                         |-- lookup user -------->|
  |                          |                         |<-- user + hash --------|
  |                          |                         |-- verify password      |
  |                          |                         |-- generate JWT         |
  |                          |                         |-- generate refresh tok |
  |                          |                         |-- store hash(refresh)->|
  |                          |<-- Set-Cookie (x2) -----|                        |
  |<-- Set-Cookie (x2) ------|                         |                        |
```

### Authenticated Request Flow

```
Browser                    Nginx                    FastAPI
  |                          |                         |
  |-- GET /api/targets ----->|-- proxy_pass ---------->|
  |   (cookies auto-sent)    |                         |
  |                          |                         |-- read JWT from cookie
  |                          |                         |-- verify signature + expiry
  |                          |                         |-- check role permissions
  |                          |                         |-- execute handler
  |                          |<-- 200 + data ----------|
  |<-- 200 + data -----------|                         |
```

### Refresh Flow

```
Browser                    Nginx                    FastAPI                  PostgreSQL
  |                          |                         |                        |
  |-- POST /api/auth/refresh>|-- proxy_pass ---------->|                        |
  |   (refresh cookie sent)  |                         |-- hash(token)          |
  |                          |                         |-- lookup hash -------->|
  |                          |                         |<-- token row ----------|
  |                          |                         |-- check: revoked?      |
  |                          |                         |   if yes: revoke family, 401
  |                          |                         |   if no: continue      |
  |                          |                         |-- revoke old token --->|
  |                          |                         |-- generate new pair    |
  |                          |                         |-- store new hash ----->|
  |                          |<-- Set-Cookie (x2) -----|                        |
  |<-- Set-Cookie (x2) ------|                         |                        |
```

---

## New Dependencies

### Backend (pyproject.toml)

| Package | Purpose |
|---------|---------|
| `pwdlib[argon2]` | Password hashing (Argon2id) |
| `PyJWT` | JWT creation and verification |
| `slowapi` | Rate limiting middleware |

### Frontend

No new dependencies required.

---

## New Environment Variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `ASTRO_JWT_SECRET` | Yes | None (must be set) | HS256 signing key (min 64 hex chars) |
| `ASTRO_ACCESS_TOKEN_EXPIRY` | No | `1800` (30 min) | Access token lifetime in seconds |
| `ASTRO_REFRESH_TOKEN_EXPIRY` | No | `604800` (7 days) | Refresh token lifetime in seconds |
| `ASTRO_SECURE_COOKIES` | No | `true` | Set to `false` for local dev without HTTPS |

---

## Migration Notes

- New Alembic migration adds `user` and `refresh_token` tables
- Existing data is unaffected (no changes to target, image, or settings tables)
- First deploy requires running `python -m app.cli create-user` to bootstrap admin account
- App refuses to start (or warns loudly) if `ASTRO_JWT_SECRET` is not set
