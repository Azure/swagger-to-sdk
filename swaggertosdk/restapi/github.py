import os
from enum import Enum
import hmac
import hashlib
import logging
from queue import Queue
import traceback
from threading import Thread

from flask import request, jsonify

from github import Github

from .bot_framework import (
    BotHandler
)
from .sdkbot import (
    GithubHandler
)
from .restbot import (
    RestAPIRepoHandler
)
from .github_handler import (
    rest_pr_management,
    generate_sdk_from_git_object
)
from ..github_tools import (
    exception_to_github,
    DashboardCommentableObject,
)
from . import app

_LOGGER = logging.getLogger("swaggertosdk.restapi.github")
_QUEUE = Queue(64)


# Webhook secreet to authenticate message (bytes)
SECRET = b'mydeepsecret'

_HMAC_CHECK = False

def check_hmac(local_request, secret):
    data = local_request.get_data()
    hmac_tester = hmac.HMAC(secret, data, hashlib.sha1)
    if not 'X-Hub-Signature' in local_request.headers:
        raise ValueError('X-Hub-Signature is mandatory on this WebService')
    if local_request.headers['X-Hub-Signature'] == 'sha1='+hmac_tester.hexdigest():
        return True
    raise ValueError('Bad X-Hub-Signature signature')

@app.route('/github', methods=['POST'])
def notify():
    """Github main endpoint."""
    github_bot = GithubHandler()
    bot = BotHandler(github_bot)
    github_index = {
        'ping': ping,
        'issue_comment': bot.issue_comment,
        'issues': bot.issues
    }
    return handle_github_webhook(
        github_index,
        request.headers['X-GitHub-Event'],
        request.get_json()
    )

@app.route('/github/rest', methods=['POST'])
def rest_notify():
    """Github rest endpoint."""
    sdkid = request.args.get("sdkid")
    sdkbase = request.args.get("sdkbase", "master")
    sdk_tag = request.args.get("repotag", sdkid.split("/")[-1].lower())

    if not sdkid:
        return {'message': 'sdkid is a required query parameter'}

    rest_bot = RestAPIRepoHandler(sdkid, sdk_tag, sdkbase)
    bot = BotHandler(rest_bot)
    github_index = {
        'ping': ping,
        'push': push,
        'pull_request': rest_pull_request,
        'issue_comment': bot.issue_comment,
        'issues': bot.issues
    }
    if not _WORKER_THREAD.is_alive():
        _WORKER_THREAD.start()

    return handle_github_webhook(
        github_index,
        request.headers['X-GitHub-Event'],
        request.get_json()
    )

def handle_github_webhook(github_index, gh_event_type, json_body):
    if _HMAC_CHECK:
        check_hmac(request, SECRET)
    _LOGGER.info("Received Webhook %s", request.headers.get("X-GitHub-Delivery"))

    json_answer = notify_github(github_index, gh_event_type, json_body)
    return jsonify(json_answer)

def notify_github(github_index, event_type, json_body):
    if event_type in github_index:
        return github_index[event_type](json_body)
    return {'message': 'Not handled currently'}

def ping(body):
    return {'message': 'Moi aussi zen beaucoup'}

def push(body):
    sdkid = request.args.get("sdkid")
    sdkbase = request.args.get("sdkbase", "master")
    sdk_tag = request.args.get("repotag", sdkid.split("/")[-1].lower())

    rest_api_branch_name = body["ref"][len("refs/heads/"):]
    if rest_api_branch_name == "master":
        return {'message': 'Webhook disabled for RestAPI master'}

    gh_token = os.environ["GH_TOKEN"]
    github_con = Github(gh_token)

    restapi_git_id = body['repository']['full_name']
    restapi_repo = github_con.get_repo(restapi_git_id)

    commit_obj = restapi_repo.get_commit(body["after"])
    generate_sdk_from_git_object(
        commit_obj,
        "restapi_auto_"+rest_api_branch_name,
        restapi_git_id,
        sdkid,
        [], # I don't know if the origin branch comes from "master", assume it.
        fallback_base_branch_name=sdkbase,
        sdk_tag=sdk_tag
    )
    return {'message': 'No return for this endpoint'}

