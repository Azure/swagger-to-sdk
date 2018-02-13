import os
from enum import Enum
import hmac
import hashlib
import logging
from queue import Queue
import traceback
from threading import Thread

from flask import request, jsonify

from github import Github, GithubException, UnknownObjectException

from .bot_framework import (
    BotHandler
)
from .sdkbot import (
    GithubHandler
)
from .github_handler import (
    generate_sdk_from_git_object
)
from ..github_tools import (
    exception_to_github,
    DashboardCommentableObject,
    get_or_create_pull,
)
from ..SwaggerToSdkCore import (
    get_context_tag_from_git_object
)
from . import app

_LOGGER = logging.getLogger(__name__)
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
    github_index = {
        'ping': ping,
        'push': push,
        'pull_request': rest_pull_request
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
    if not sdkid:
        return {'message': 'sdkid is a required query parameter'}
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
    if not sdkid:
        return {'message': 'sdkid is a required query parameter'}
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

    restapi_git_id = body['repository']['full_name']
    restapi_repo = github_con.get_repo(restapi_git_id)
    rest_pr = restapi_repo.get_pull(body["number"])
    dashboard = DashboardCommentableObject(rest_pr, "# Automation for {}".format(sdk_tag))

    context_tags = list(get_context_tag_from_git_object(rest_pr))
    if len(context_tags) == 0:
        dashboard.create_comment("Unable to detect any generation context from this PR.")
        return
    context_tags_limit = 3
    if len(context_tags) > context_tags_limit:
        dashboard.create_comment("This PR contains more than {} context, SDK generation is not enabled. Contexts found:\n{}".format(
            context_tags_limit,
            "\n".join(["- {}".format(ctxt) for ctxt in context_tags])
        ))
        return

    _LOGGER.info("Received PR action %s", body["action"])
    with exception_to_github(dashboard, sdk_tag):
        if body["action"] in ["opened", "reopened"]:
            return rest_pull_open(body, github_con, restapi_repo, sdk_pr_target_repo, context_tags, sdkbase, sdk_tag)
        if body["action"] == "closed":
            return rest_pull_close(body, github_con, restapi_repo, sdk_pr_target_repo, context_tags, sdkbase, sdk_tag)
        if body["action"] == "synchronize": # push to a PR from a fork
            return rest_pull_sync(body, github_con, restapi_repo, sdk_pr_target_repo, context_tags, sdkbase, sdk_tag)

def rest_pull_open(body, github_con, restapi_repo, sdk_pr_target_repo, context_tags, sdk_default_base="master", sdk_tag=None):

    rest_basebranch = body["pull_request"]["base"]["ref"]
    origin_repo = body["pull_request"]["head"]["repo"]["full_name"]
    pr_title = body["pull_request"]["title"]
    pr_number = body["number"]

    sdk_pr_model = SdkPRModel.from_pr_webhook(body, github_con, restapi_repo, sdk_pr_target_repo, sdk_default_base)
    sdk_base = sdk_pr_model.base_branch_name
    sdk_dest_branch = sdk_pr_model.head_branch_name

    sdk_checkout_bases = [] if rest_basebranch == "master" else [sdk_base]
    context_branch = None
    if len(context_tags) == 1:
        context_branch = "restapi_auto_"+context_tags[0]
        sdk_checkout_bases.insert(0, context_branch)

    rest_pr = restapi_repo.get_pull(pr_number)
    dashboard = DashboardCommentableObject(rest_pr, "# Automation for {}".format(sdk_tag))

    if origin_repo != restapi_repo.full_name:
        # Let's always take the PR files list, and not the one from the commit.
        # If the PR contains a merge commit, we might generate the entire world
        # even if the global PR itself is not impacted by this merge commit.
        _LOGGER.info("This comes from a fork, I need generation first, since targetted branch does not exist")
        commit_url = generate_sdk_from_git_object(
            rest_pr,
            sdk_dest_branch,
            origin_repo,
            sdk_pr_target_repo.full_name,
            sdk_checkout_bases,
            fallback_base_branch_name=sdk_default_base,
            sdk_tag=sdk_tag
        )
        if commit_url:
            dashboard.create_comment("Did a commit to {}:\n{}".format(sdk_tag, commit_url))
        else:
            dashboard.create_comment("This commit was treated and no generation was made for {}".format(sdk_tag))
            return
    else:
        context_branch = None

    # Let it raise at worst
    github_pr = get_or_create_pull(
        sdk_pr_target_repo,
        title='[AutoPR {}] {}'.format("/".join(context_tags), pr_title),
        body="Created to sync {}".format(rest_pr.html_url),
        head=sdk_pr_target_repo.owner.login+":"+sdk_dest_branch,
        base=context_branch or sdk_base
    )
    dashboard.create_comment("A PR has been created for you:\n{}".format(github_pr.html_url))

    try: # Try to label it. Catch, consider failing not critical.
        sdk_pr_as_issue = sdk_pr_target_repo.get_issue(github_pr.number)
        sdk_pr_as_issue.add_to_labels(get_or_create_label(sdk_pr_target_repo, SwaggerToSdkLabels.in_progress))
        safe_remove_label(sdk_pr_as_issue, get_or_create_label(sdk_pr_target_repo, SwaggerToSdkLabels.refused))
        safe_remove_label(sdk_pr_as_issue, get_or_create_label(sdk_pr_target_repo, SwaggerToSdkLabels.merged))
    except Exception as err:
        response = traceback.format_exc()
        _LOGGER.info("Unable to label PR %s:\n%s", github_pr.number, response)
        return {'message': response}

    if context_branch:
        create_context_pr(sdk_pr_target_repo, context_tags, sdk_base)

def create_context_pr(sdk_pr_target_repo, context_tags, sdk_base):
    context_branch = "restapi_auto_"+context_tags[0]
    context_pr = None
    try:
        context_pr = get_or_create_pull(
            sdk_pr_target_repo,
            title='[AutoPR] {}'.format("/".join(context_tags)),
            body="Created to accumulate context: {}".format(context_tags[0]),
            head=sdk_pr_target_repo.owner.login+":"+context_branch,
            base=sdk_base
        )
        context_pr_as_issue = sdk_pr_target_repo.get_issue(context_pr.number)
        context_pr_as_issue.add_to_labels(get_or_create_label(sdk_pr_target_repo, SwaggerToSdkLabels.service_pr))
    except Exception as err:
        # Accept failure, likely this is
        # - context branch is same as master (not critical)
        # - impossible to label. The PR is created, that's the most important.
        response = traceback.format_exc()
        _LOGGER.info("Unable to manage Context PR %s:\n%s", context_pr.number if context_pr else "", response)
        return {'message': response}

class SwaggerToSdkLabels(Enum):
    merged = "RestPRMerged", "0e8a16"
    refused = "RestPRRefused", "b60205"
    in_progress = "RestPRInProgress", "fbca04"
    service_pr = "ServicePR", "1d76db"

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

class SdkPRModel:
    def __init__(self, head_branch_name, base_branch_name):
        self.head_branch_name = head_branch_name
        self.base_branch_name = base_branch_name

    @classmethod
    def from_pr_webhook(cls, webhook_body, github_con, restapi_repo, sdk_pr_target_repo, sdk_default_base="master"):
        # What was "head" name
        origin_repo = webhook_body["pull_request"]["head"]["repo"]["full_name"]
        dest_branch = webhook_body["pull_request"]["head"]["ref"]
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
        rest_basebranch = webhook_body["pull_request"]["base"]["ref"]
        sdk_base = sdk_default_base if rest_basebranch == "master" else "restapi_auto_" + rest_basebranch
        _LOGGER.info("SDK base branch should be %s", sdk_base)

        return cls(
            head_branch_name=sdk_dest_branch,
            base_branch_name=sdk_base
        )

def rest_pull_close(body, github_con, restapi_repo, sdk_pr_target_repo, context_tags, sdk_default_base="master", sdk_tag=None):
    _LOGGER.info("Received a PR closed event")
    sdkid = sdk_pr_target_repo.full_name
    rest_pr = restapi_repo.get_pull(body["number"])

    sdk_pr_model = SdkPRModel.from_pr_webhook(body, github_con, restapi_repo, sdk_pr_target_repo, sdk_default_base)
    sdk_base = sdk_pr_model.base_branch_name

    context_branch = None
    if len(context_tags) == 1:
        context_branch = "restapi_auto_"+context_tags[0]

    sdk_prs = list(sdk_pr_target_repo.get_pulls(
        head=sdk_pr_target_repo.owner.login+":"+sdk_pr_model.head_branch_name,
        base=context_branch or sdk_pr_model.base_branch_name
    ))
    if not sdk_prs:
        # Didn't find it, it's probably because the bot wasn't there when it was created. Let's be smart and do it now.
        rest_pull_open(body, github_con, restapi_repo, sdk_pr_target_repo, context_tags, sdk_default_base, sdk_tag)
        # Look for it again now
        sdk_prs = list(sdk_pr_target_repo.get_pulls(
            head=sdk_pr_target_repo.owner.login+":"+sdk_pr_model.head_branch_name,
            base=context_branch or sdk_base
        ))

    if not sdk_prs:
        # Not possible in theory, but let's be sad in the PR comment
        dashboard = DashboardCommentableObject(rest_pr, "# Automation for {}".format(sdk_tag))
        dashboard.create_comment("Was unable to create SDK {} PR for this closed PR.".format(sdk_tag))
    elif len(sdk_prs) == 1:
        sdk_pr = sdk_prs[0]
        sdk_pr_as_issue = sdk_pr_target_repo.get_issue(sdk_pr.number)
        safe_remove_label(sdk_pr_as_issue, get_or_create_label(sdk_pr_target_repo, SwaggerToSdkLabels.in_progress))
        try:
            if body["pull_request"]["merged"]:
                sdk_pr_as_issue.add_to_labels(get_or_create_label(sdk_pr_target_repo, SwaggerToSdkLabels.merged))
                if context_branch and sdk_pr.mergeable:
                    # Merge context PR automatically
                    sdk_pr.merge(merge_method="squash")
            else:
                sdk_pr_as_issue.add_to_labels(get_or_create_label(sdk_pr_target_repo, SwaggerToSdkLabels.refused))
                sdk_pr.edit(state="closed")
        except GithubException:
            sdk_pr.create_issue_comment("Cannot set labels. Initial PR has been closed with merged status: {}".format(body["pull_request"]["merged"]))
        if context_branch:
            create_context_pr(sdk_pr_target_repo, context_tags, sdk_base)

    else:
        # Should be impossible, create_pull would have sent a 422
        pr_list = "\n".join(["- {}".format(pr.html_url) for pr in sdk_prs])
        _LOGGER.info("We found several SDK {} PRs and didn't notify closing event.\n{}".format(sdkid, pr_list))

def rest_pull_sync(body, github_con, restapi_repo, sdk_pr_target_repo, context_tags, sdk_default_base="master", sdk_tag=None):

    if body["before"] == body["after"]:
        return {'message': 'No commit id change'}

    origin_repo = body["pull_request"]["head"]["repo"]["full_name"]
    if origin_repo == restapi_repo.full_name:
        _LOGGER.info("This will be handled by 'push' event on the branch")
        return

    context_branch = None
    if len(context_tags) == 1:
        context_branch = "restapi_auto_"+context_tags[0]

    # Look for the SDK pr
    sdk_pr_model = SdkPRModel.from_pr_webhook(body, github_con, restapi_repo, sdk_pr_target_repo, sdk_default_base)
    sdk_prs = list(sdk_pr_target_repo.get_pulls(
        head=sdk_pr_target_repo.owner.login+":"+sdk_pr_model.head_branch_name,
        base=context_branch or sdk_pr_model.base_branch_name
    ))
    if not sdk_prs:
        # Didn't find it, let's consider this event as opening
        return rest_pull_open(body, github_con, restapi_repo, sdk_pr_target_repo, context_tags, sdk_default_base, sdk_tag)

    pr_number = body["number"]
    rest_pr = restapi_repo.get_pull(pr_number)
    dest_branch = body["pull_request"]["head"]["ref"]
    fork_repo = github_con.get_repo(origin_repo)
    fork_owner = fork_repo.owner.login
    subbranch_name_part = fork_owner+"_"+dest_branch
    generate_sdk_from_git_object(
        rest_pr,
        "restapi_auto_"+subbranch_name_part,
        origin_repo,
        sdk_pr_target_repo.full_name,
        [], # I don't know if the origin branch comes from "master", assume it.
        fallback_base_branch_name=sdk_default_base,
        sdk_tag=sdk_tag
    )
    dashboard = DashboardCommentableObject(rest_pr, "# Automation for {}".format(sdk_tag))
    # Do not comment on this commit, just push back the PR html url just in case last one was an exception
    dashboard.create_comment("A PR has been created for you:\n{}".format(sdk_prs[0].html_url))
    return {'message': 'No return for this endpoint'}

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
