# Assembly Register

QR-code attendance for a church. Members scan a code at the entrance, type
the first few letters of their name, and tap themselves. After the service
the pastoral team downloads a list of who was **not** there, with phone
numbers, so they can call during the week.

- No app, no login and no member cards. One tap on the member's own phone.
- A fresh code for every service. It only works during that service's
  check-in window, so nobody can check in from home on a Tuesday.
- Several churches can share one installation. Each assembly has its own
  admin token and can only ever see its own data.
- Python 3.12, FastAPI, PostgreSQL, SQLAlchemy 2, Alembic, Jinja2 and
  Docker Compose. No JavaScript build step.

---

## Sunday-morning runbook

### Before the service (Saturday evening or early Sunday)

1. Sign in at `https://<your-site>/admin/ui` with your assembly's admin token.
2. Under **New service**, check the date (it defaults to the coming Sunday)
   and the check-in window (default 08:30–15:00), then press **Create service
   and show QR code**.
3. Either project that page (the QR code is on the right), or press
   **Download PNG to print** and print two or three copies for the entrance
   table. Each PNG carries the church name and the date, so last week's
   printout can't be mixed up with this week's.
4. Scan the code with your own phone to check that it opens the check-in page.

> Each service has its own code. Last Sunday's printout will not work this
> Sunday. That is intentional.

### During the service

| Situation | What to do |
|---|---|
| Someone has no smartphone, or can't manage | An usher signed in on the admin page opens the service, chooses **Add someone by hand**, and picks the name. This also works after the window closes. |
| Someone tapped the wrong name | On the service page, press **Remove** next to the wrong entry, then add the right person by hand. |
| A phone shows "No connection. Ask an usher to add you." | The hall wifi or mobile data dropped. Add them by hand, or write their name down and add it after the service. |
| Their name isn't found | They may not be on the roll yet, or have no recorded consent. Add them on **Members** (tick consent only if they agree), then check them in by hand. |
| A first-time visitor | They use **First time here?** at the bottom of the check-in page: name, plus a phone number if they want one. |
| The page says "Check-in opens at …" | It is earlier than the window. Wait, or check in by hand. |

### After the service

1. Open the service from **Services**. **Present** lists who checked in;
   **Absent** lists active members who gave consent and didn't check in.
2. Press **Download call list (CSV)**. It has the columns
   `name, phone, called, notes`. The last two are blank, for whoever makes
   the calls.
3. Share the file only with the people who will make the calls. Don't post
   it in a group chat, and delete it once the calls are done.

---

## Deployment

You need a small Linux server, ideally hosted in the EU, with Docker and the
Compose plugin, plus a domain name pointing at it.

```sh
git clone <this repo> assembly-register && cd assembly-register
cp .env.example .env
$EDITOR .env          # set POSTGRES_PASSWORD, BASE_URL, CHURCH_NAME

docker compose up -d --build
```

Compose starts Postgres, runs the Alembic migrations in a one-off `migrate`
container, and then starts the app on `127.0.0.1:8000`. The schema is never
created implicitly at startup. Migrations are the only way it changes.

### Create the first assembly

```sh
docker compose exec app python scripts/seed_assembly.py --contact-email office@your-church.de
```

This uses `CHURCH_NAME` from `.env`. If `ADMIN_TOKEN` is set in `.env`, that
becomes the assembly's token. Otherwise a random token is generated and
printed **once**. Either way, only a SHA-256 digest of the token is stored.
The app never reads `ADMIN_TOKEN`, so remove it from `.env` once the
assembly is seeded. Keep the token in a password manager.

The contact email appears in the footer of the check-in page as the address
for data requests.

### Load the membership roll

Prepare a UTF-8 CSV with the header `first_name,last_name,phone,email`. Only
include people whose consent you actually hold (see GDPR below).

```sh
docker compose cp roll.csv app:/tmp/roll.csv
docker compose exec app python scripts/seed_members.py /tmp/roll.csv \
    --assembly <slug> --consent-date 2026-09-20
```

`--consent-date` records when consent was given, for example the date the
paper forms were signed. It defaults to now. You can safely run the script
again: anyone already present, matched on first name, last name and phone,
is skipped.

### HTTPS (required)

