import logging
import os
from pathlib import Path
import tempfile

from git import Repo

from swaggertosdk.SwaggerToSdkCore import (
    CONFIG_FILE,
    read_config,
    build_swaggertosdk_conf_from_json_readme,
)
from swaggertosdk.git_tools import (
    do_commit,
)
from swaggertosdk.github_tools import (
    configure_user,
    manage_git_folder,
    do_pr,
    GithubLink
)
from .bot_framework import (
    order
)

_LOGGER = logging.getLogger("swaggertosdk.restapi.sdkbot")


def pr_message_for_package(sdk_pr, package_name):
    git_path = '"git+{}@{}#egg={}&subdirectory={}"'.format(
        sdk_pr.head.repo.html_url,
        sdk_pr.head.ref,
        package_name,
        package_name
    )

    pip_install = 'pip install '+git_path
    pip_wheel = 'pip wheel --no-deps '+git_path

    pr_body = "You can install the package `{}` of this PR using the following command:\n\t`{}`".format(
        package_name,
        pip_install
    )

    pr_body += "\n\n"

    pr_body += "You can build a wheel to distribute for test using the following command:\n\t`{}`".format(
        pip_wheel
    )

    pr_body += "\n\n"
    pr_body += "If you have a local clone of this repository, you can also do:\n\n"
    pr_body += "- `git checkout {}`\n".format(sdk_pr.head.ref)
    pr_body += "- `pip install -e ./{}`\n".format(package_name)
    return pr_body


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
