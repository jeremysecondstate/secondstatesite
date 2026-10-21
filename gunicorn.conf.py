"""Allow a reviewed three-email bundle to finish its bounded transport calls."""
import os

# This is an operational allowance, not a total Gmail/OAuth deadline. Each
# delivery is committed before transport and uncertain outcomes are never resent.
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "180"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "180"))