Put a TLS-terminating reverse proxy in front of the app. With
[Caddy](https://caddyserver.com/), which gets certificates automatically, it
looks like this:

```
register.your-church.de {
    reverse_proxy 127.0.0.1:8000
}
```

`BASE_URL` must be the public `https://` address. Check-in links and QR
codes are built from it, and an `https://` address also makes the admin
cookie `Secure`.

**Recommended:** rate-limit `/s/` at the proxy, for example to 30 requests a
minute per IP. This makes the name search much harder to scrape (see GDPR).

### More assemblies

```sh
docker compose exec app python scripts/seed_assembly.py --name "Assembly Name" --slug assembly-slug
```

Give the printed token to that church's team. Tokens are per assembly, so a
team can only ever see its own members and services.

To rotate a token, for example when someone leaves the team:

```sh
docker compose exec app python scripts/seed_assembly.py --slug <slug> --rotate-token
```

### Retention job

Run retention once a month for each assembly, from cron on the host:

```sh
curl -fsS -X POST -H "X-Admin-Token: $TOKEN" https://register.your-church.de/admin/retention/run
```

Or press **Run retention now** at the bottom of the Services page.

### Upgrades, backups and tests

```sh
git pull && docker compose up -d --build                  # migrations run first
docker compose exec db pg_dump -U register register | gzip > backup-$(date +%F).sql.gz
docker compose --profile test run --rm test                 # test suite against the db container
```

Keep backups short-lived (for example 30 days, encrypted). Data you erase in
the app stays in older backups until they expire. The GDPR section explains
why that matters.

### Printing a QR code from the command line

```sh
docker compose exec app python scripts/make_qr.py "https://register.your-church.de/s/<token>" \
    -o /tmp/sunday.png --caption "Assembly Name" --caption "Sunday 4 October"
docker compose cp app:/tmp/sunday.png .
```

The admin page's **Download PNG to print** button produces the same image.

---

## GDPR

*This section explains how the software supports compliance. It is not
legal advice. Have someone responsible for data protection in your church
read it.*

**Church attendance is special-category data.** Recording that someone
attends a church reveals their religious beliefs (Art. 9 GDPR). A religious
body may process this data about its members and regular contacts
(Art. 9(2)(d)), as long as it has appropriate safeguards and doesn't disclose
the data outside the church without consent. In Germany a free church
registered as an *e.V.* is generally subject to the GDPR and the BDSG, not to
the churches' own data-protection laws. In practice:

- record this processing in your *Verzeichnis von Verarbeitungstätigkeiten*;
- sign a data processing agreement (AVV) with your hosting provider, and
  host in the EU;
- keep the admin tokens and the CSV exports within the pastoral team.

### Consent

- `members.consent_at` is a column on the member record. If it is `NULL`,
  the member **never** appears in the check-in search or in an absentee
  list or CSV, and cannot be checked in by id.
- Record consent on paper or a form first. Then tick the box when adding the
  member, use **Record consent** on the Members page, or pass
  `--consent-date` to `seed_members.py`.
- **Withdraw** clears `consent_at` at once. The member disappears from
  search and from call lists, but their record stays until it is deleted.
- Visitors give their name and optional phone voluntarily on the visitor
  form. The form says why the phone number is asked for. Visitor details live
  only on the attendance row, so retention removes them with it.
- The check-in page footer explains why attendance is recorded and that
  anyone can ask to see or delete their record.

### Right of access and erasure

- **Access:** the Members page and the service pages show everything held
  about a person. `GET /admin/members` and the attendance endpoints return
  it as JSON.
- **Erasure:** **Delete** on the Members page (`DELETE /admin/members/{id}`)
  removes the member **and all their attendance**. This uses
  `ON DELETE CASCADE`, so no orphaned rows remain. A visitor's entry can be
  removed with **Remove** on the service page.
- Erased data persists in database backups until they expire. Keep backup
  retention short and say so in your privacy notice.

### Retention

`POST /admin/retention/run` deletes attendance rows older than
`RETENTION_DAYS` (default 730, about two years) for the calling assembly,
including visitor details. Member records themselves are not deleted by
retention. Delete members who leave, rather than only deactivating them,
once you no longer need their record. The retention job runs only when
called, so schedule it (see Deployment).

### The name search exposes member names

While a service is open, **anyone holding the live link** can type two
letters and see up to eight matching names. By working through prefixes they
could list most of the roll of consenting members. That is the cost of
one-tap, no-login check-in. It is limited by:

- the link only working during that service's window, and being new each
  service;
- search returning only names and the "already here" flag, never phone
  numbers or emails;
- rate limiting at the reverse proxy (recommended above);
- never posting the link or code online, for example on social media or in
  livestream slides.

**Stricter alternative:** ask for the first name **plus the last four digits
of the member's phone number**, and show a match only when both agree.
Holding the link would then reveal nothing. The trade-offs: it is slower at
the door, it is harder for older members who don't know their number by
heart, and it doesn't work for members without a phone (they would always
need an usher). To switch, change `search_members` in `app/register.py` to
require the digits and change the check-in form to ask for them. Nothing
else needs to change.

### Other safeguards built in

- Admin tokens are stored as SHA-256 digests and compared with
  `secrets.compare_digest`.
