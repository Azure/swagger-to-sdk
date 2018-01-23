from flask import Flask
from jsonrpc.backend.flask import api

from ..SwaggerToSdkMain import generate_sdk
from ..SwaggerToSdkCore import CONFIG_FILE, DEFAULT_COMMIT_MESSAGE

app = Flask(__name__)
app.add_url_rule('/', 'api', api.as_view(), methods=['POST'])

@api.dispatcher.add_method
def ping(*args, **kwargs):
    return "Pong!"

@api.dispatcher.add_method
def generate_project(*args, **kwargs):
    # Get required parameter
    rest_api_id = kwargs['rest_api_id']
    sdk_id = kwargs['sdk_id']
    project = kwargs['project']

    generate_sdk(
        os.environ['GH_TOKEN'],
        CONFIG_FILE,
        project,
        rest_api_id,
        sdk_id,
        None, # No PR repo id
        DEFAULT_COMMIT_MESSAGE,
        'master',
        None # Destination branch
    )

from .github import *
