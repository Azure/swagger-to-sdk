from . import app
from jsonrpc.backend.flask import api

@app.route("/")
def hello():
    return "Hello World!"