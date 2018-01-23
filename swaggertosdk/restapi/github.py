from datetime import datetime
from enum import Enum
from functools import wraps, lru_cache
import logging
from queue import Queue
import re
import traceback
from threading import Thread

from flask import request, jsonify

from github import Github, GithubException, UnknownObjectException

import hmac, hashlib
import os

from .github_handler import (
    build_from_issue_comment,
    build_from_issues,
    GithubHandler as LocalHandler,
    generate_sdk_from_commit
)
from . import app

_LOGGER = logging.getLogger(__name__)
_QUEUE = Queue(64)


# Webhook secreet to authenticate message (bytes)
SECRET = b'mydeepsecret'

_HMAC_CHECK = False

def check_hmac(request, secret):
    data = request.get_data()
    hmac_tester = hmac.HMAC(b'mydeepsecret', data, hashlib.sha1)
    if not 'X-Hub-Signature' in request.headers:
        raise ValueError('X-Hub-Signature is mandatory on this WebService')
    if request.headers['X-Hub-Signature'] == 'sha1='+hmac_tester.hexdigest():
        return True
    raise ValueError('Bad X-Hub-Signature signature')

@app.route('/github', methods=['POST'])
def notify():
    """Github main endpoint."""
    github_index = {
        'ping': ping,
        'issue_comment': issue_comment,
        'issues': issues
    }
    return handle_github_webhook(
        github_index,
        request.headers['X-GitHub-Event'],
        request.get_json()
    )

@app.route('/github/rest', methods=['POST'])
def rest_notify():
    """Github rest endpoint."""
    github_index = {
        'ping': ping,
        'push': push,
        'pull_request': rest_pull_request
    }
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

@lru_cache()
def robot_name():
    github_con = Github(os.environ["GH_TOKEN"])
    return github_con.get_user().login

def notify_github(github_index, event_type, json_body):
    if json_body['sender']['login'].lower() == robot_name().lower():
        return {'message': 'I don\'t talk to myself, I\'m not schizo'}
    if event_type in github_index:
        return github_index[event_type](json_body)
    return {'message': 'Not handled currently'}

def ping(body):
    return {'message': 'Moi aussi zen beaucoup'}

def issue_comment(body):
    if body["action"] in ["created", "edited"]:
        webhook_data = build_from_issue_comment(body)
        response = manage_comment(webhook_data)
        if response:
            return response
    return {'message': 'Nothing for me'}
    
def issues(body):
    if body["action"] in ["opened"]:
        webhook_data = build_from_issues(body)
        response = manage_comment(webhook_data)
        if response:
            return response
    return {'message': 'Nothing for me'}

def manage_comment(webhook_data):
    handler = LocalHandler()
    
    # Is someone talking to me:
    message = re.search("@{} (.*)".format(robot_name()), webhook_data.text, re.I)
    if message:
        command = message.group(1)
        try:
            response = handler.act_and_response(webhook_data, command)
        except Exception as err:
            response = traceback.format_exc()
        if response:
            return {'message': response}

def push(body):
    sdkid = request.args.get("sdkid")
    if not sdkid:
        return {'message': 'sdkid is a required query parameter'}
    sdkbase = request.args.get("sdkbase", "master")

    rest_api_branch_name = body["ref"][len("refs/heads/"):]
    if rest_api_branch_name == "master":
        return {'message': 'Webhook disabled for RestAPI master'}

    gh_token = os.environ["GH_TOKEN"]
    github_con = Github(gh_token)
    restapi_git_id = body['repository']['full_name']
    repo = github_con.get_repo(restapi_git_id)

    commit_obj = repo.get_commit(body["after"])
    generate_sdk_from_commit(
        commit_obj,
        "restapi_auto_"+rest_api_branch_name,
        restapi_git_id,
        sdkid,
        None, # I don't know if the origin branch comes from "master", assume it.
        sdkbase
    )
    return {'message': 'No return for this endpoint'}

def rest_pull_request(body):
    sdkid = request.args.get("sdkid")
    if not sdkid:
        return {'message': 'sdkid is a required query parameter'}
    sdkbase = request.args.get("sdkbase", "master")

    _LOGGER.info("Received PR action %s", body["action"])
    _QUEUE.put((body, sdkid, sdkbase))
    _LOGGER.info("Received action has been queued. Queue size: %d", _QUEUE.qsize())

    return {'message': 'Current queue size: {}'.format(_QUEUE.qsize())}

