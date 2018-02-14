import os
import logging

from github import Github

from .bot_framework import order
from .github_handler import rest_pr_management

_LOGGER = logging.getLogger(__name__)

class RestAPIRepoHandler:
    def __init__(self, sdkid, repotag, sdk_default_base):
        self.gh_token = os.environ["GH_TOKEN"]
        self.sdkid = sdkid
        self.repotag = repotag
        self.sdk_default_base = sdk_default_base

    @order
    def rebuild(self, issue, repotag=None):
        if not issue.pull_request:
            return "Rebuild makes no sense if not a PR"
        if repotag and self.repotag != repotag:
            _LOGGER.info("Skipping rebuild from bot, since repotag doesn't match: %s %s",
                         self.repotag,
                         repotag)
            return # Do NOT return a string, I don't want to talk in the PR

        rest_pr = issue.repository.get_pull(issue.number)
        github_con = Github(self.gh_token)
        sdk_repo = github_con.get_repo(self.sdkid)

        rest_pr_management(
            rest_pr,
            sdk_repo,
            repotag or self.repotag,
            self.sdk_default_base
        )
