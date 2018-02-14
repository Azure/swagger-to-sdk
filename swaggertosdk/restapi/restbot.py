import os
import logging

from .bot_framework import order

_LOGGER = logging.getLogger(__name__)

class RestAPIRepoHandler:
    def __init__(self, repotag):
        self.gh_token = os.environ["GH_TOKEN"]
        self.repotag = repotag

    @order
    def rebuild(self, issue, repotag=None):
        if not issue.pull_request:
            return "Rebuild makes no sense if not a PR"
        if repotag and self.repotag != repotag:
            _LOGGER.info("Skipping rebuild from bot, since repotag doesn't match: {} {}".format(self.repotag, repotag))
            return # Do NOT return a string, I don't want to talk in the PR

        pr = issue.repository.get_pull(issue.number)

        # Consider this as a "sync" event