def rest_handle_action(body, sdkid, sdkbase):
    """First method in the thread.
    """
    _LOGGER.info("Rest handle action")
    gh_token = os.environ["GH_TOKEN"]
    github_con = Github(gh_token)

    sdk_pr_target_repo = github_con.get_repo(sdkid)

    restapi_git_id = body['repository']['full_name']
    restapi_repo = github_con.get_repo(restapi_git_id)

    _LOGGER.info("Received PR action %s", body["action"])
    if body["action"] in ["opened", "reopened"]:
        return rest_pull_open(body, github_con, restapi_repo, sdk_pr_target_repo, sdkbase)
    if body["action"] == "closed":
        return rest_pull_close(body, github_con, restapi_repo, sdk_pr_target_repo, sdkbase)
    if body["action"] == "synchronize": # push to a PR from a fork
        return rest_pull_sync(body, github_con, restapi_repo, sdk_pr_target_repo, sdkbase)    

def rest_pull_open(body, github_con, restapi_repo, sdk_pr_target_repo, sdk_default_base="master"):

    rest_basebranch = body["pull_request"]["base"]["ref"]
    dest_branch = body["pull_request"]["head"]["ref"]
    origin_repo = body["pull_request"]["head"]["repo"]["full_name"]

    if rest_basebranch == "master":
        sdk_base = sdk_default_base
        sdk_checkout_base = None
    else:
        sdk_base = "restapi_auto_" + rest_basebranch
        sdk_checkout_base = sdk_base

    rest_pr = restapi_repo.get_pull(body["number"])

    if origin_repo != restapi_repo.full_name:
        _LOGGER.info("This comes from a fork, I need generation first, since targetted branch does not exist")
        fork_repo = github_con.get_repo(origin_repo)
        fork_owner = fork_repo.owner.login
        commit_obj = fork_repo.get_commit(body["pull_request"]["head"]["sha"])
        subbranch_name_part = fork_owner+"_"+dest_branch
        sdk_dest_branch = "restapi_auto_" + subbranch_name_part
        generate_sdk_from_commit(
            commit_obj,
            sdk_dest_branch,
            origin_repo,
            sdk_pr_target_repo.full_name,
            sdk_checkout_base,
            sdk_default_base
        )
    else:
        sdk_dest_branch = "restapi_auto_" + dest_branch

    try:
        github_pr = sdk_pr_target_repo.create_pull(
            title='Automatic PR of {} into {}'.format(sdk_dest_branch, sdk_base),
            body="Created to sync {}".format(rest_pr.html_url),
            head=sdk_dest_branch,
            base=sdk_base
        )
        sdk_pr_as_issue = sdk_pr_target_repo.get_issue(github_pr.number)
        sdk_pr_as_issue.add_to_labels(get_or_create_label(sdk_pr_target_repo, SwaggerToSdkLabels.in_progress))
    except GithubException as err:
        if err.status == 422 and err.data['errors'][0].get('message', '').startswith('A pull request already exists'):
            _LOGGER.info('PR already exists, it was a commit on an open PR')
            sdk_pr = list(sdk_pr_target_repo.get_pulls(
                head=sdk_pr_target_repo.owner.login+":"+sdk_dest_branch,
                base=sdk_base
            ))[0]
            sdk_pr_as_issue = sdk_pr_target_repo.get_issue(sdk_pr.number)
            sdk_pr_as_issue.add_to_labels(get_or_create_label(sdk_pr_target_repo, SwaggerToSdkLabels.in_progress))
            safe_remove_label(sdk_pr_as_issue, get_or_create_label(sdk_pr_target_repo, SwaggerToSdkLabels.refused))
            safe_remove_label(sdk_pr_as_issue, get_or_create_label(sdk_pr_target_repo, SwaggerToSdkLabels.merged))
            return {'message': 'PR already exists'}
        else:
            return {'message': err.data}
    except Exception as err:
        response = traceback.format_exc()
        return {'message': response}


class SwaggerToSdkLabels(Enum):
    merged = "RestPRMerged", "0e8a16"
    refused = "RestPRRefused", "b60205"
    in_progress = "RestPRInProgress", "fbca04"

def get_or_create_label(sdk_pr_target_repo, label_enum):
    try:
        return sdk_pr_target_repo.get_label(label_enum.value[0])
    except UnknownObjectException:
        return sdk_pr_target_repo.create_label(*label_enum.value)
    