- Pages are sent with `Referrer-Policy: no-referrer`, so the check-in token
  never leaks to other sites. They also have a strict Content-Security-Policy
  (no third-party scripts, fonts or trackers), `Cache-Control: no-store`, and
  `noindex`.
- The CSV export neutralises spreadsheet formulas in names (CSV injection)
  while leaving phone numbers such as `+49 …` untouched.

---

## Reference

### Endpoints

Public routes take the assembly from the service token in the URL:

| Method | Path | Notes |
|---|---|---|
| GET | `/s/{token}` | Check-in page. Shows a friendly "opens at" or "closed" page outside the window, and a 404 page for unknown tokens. `?q=` is the no-JavaScript search. |
| GET | `/s/{token}/members?q=` | Name lookup. At least 2 characters, at most 8 results. Returns 403 when the service is closed. Members already checked in are flagged `checked_in: true`. |
| POST | `/s/{token}/check-in` | Form fields `member_id` **or** `visitor_name` (+ `visitor_phone`). Returns HTML, or JSON with `Accept: application/json`. A repeat check-in returns `"status": "already"`, never an error. |

Admin routes take the assembly from the `X-Admin-Token` header, or from the
admin UI's cookie:

| Method | Path |
|---|---|
| POST | `/admin/services`: `{"service_date": "2026-10-04", "title"?, "opens_at"?, "closes_at"?}`. Times without a zone are read as the assembly's local time. |
| GET | `/admin/services`: newest first, with member and visitor counts |
| GET | `/admin/services/{id}/attendance` |
| GET | `/admin/services/{id}/absentees` |
| GET | `/admin/services/{id}/absentees.csv` |
| GET | `/admin/services/{id}/qr.png` |
| POST | `/admin/members`: `{"first_name", "last_name", "phone"?, "email"?, "notes"?, "consent": bool}` |
| GET | `/admin/members` |
| DELETE | `/admin/members/{id}`: full erasure, including attendance |
| POST | `/admin/retention/run` |
| GET | `/healthz` |

Admin web UI: `/admin/ui` (services), `/admin/ui/services/{id}`,
`/admin/ui/members`.

### Data model

```
assemblies  id, name, slug (unique), timezone ('Europe/Berlin'), contact_email,
            admin_token_hash (unique, sha256), created_at
members     id, assembly_id → assemblies (indexed), first_name, last_name, phone,
            email, consent_at (nullable timestamptz), is_active, notes, created_at
services    id, assembly_id → assemblies (indexed), service_date, title,
            qr_token (unique, indexed), opens_at, closes_at, created_at
            CHECK (closes_at > opens_at)
attendance  id, service_id → services ON DELETE CASCADE,
            member_id → members ON DELETE CASCADE (NULL = visitor),
            visitor_name, visitor_phone, method ('qr' | 'manual'), checked_in_at
            UNIQUE (service_id, member_id)
            CHECK (member_id IS NOT NULL OR visitor_name IS NOT NULL)
```

All timestamps are `timestamptz`. The check-in window is entered and shown
in the assembly's time zone (Europe/Berlin by default) and compared in UTC.
Attendance has no `assembly_id` of its own: it reaches its assembly through
its service, and every check-in confirms that the member belongs to the
same assembly as the service.

### Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `POSTGRES_PASSWORD` | Database password |
| `ADMIN_TOKEN` | Optional. Token for the first assembly, read only by `seed_assembly.py` |
| `BASE_URL` | Public `https://` address, used in check-in links and QR codes |
| `CHURCH_NAME` | Name of the first assembly, read only by `seed_assembly.py` |
| `RETENTION_DAYS` | Attendance retention, default 730 |
| `SERVICE_OPENS` / `SERVICE_CLOSES` | Optional. Default check-in window, default `08:30` / `15:00` |

### Development

```sh
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
# any Postgres you can create databases on; the test database is created if missing
export TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/register_test
pytest
```

The tests build the schema with the Alembic migrations, so the migrations are
tested as well. They cover: check-in outside the window is rejected; a double
check-in doesn't duplicate; absentees exclude anyone who checked in and
anyone without consent; every admin endpoint returns 401 without a valid
token; and a token for assembly A cannot read or change assembly B's data.

### Patchy wifi

The check-in page is a single HTML document plus about 10 KB of CSS and
JavaScript. It loads no web fonts, frameworks or third-party resources. The
church name uses the phone's built-in serif. Each search is one small JSON
request, and stale searches are cancelled. When a request fails or takes
longer than 8–10 seconds, the page says so plainly ("No connection. Ask an
usher to add you.") instead of spinning. Without JavaScript the page still
works: search and check-in fall back to ordinary form submissions.