def rest_pull_request(body):
    sdkid = request.args.get("sdkid")
    sdkbase = request.args.get("sdkbase", "master")
    sdk_tag = request.args.get("repotag", sdkid.split("/")[-1].lower())

    _LOGGER.info("Received PR action %s", body["action"])
    _QUEUE.put((body, sdkid, sdkbase, sdk_tag))
    _LOGGER.info("Received action has been queued. Queue size: %d", _QUEUE.qsize())

    return {'message': 'Current queue size: {}'.format(_QUEUE.qsize())}

def rest_handle_action(body, sdkid, sdkbase, sdk_tag):
    """First method in the thread.
    """
    _LOGGER.info("Rest handle action")
    gh_token = os.environ["GH_TOKEN"]
    github_con = Github(gh_token)

    sdk_pr_target_repo = github_con.get_repo(sdkid)

    restapi_repo = github_con.get_repo(body['repository']['full_name'])
    rest_pr = restapi_repo.get_pull(body["number"])
    dashboard = DashboardCommentableObject(rest_pr, "# Automation for {}".format(sdk_tag))

    _LOGGER.info("Received PR action %s", body["action"])
    with exception_to_github(dashboard, sdk_tag):
        if body["action"] in ["opened", "reopened"]:
            return rest_pull_open(body, restapi_repo, sdk_pr_target_repo, sdkbase, sdk_tag)
        if body["action"] == "closed":
            return rest_pull_close(body, restapi_repo, sdk_pr_target_repo, sdkbase, sdk_tag)
        if body["action"] == "synchronize": # push to a PR from a fork
            return rest_pull_sync(body, restapi_repo, sdk_pr_target_repo, sdkbase, sdk_tag)

def rest_pull_open(body, restapi_repo, sdk_pr_target_repo, sdk_default_base="master", sdk_tag=None):
    _LOGGER.info("Received a PR open event")

    rest_pr = restapi_repo.get_pull(body["number"])
    rest_pr_management(rest_pr, sdk_pr_target_repo, sdk_tag, sdk_default_base)


def rest_pull_close(body, restapi_repo, sdk_pr_target_repo, sdk_default_base="master", sdk_tag=None):
    _LOGGER.info("Received a PR closed event")

    rest_pr = restapi_repo.get_pull(body["number"])
    rest_pr_management(rest_pr, sdk_pr_target_repo, sdk_tag, sdk_default_base)

def rest_pull_sync(body, restapi_repo, sdk_pr_target_repo, sdk_default_base="master", sdk_tag=None):

    # If this sync has no commit change, save CPU time.
    if body["before"] == body["after"]:
        return {'message': 'No commit id change'}

    # If this sync corresponds to a local branch, let "push" event handle it
    origin_repo = body["pull_request"]["head"]["repo"]["full_name"]
    if origin_repo == restapi_repo.full_name:
        _LOGGER.info("This will be handled by 'push' event on the branch")
        return

    rest_pr = restapi_repo.get_pull(body["number"])
    rest_pr_management(rest_pr, sdk_pr_target_repo, sdk_tag, sdk_default_base)

def consume():
    """Consume action and block if there is not.
    """
    while True:
        body, sdkid, sdkbase, sdk_tag = _QUEUE.get()
        _LOGGER.info("Pop from queue. Queue size: %d", _QUEUE.qsize())
        try:
            rest_handle_action(body, sdkid, sdkbase, sdk_tag)
        except Exception as err:
            _LOGGER.critical("Worked thread issue:\n%s", traceback.format_exc())
    _LOGGER.info("End of WorkerThread")

_WORKER_THREAD = Thread(
    target=consume,
    name="WorkerThread"
)
