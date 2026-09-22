# Cue & Console Club — Mobile-first PWA

Flask + SQLAlchemy backend with a responsive, installable PWA-style interface for Android and iPhone. Multiple owner/staff devices can share data when the app is deployed against the same hosted database.

## Included
- Owner/staff login with role-gated pricing and product management
- Five resources: Pool 1, Pool 2, Snooker, PS4, PS5
- Session timers, pause/resume, estimates, and configurable controller charges
- Manual product creation/editing; no sample products are preloaded
- Checkout with itemized live estimate, discount, received amount, and balance
- Booking create/edit/cancel, overlap validation, and booking calendar/list
- Remote dashboard refreshes every 15 seconds; date-filtered bill history
- PostgreSQL support through `DATABASE_URL`; SQLite for local testing
- PWA manifest and mobile-responsive layout

## Local setup (for development/testing)
Requires Python 3.11+.

```bash
python -m venv .venv
# Windows PowerShell
.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
python app.py
```

Open `http://127.0.0.1:5000`.

Default local credentials if you have not configured environment variables:
- Owner: `owner` / `ChangeMe123!`
- Staff: `staff` / `StaffChange123!`

Change both passwords and `SECRET_KEY` before using real data. Do not expose Flask's development server to the public internet.

## Free hosting / phone installation
You can try a free-tier host and a free-tier managed PostgreSQL provider, but free plans have limits and may sleep, pause, expire, or change. This means free hosting is suitable for prototyping—not guaranteed, uninterrupted business operation. Check current provider limits before relying on it.

For shared multi-device use:
1. Deploy this Flask app to a Python-compatible host.
2. Create a managed PostgreSQL database and set `DATABASE_URL` in the host's environment.
3. Set a strong, unique `SECRET_KEY`, `OWNER_USERNAME`, `OWNER_PASSWORD`, `STAFF_USERNAME`, and `STAFF_PASSWORD`.
4. Deploy and test bookings, sessions, billing, and data persistence across multiple devices.
5. Use the resulting HTTPS URL:
   - Android: open in Chrome → menu → **Add to Home screen** / **Install app**.
   - iPhone: open in Safari → Share → **Add to Home Screen**.

All devices must use the same deployed URL/database. The SQLite file on one device/server is not a shared cloud database. PWA installation does not itself provide offline transaction sync.

## Important MVP limitations
This is a starter application, not audited production POS software. Before live commercial use, add production-grade CSRF protection, rate limiting, password reset/MFA, database migrations, robust timezone/business-hours handling, atomic booking exclusion constraints (especially for concurrent requests), complete split-payment allocation, payment/refund reconciliation, automated backups, and end-to-end tests. Remote access requires deployment; this ZIP is not hosted automatically.
