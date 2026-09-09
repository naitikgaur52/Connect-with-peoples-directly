# Higher-Ed Contact Research & Outreach System

A private, self-contained application that:

1. Scrapes configured college/university web pages for relevant academic
   contacts (deans, chairs, program directors, etc. — titles/disciplines
   are configurable).
2. Deduplicates against a historical database and a standing exclusion
   list before anything is sent.
3. Sends personalized outreach emails (with a CV attachment) through a
   dedicated Gmail account, within configurable volume/frequency
   safeguards.
4. Gives you a private web dashboard to review contacts, manage
   exclusions, edit templates, adjust settings, view history, and export
   to Excel/CSV.

Nothing in this system depends on the developer's personal accounts,
servers, or API keys. Every credential is supplied by whoever deploys it.

---

## 1. How it's built (architecture)

```
main.py                    Entry point: starts web dashboard + scheduler
app/
  config.py                All settings, loaded from .env
  models.py                Database schema (SQLAlchemy)
  dedup.py                 The eligibility/safeguard engine (single source of truth)
  scheduler.py             Cron-based background jobs (discovery + outreach)
  export.py                CSV / Excel export
  scraper/
    extractor.py           HTML -> contact heuristics (JSON-LD, mailto cards, text fallback)
    discovery.py           Fetches seed URLs, runs extraction, writes to DB
  gmail/
    auth.py                Google OAuth flow
    sender.py               Template rendering + sending + logging
  dashboard/
    routes.py               All web routes
    templates/               HTML pages (Bootstrap, no build step needed)
scripts/
  authorize_gmail.py        One-time Gmail OAuth setup
  set_admin_password.py     Generates your dashboard password hash
  seed_initial_data.py      Optional starter titles + email template
```

**Why this shape:**
- The eligibility engine (`app/dedup.py`) is the *only* place that decides
  "can we email this person right now." Both the scheduler and the manual
  "Send now" button in the dashboard call the same function, so there is
  no way to bypass the safeguards from either path.
- The scraper does not crawl the open web on its own — it works from an
  admin-managed list of **seed URLs** (e.g., a specific faculty directory
  page). This keeps behavior predictable, auditable, and respectful of
  each site's `robots.txt` (checked automatically before every fetch).
- Extraction is heuristic (see section 4) because there is no universal
  structure to college directory pages — the system is built to be tuned
  over time, not to be a one-shot script.

---

## 2. Installation

Requires Python 3.10+.

```bash
git clone <this-repo>   # or unzip the delivered archive
cd edu-outreach
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
python scripts/set_admin_password.py     # paste the printed hash into .env
```

Put your CV at `attachments/cv.pdf` (path configurable via
`CV_ATTACHMENT_PATH` in `.env`).

Run it:

```bash
python main.py
```

Visit `http://localhost:5000`, log in with the admin username/password
you set. The database (SQLite) is created automatically on first run at
`data/outreach.db`.

Optionally seed some starter target titles and a sample template:

```bash
python scripts/seed_initial_data.py
```

---

## 3. Gmail API setup (one-time)

The system sends through **your own dedicated Gmail account** — never the
developer's.

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and
   create a new project (or use an existing one).
2. Enable the **Gmail API** for that project.
3. Configure the OAuth consent screen (choose "Internal" if using Google
   Workspace, or "External" + add your own Gmail address as a test user
   if using a personal Gmail account).
4. Create an **OAuth client ID** of type "Desktop app."
5. Download the resulting JSON file, rename it `credentials.json`, and
   place it in the project root (path configurable via
   `GMAIL_CREDENTIALS_FILE`).
6. Set `GMAIL_SENDER_EMAIL` in `.env` to the sending address.
7. Run the one-time authorization:

   ```bash
   python scripts/authorize_gmail.py
   ```

   This opens a browser, asks you to log into that Gmail account, and
   grants send-only permission (`gmail.send` scope — this app can send
   mail but cannot read your inbox). A `token.json` refresh token is
   saved locally; after this, sending is fully automated with no further
   login prompts, and the token refreshes itself.