def safe_remove_label(issue, label):
    """Remove a label, does not fail if label was not there.
    """
    try:
        issue.remove_from_labels(label)
    except GithubException:
        pass

def rest_pull_close(body, github_con, restapi_repo, sdk_pr_target_repo, sdk_default_base="master"):
    _LOGGER.info("Received a PR closed event")
    sdkid = sdk_pr_target_repo.full_name
    rest_pr = restapi_repo.get_pull(body["number"])

    # What was "head" name
    origin_repo = body["pull_request"]["head"]["repo"]["full_name"]
    dest_branch = body["pull_request"]["head"]["ref"]
    if origin_repo != restapi_repo.full_name: # This PR comes from a fork
        fork_repo = github_con.get_repo(origin_repo)
        fork_owner = fork_repo.owner.login
        subbranch_name_part = fork_owner+"_"+dest_branch
        sdk_dest_branch = "restapi_auto_" + subbranch_name_part
    else:
        sdk_dest_branch = "restapi_auto_" + dest_branch
    _LOGGER.info("SDK head branch should be %s", sdk_dest_branch)
    full_head = sdk_pr_target_repo.owner.login+":"+sdk_dest_branch
    _LOGGER.info("Will filter with %s", full_head)

    # What was "base"
    rest_basebranch = body["pull_request"]["base"]["ref"]
    sdk_base = sdk_default_base if rest_basebranch == "master" else "restapi_auto_" + rest_basebranch
    _LOGGER.info("SDK base branch should be %s", sdk_base)

    sdk_prs = list(sdk_pr_target_repo.get_pulls(
        head=full_head,
        base=sdk_base
    ))
    if not sdk_prs:
        rest_pr.create_issue_comment("Was unable to find SDK {} PR for this closed PR.".format(sdkid))
    elif len(sdk_prs) == 1:
        sdk_pr = sdk_prs[0]
        sdk_pr_as_issue = sdk_pr_target_repo.get_issue(sdk_pr.number)
        safe_remove_label(sdk_pr_as_issue, get_or_create_label(sdk_pr_target_repo, SwaggerToSdkLabels.in_progress))
        try:
            if body["pull_request"]["merged"]:
                sdk_pr_as_issue.add_to_labels(get_or_create_label(sdk_pr_target_repo, SwaggerToSdkLabels.merged))
            else:
                sdk_pr_as_issue.add_to_labels(get_or_create_label(sdk_pr_target_repo, SwaggerToSdkLabels.refused))
        except GithubException:
            sdk_pr.create_issue_comment("Cannot set labels. Initial PR has been closed with merged status: {}".format(body["pull_request"]["merged"]))
    else:
        # Should be impossible, create_pull would have sent a 422
        pr_list = "\n".join(["- {}".format(pr.html_url) for pr in sdk_prs])
        rest_pr.create_issue_comment("We found several SDK {} PRs and didn't notify closing event.\n{}".format(sdkid, pr_list))

def rest_pull_sync(body, github_con, restapi_repo, sdk_pr_target_repo, sdk_default_base="master"):

    if body["before"] == body["after"]:
        return {'message': 'No commit id change'}

    # What was "head" name
    origin_repo = body["pull_request"]["head"]["repo"]["full_name"]

    if origin_repo == restapi_repo.full_name:
        _LOGGER.info("This will be handled by 'push' event on the branch")

    dest_branch = body["pull_request"]["head"]["ref"]
    fork_repo = github_con.get_repo(origin_repo)
    fork_owner = fork_repo.owner.login
    commit_obj = fork_repo.get_commit(body["pull_request"]["head"]["sha"])
    subbranch_name_part = fork_owner+"_"+dest_branch
    generate_sdk_from_commit(
        commit_obj,
        "restapi_auto_"+subbranch_name_part,
        origin_repo,
        sdk_pr_target_repo.full_name,
        None, # I don't know if the origin branch comes from "master", assume it.
        sdk_default_base
    )

    return {'message': 'No return for this endpoint'}

def consume():
    """Consume action and block if there is not.
    """
    while True:
        body, sdkid, sdkbase = _QUEUE.get()
        try:
            rest_handle_action(body, sdkid, sdkbase)
        except Exception as err:
            _LOGGER.critical("Worked thread issue:\n%s", traceback.format_exc())
    _LOGGER.info("End of WorkerThread")

_WORKER_THREAD = Thread(
    target=consume,
    name="WorkerThread"
)
_WORKER_THREAD.start()
