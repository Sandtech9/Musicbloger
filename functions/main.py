import os
import sys

# Ensure root workspace directory containing server.py and database.py is in sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from firebase_functions import https_fn
from a2wsgi import WSGIMiddleware
from server import app

# Wrap FastAPI (ASGI) into WSGI interface for Firebase Cloud Functions
wsgi_app = WSGIMiddleware(app)

@https_fn.on_request()
def api(req: https_fn.Request) -> https_fn.Response:
    return https_fn.Response.from_app(wsgi_app, req.environ)
