from collections import namedtuple
from contextlib import contextmanager
from functools import lru_cache
import logging
import os
import re
from pathlib import Path
import tempfile
import traceback

from github import Github
from git import Repo, GitCommandError

from swaggertosdk.build_sdk import generate as build_sdk
from swaggertosdk.SwaggerToSdkCore import (
    CONFIG_FILE,
    read_config,
    DEFAULT_COMMIT_MESSAGE,
    get_input_paths,
    extract_conf_from_readmes,
    build_swaggertosdk_conf_from_json_readme,
    get_readme_files_from_git_objects
)
from swaggertosdk.SwaggerToSdkNewCLI import build_libraries
from swaggertosdk.git_tools import (
    checkout_and_create_branch,
    checkout_create_push_branch,
    do_commit,
)
from swaggertosdk.github_tools import (
    configure_user,
    exception_to_github,
    manage_git_folder,
    do_pr,
    create_comment,
    GithubLink
)

_LOGGER = logging.getLogger(__name__)


def order(function):
    function.bot_order = True
    return function

WebhookMetadata = namedtuple(
    'WebhookMetadata',
    ['repo', 'issue', 'text']
)

def build_from_issue_comment(gh_token, body):
    """Create a WebhookMetadata from a comment added to an issue.
    """
    if body["action"] in ["created", "edited"]:
        gh_token = os.environ["GH_TOKEN"]
        github_con = Github(gh_token)
        repo = github_con.get_repo(body['repository']['full_name'])
        issue = repo.get_issue(body['issue']['number'])
        text = body['comment']['body']
        return WebhookMetadata(repo, issue, text)

def build_from_issues(gh_token, body):
    """Create a WebhookMetadata from an opening issue text.
    """
    if body["action"] in ["opened"]:
        github_con = Github(gh_token)
        repo = github_con.get_repo(body['repository']['full_name'])
        issue = repo.get_issue(body['issue']['number'])
        text = body['issue']['body']
        return WebhookMetadata(repo, issue, text)

@lru_cache()
def robot_name_from_env_variable():
    github_con = Github(os.environ["GH_TOKEN"])
    return github_con.get_user().login


class BotHandler:
    def __init__(self, handler, robot_name=None, gh_token=None):
        self.handler = handler
        self.gh_token = gh_token or os.environ["GH_TOKEN"]
        self.robot_name = robot_name or robot_name_from_env_variable()

    def _is_myself(self, body):
        return body['sender']['login'].lower() == self.robot_name.lower()

    def issue_comment(self, body):
        if self._is_myself(body):
            return {'message': 'I don\'t talk to myself, I\'m not schizo'}
        webhook_data = build_from_issue_comment(self.gh_token, body)
        return self.manage_comment(webhook_data)
        
    def issues(self, body):
        if self._is_myself(body):
            return {'message': 'I don\'t talk to myself, I\'m not schizo'}
        webhook_data = build_from_issues(self.gh_token, body)
        return self.manage_comment(webhook_data)

    def orders(self):
        """Return method tagged "order" in the handler.
        """
        return [order_cmd for order_cmd in dir(self.handler) if getattr(getattr(self.handler, order_cmd), "bot_order", False)]

    def manage_comment(self, webhook_data):
        if webhook_data is None:
            return {'message': 'Nothing for me'}
        # Is someone talking to me:
        message = re.search("@{} (.*)".format(self.robot_name), webhook_data.text, re.I)
        response = None
        if message:
            command = message.group(1)
            split_text = command.lower().split()
            order = split_text.pop(0)
            if order == "help":
                response = self.help_order(webhook_data.issue)
            elif order in self.orders():
                with exception_to_github(webhook_data.issue):  # Should do nothing, if handler is managing error correctly
                    response = getattr(self.handler, order)(webhook_data.issue, *split_text)
            else:
                response = "I didn't understand your command:\n```bash\n{}\n```\nin this context, sorry :(".format(command)
            if response:
                webhook_data.issue.create_comment(response)
                return {'message': response}
        return {'message': 'Nothing for me or exception'}

    def help_order(self, issue):
        orders = ["This is what I can do:"]
        for order in self.orders():
            orders.append("- `{}`".format(order))
        orders.append("- `help` : this help message")
        return "\n".join(orders)
