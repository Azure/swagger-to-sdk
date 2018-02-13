from collections import namedtuple
from contextlib import contextmanager
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
    get_swagger_project_files_in_git_object
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
from .bot_framework import (
    order
)

_LOGGER = logging.getLogger(__name__)


class GithubHandler:
    def __init__(self):
        # I need a token to do PR. Nothing to do with the bot.
        self.gh_token = os.environ["GH_TOKEN"]

    @order
    def rebase(self, issue, branch=None):
        if not issue.pull_request:
            return "Rebase is just supported in PR for now"
        
        pr = issue.repository.get_pull(issue.number)

        branch_name = pr.head.ref
        branched_sdk_id = pr.head.repo.full_name+'@'+branch_name

        upstream_url = 'https://github.com/{}.git'.format(pr.base.repo.full_name)
        upstream_base = pr.base.ref if not branch else branch

        with tempfile.TemporaryDirectory() as temp_dir, \
                manage_git_folder(self.gh_token, Path(temp_dir) / Path("sdk"), branched_sdk_id) as sdk_folder:

            sdk_repo = Repo(str(sdk_folder))
            configure_user(self.gh_token, sdk_repo)

            upstream = sdk_repo.create_remote('upstream', url=upstream_url)
            upstream.fetch()

            msg = sdk_repo.git.rebase('upstream/{}'.format(upstream_base))
            _LOGGER.debug(msg)
            msg = sdk_repo.git.push(force=True)
            _LOGGER.debug(msg)

            return "Rebase done and pushed to the branch"

    # @order
    def generate(self, issue, readme_parameter):
        # Do a start comment
        new_comment = issue.create_comment("Working on generating this for you!!!")

        # Clone SDK repo
        sdk_git_id = issue.repository.full_name
        pr_repo_id = sdk_git_id
        base_branch_name = "master"

        with tempfile.TemporaryDirectory() as temp_dir, \
                manage_git_folder(self.gh_token, temp_dir + "/sdk", sdk_git_id) as sdk_folder:

            sdk_conf = build_sdk(readme_parameter, sdk_folder)
            branch_name = list(sdk_conf.keys()).pop()

            new_comment.edit("Generated! Let's see if there is something to PR.")

            sdk_repo = Repo(str(sdk_folder))
            configure_user(self.gh_token, sdk_repo)
            modification = do_commit(
                sdk_repo,
                "Generated from {}".format(issue.html_url),
                branch_name,
                ""
            )
            new_comment.delete()
            if modification:
                sdk_repo.git.push('origin', branch_name, set_upstream=True)
                pip_command = 'pip install "git+{}@{}#egg={}&subdirectory={}"'.format(
                    issue.repository.html_url,
                    branch_name,
                    sdk_conf[branch_name]["autorest_options"]["package-name"],
                    sdk_conf[branch_name]["autorest_options"]["package-name"]
                )
                local_command = 'pip install -e ./{}'.format(sdk_conf[branch_name]["autorest_options"]["package-name"])

                pr_body = """Generated from Issue: {}

You can install the new package of this PR for testing using the following command:
`{}`

If you have a local clone of this repo in the folder /home/git/repo, please checkout this branch and do:
`{}`
""".format(issue.html_url, pip_command, local_command)

                pr = do_pr(self.gh_token, sdk_git_id, pr_repo_id, branch_name, base_branch_name, pr_body)

                answer = """
Done! I created this branch and this PR:
- {}
- {}
""".format(branch_name, pr.html_url, pip_command)
                return answer
            else:
                return "Sorry, there is nothing to PR"

    @order
    def rebuild(self, issue, project_pattern):
        if not issue.pull_request:
            return "Rebuild is just supported in PR for now"
        sdkid = issue.repository.full_name
        pr = issue.repository.get_pull(issue.number)

        new_comment = issue.create_comment("Working on generating {} for you!!!".format(project_pattern))

        config_path = CONFIG_FILE
        message = "Rebuild by "+issue.html_url
        autorest_bin = None

        branch_name = pr.head.ref
        branched_sdk_id = pr.head.repo.full_name+'@'+branch_name

        if project_pattern.startswith("https://"):
            link = GithubLink.from_string(project_pattern)
            link = link.as_raw_link()  # Ensure this is a raw link.
            rest_api_id = link.gitid
            rest_api_branch = link.branch_or_commit
            token = link.token if link.token else self.gh_token
            path = link.path
        else:
            rest_api_id = "Azure/azure-rest-api-specs"
            rest_api_branch = "master"
            token = self.gh_token
            path = None  # Not such notion of path here, since it's inside SwaggerToSdk conf
        branched_rest_api_id = rest_api_id + "@" + rest_api_branch

        with tempfile.TemporaryDirectory() as temp_dir, \
                manage_git_folder(token, Path(temp_dir) / Path("rest"), branched_rest_api_id) as restapi_git_folder, \
                manage_git_folder(self.gh_token, Path(temp_dir) / Path("sdk"), branched_sdk_id) as sdk_folder:

            sdk_repo = Repo(str(sdk_folder))
            configure_user(self.gh_token, sdk_repo)

            config = read_config(sdk_repo.working_tree_dir, config_path)
            if path: # Assume this is a Readme path
                config["projects"] = {} # Wipe out everything
                build_swaggertosdk_conf_from_json_readme(path, sdkid, config, base_folder=restapi_git_folder)
                skip_callback = lambda x, y: False
            else:
                def skip_callback(project, local_conf):
                    del local_conf  # Unused
                    if not project.startswith(project_pattern):
                        return True
                    return False

            from swaggertosdk import SwaggerToSdkNewCLI
            SwaggerToSdkNewCLI.build_libraries(config, skip_callback, restapi_git_folder,
                                               sdk_repo, temp_dir, autorest_bin)
            new_comment.edit("End of generation, doing commit")
            commit_sha = do_commit(sdk_repo, message, branch_name, "")
            if commit_sha:
                new_comment.edit("Pushing")
                sdk_repo.git.push('origin', branch_name, set_upstream=True)
                new_comment.delete()
            else:
                new_comment.delete()
                return "Nothing to rebuild, this PR is up to date"

        _LOGGER.info("Build SDK finished and cleaned")
        return "Build SDK finished and cleaned"