**Cost:** the Gmail API is free for this volume of use (well under
Google's quota for a personal/workspace account).

---

## 4. How site-structure differences are handled

College websites vary enormously, so extraction uses three layered
heuristics, applied to every page in this order (see
`app/scraper/extractor.py`):

1. **Structured data first** — many university CMSs (WordPress, Drupal,
   Cascade) embed `schema.org Person` JSON-LD blocks; when present, this
   is the highest-confidence, most reliable source.
2. **"Card" heuristic** — for typical staff-directory grids, every
   `mailto:` link is found, then the surrounding HTML block is scanned
   for a name (heading tags) and a title (matched against your
   configured target-title keywords).
3. **Plain-text fallback** — as a last resort, any email address on the
   page is considered, but only kept if a target-title keyword appears
   in the surrounding text.

Every extracted contact gets a **confidence score**. Below your
configured threshold (default 0.75), a contact is routed to the **Needs
Review** queue instead of being auto-approved for sending — you make the
final call. As you encounter site layouts the heuristics miss, this is
the file to extend; it's isolated from the database and scheduling logic
specifically so it can be improved independently.

This system is not a "smart AI scraper" that guarantees 100% accuracy on
every site — no such thing exists given how different these pages are.
It is a maintainable framework with sensible defaults and a manual review
safety net.

---

## 5. Duplicate & repeat-contact prevention

Layered checks, all in `app/dedup.py`:

- **Database-level dedup**: a contact is unique per (institution, email);
  re-discovering the same person just updates their existing record
  instead of creating a duplicate.
- **Standing exclusion list**: block by institution, domain, email,
  department, or name — checked before every send, independent of any
  contact's current status.
- **Cooldown period**: won't re-email the same person until N days
  (configurable) have passed since the last send.
- **Per-institution cap**: won't exceed N contacts emailed per
  institution.
- **Daily / monthly caps**: hard ceilings on total volume.
- **Confidence threshold**: uncertain matches never auto-send; they wait
  in Needs Review.
- **Manual duplicate marking**: in the dashboard, any contact can be
  marked as a duplicate of another, which sets it to "do not contact."
- **Global pause switch**: one click in the dashboard stops all
  automated scraping and sending immediately.

---

## 6. Deployment

For continuous operation, run on any always-on machine or small VPS
(e.g., a $5-6/month droplet/Lightsail instance, or an existing server you
already have). Two processes:

```bash
# Web dashboard (behind a reverse proxy like nginx + HTTPS in production)
gunicorn -w 2 -b 0.0.0.0:5000 main:app

# Background worker (discovery + outreach on schedule) — run as a
# separate process so restarting the web dashboard never affects
# scheduled jobs. Set RUN_SCHEDULER=false for the gunicorn process above,
# and run this instead:
RUN_SCHEDULER=true python -c "from app.factory import create_app; from app.scheduler import start_scheduler; app=create_app(); start_scheduler(app); import time; [time.sleep(3600) for _ in iter(int,1)]"
```

In practice, wrap each as a `systemd` service (or a Docker Compose file
with two services) so they restart automatically on reboot/crash. A
minimal `systemd` unit or `docker-compose.yml` can be added at handoff if
you'd like — ask and I'll include one tailored to your host.

Put the dashboard behind HTTPS (e.g., via nginx + Let's Encrypt, or a
platform like Render/Railway/Fly.io that provides HTTPS automatically) —
credentials should never be sent over plain HTTP.

---

## 7. Backup & recovery

Everything that matters is two files:

- `data/outreach.db` — the entire database (contacts, exclusions,
  templates, history, settings).
- `token.json` — the Gmail refresh token.

**Backup:** copy these on a schedule (a simple daily cron job running
`cp data/outreach.db backups/outreach-$(date +%F).db` is sufficient for
this volume; for extra safety, sync backups off-server, e.g., to cloud
storage).

**Recovery:** restore `data/outreach.db` and `token.json` to a fresh
install of this same codebase with the same `.env`, and it resumes
exactly where it left off. No data is stored anywhere else.

---

## 8. Third-party services & recurring costs

- **Gmail API**: free at this volume (uses your existing Google account).
- **Hosting**: whatever you choose to run it on — a small VPS is
  typically $5-10/month, or it can run on hardware you already own/manage
  (this app has no hard requirement to be cloud-hosted).
- **No other third-party services are required.** No paid scraping APIs,
  no external CRM, no SaaS subscriptions. Everything is self-contained
  Python + SQLite.

---

## 9. What you receive at handoff

- Complete source code (this repository).
- Database schema (created automatically by the code; also inspectable
  via any SQLite browser).
- `.env.example` with every configuration option documented.
- This README (installation, Gmail setup, deployment, backup/recovery).
- Full admin access to the dashboard (you set your own password).
- No dependency on the developer's accounts, servers, or keys — you
  create your own Google Cloud project, your own Gmail authorization,
  and host it wherever you choose.

---

## 10. Using the dashboard day to day

- **Seed URLs** — add the directory/staff-listing pages you want scraped.
- **Target Criteria** — set which job titles and disciplines matter.
- **Contacts** — search, review, edit, change status, manually send.
- **Exclusions** — block any institution/domain/email/department/name.
- **Templates** — edit the email content sent to qualified contacts.
- **Settings** — adjust daily/monthly caps, cooldown, confidence
  threshold, or pause automation entirely.
- **Outreach History** — full audit trail of every email attempt.
- **Export** — download the full contact database or history as CSV/XLSX
  at any time.
