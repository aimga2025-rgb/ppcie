"""WSGI entrypoint for deploying the existing Dash app in ppc.py.

This file does not change any local runtime behavior.
Use with a WSGI server like gunicorn:
    gunicorn wsgi:server
"""

from ppc import app

# gunicorn looks for a module-level variable named `server` by default.
server = app.server
