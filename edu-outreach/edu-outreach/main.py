"""
Main entry point.

Running this starts:
  1. The Flask admin dashboard (web UI)
  2. The background scheduler (automated discovery + outreach on cron)

For local testing:      python main.py
For production:         see README.md ("Deployment") for running under
                         gunicorn + a process supervisor (systemd/Docker),
                         with the scheduler run as a separate worker
                         process (recommended) rather than inside the web
                         process.
"""

import os
from app.factory import create_app
from app.scheduler import start_scheduler

app = create_app()

# The scheduler is opt-in via RUN_SCHEDULER=true so that, in production,
# you can run the web dashboard and the background worker as two separate
# processes (recommended -- see README.md) without double-scheduling jobs.
if os.environ.get("RUN_SCHEDULER", "true").lower() == "true":
    start_scheduler(app)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
