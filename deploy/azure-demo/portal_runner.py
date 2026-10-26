"""Gunicorn entrypoint that retains the portal's delivery/reconciliation worker."""

import threading

from werkzeug.middleware.proxy_fix import ProxyFix

from app.web import app, run_sync_worker

# Only Caddy can reach this container, so trust its forwarded host/scheme.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
threading.Thread(target=run_sync_worker, name="verifyflow-sync", daemon=True).start()
