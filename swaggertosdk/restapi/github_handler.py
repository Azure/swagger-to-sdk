from collections import namedtuple
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
    manage_git_folder,
    checkout_and_create_branch,
    do_commit,
    do_pr,
    configure_user,
    CONFIG_FILE,
    read_config,
    DEFAULT_COMMIT_MESSAGE,
    get_input_paths,
    extract_conf_from_readmes,
    checkout_and_create_branch
)

_LOGGER = logging.getLogger(__name__)

WebhookMetadata = namedtuple(
    'WebhookMetadata',
    ['repo', 'issue', 'text']
)

def build_from_issue_comment(body):
    gh_token = os.environ["GH_TOKEN"]
    github_con = Github(gh_token)
    repo = github_con.get_repo(body['repository']['full_name'])
    issue = repo.get_issue(body['issue']['number'])
    text = body['comment']['body']
    return WebhookMetadata(repo, issue, text)

def build_from_issues(body):
    gh_token = os.environ["GH_TOKEN"]
    github_con = Github(gh_token)
    repo = github_con.get_repo(body['repository']['full_name'])
    issue = repo.get_issue(body['issue']['number'])
    text = body['issue']['body']
    return WebhookMetadata(repo, issue, text)

class GithubHandler:
    def __init__(self):
        self.gh_token = os.environ["GH_TOKEN"]

    def act_and_response(self, webhook_data, command):
        issue = webhook_data.issue

        try:
            response = self.comment_command(issue, command)
        except Exception as err:
            response = "Something's wrong:\n```python\n{}\n```\n".format(traceback.format_exc())

        new_comment = issue.create_comment(response)
        return 'Posted: {}'.format(new_comment.html_url)

    def comment_command(self, issue, text):
        split_text = text.lower().split()
        if split_text[0] == "generate":
            return self.generate(issue, split_text[1])
        elif split_text[0] == "rebuild":
            return self.rebuild(issue, split_text[1])
        elif split_text[0] == "help":
            return self.help(issue)
        else:
            return "I didn't understand your command:\n```bash\n{}\n```\nin this context, sorry :(".format(text)

    def help(self, issue):
        message = """This is what I can do:
- `help` : this help message
- `generate <raw github path to a readme>` : create a PR for this README
"""
        new_comment = issue.create_comment(message)

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

    def rebuild(self, issue, project_pattern):
        if not issue.pull_request:
            return "Rebuild is just supported in PR for now"
        pr = issue.repository.get_pull(issue.number)

        new_comment = issue.create_comment("Working on generating {} for you!!!".format(project_pattern))

        config_path = CONFIG_FILE
        message = "Rebuild by "+issue.html_url
        initial_pr = None # There is no initial PR to test for files
        autorest_bin = None

        branch_name = pr.head.ref

        rest_api_id = "Azure/azure-rest-api-specs" # current
        branched_sdk_id = pr.head.repo.full_name+'@'+branch_name

        with tempfile.TemporaryDirectory() as temp_dir, \
                manage_git_folder(self.gh_token, Path(temp_dir) / Path("rest"), rest_api_id) as restapi_git_folder, \
                manage_git_folder(self.gh_token, Path(temp_dir) / Path("sdk"), branched_sdk_id) as sdk_folder:

            sdk_repo = Repo(str(sdk_folder))
            configure_user(self.gh_token, sdk_repo)

            config = read_config(sdk_repo.working_tree_dir, config_path)

            def skip_callback(project, local_conf):
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


def generate_sdk_from_commit_safe(commit_obj, branch_name, restapi_git_id, sdkid, base_branch_name, fallback_base_branch_name="master"):
    try:
        response = generate_sdk_from_commit(commit_obj, branch_name, restapi_git_id, sdkid, base_branch_name, fallback_base_branch_name)
    except Exception as err:
        response = "Something's wrong:\n```python\n{}\n```\n".format(traceback.format_exc())

    new_comment = commit_obj.create_comment(response)
    return 'Posted: {}'.format(new_comment.html_url)    

def generate_sdk_from_commit(commit_obj, branch_name, restapi_git_id, sdk_git_id, base_branch_name, fallback_base_branch_name="master"):
    """Generate SDK from a commit.
    
    commit_obj is the initial commit_obj from the RestAPI repo. restapi_git_id explains where to clone the repo.
    sdk_git_id explains where to push the commit.
    branch_name is the expected branch name in the SDK repo.
    - If this branch exists, use it.
    - If not, use the base branch to create that branch (base branch is where I intend to do my PR)
    - If base_branch is not provided, use fallback_base_branch_name as base
    - If this base branch is provided and does not exists, create this base branch first using fallback_base_branch_name (this one is required to exist)

    WARNING:
    This method might push to "branch_name" and "base_branch_name". No push will be made to "fallback_base_branch_name"
    """
    gh_token = os.environ["GH_TOKEN"]
    config_path = CONFIG_FILE
    message_template = DEFAULT_COMMIT_MESSAGE
    autorest_bin = None

    branched_rest_api_id = restapi_git_id+'@'+commit_obj.sha
    branched_sdk_git_id = sdk_git_id+'@'+fallback_base_branch_name

    with tempfile.TemporaryDirectory() as temp_dir, \
            manage_git_folder(gh_token, Path(temp_dir) / Path("rest"), branched_rest_api_id) as restapi_git_folder, \
            manage_git_folder(gh_token, Path(temp_dir) / Path("sdk"), branched_sdk_git_id) as sdk_folder:

        sdk_repo = Repo(str(sdk_folder))
        _LOGGER.info('Destination branch for generated code is %s', branch_name)
        try:
            _LOGGER.info('Try to checkout the destination branch if it already exists')
            sdk_repo.git.checkout(branch_name)
        except GitCommandError:
            _LOGGER.info('Destination branch does not exists')
            if base_branch_name is not None:
                _LOGGER.info('Try to checkout base branch {} '.format(base_branch_name))
                try:
                    sdk_repo.git.checkout(base_branch_name)
                except GitCommandError:
                    _LOGGER.info('Base branch does not exists, create it from {}'.format(fallback_base_branch_name))
                    checkout_and_create_branch(sdk_repo, base_branch_name)
                    sdk_repo.git.push('origin', base_branch_name, set_upstream=True)

        configure_user(gh_token, sdk_repo)

        config = read_config(sdk_repo.working_tree_dir, config_path)
        global_conf = config["meta"]

        from swaggertosdk import SwaggerToSdkNewCLI
        from swaggertosdk import SwaggerToSdkCore
        swagger_files_in_commit = SwaggerToSdkCore.get_swagger_project_files_in_pr(commit_obj, restapi_git_folder)
        _LOGGER.info("Files in PR: %s ", swagger_files_in_commit)

        # Look for configuration in Readme
        extract_conf_from_readmes(gh_token, swagger_files_in_commit, restapi_git_folder, sdk_git_id, config)

        def skip_callback(project, local_conf):
            if not swagger_files_in_commit:
                return True
            markdown_relative_path, optional_relative_paths = get_input_paths(global_conf, local_conf)
            if not (
                    markdown_relative_path in swagger_files_in_commit or
                    any(input_file in swagger_files_in_commit for input_file in optional_relative_paths)):
                _LOGGER.info(f"In project {project} no files involved in this commit")
                return True
            return False

        SwaggerToSdkNewCLI.build_libraries(config, skip_callback, restapi_git_folder,
                                           sdk_repo, temp_dir, autorest_bin)

        message = message_template + "\n\n" + commit_obj.commit.message
        commit_sha = do_commit(sdk_repo, message, branch_name, commit_obj.sha)
        if commit_sha:
            sdk_repo.git.push('origin', branch_name, set_upstream=True)
            commit_url = "https://github.com/{}/commit/{}".format(sdk_git_id, commit_sha)
            commit_obj.create_comment("Did a commit to SDK for Python:\n{}".format(commit_url))
        else:
            commit_obj.create_comment("This commit was treated and no generation was made for Python")

    _LOGGER.info("Build SDK finished and cleaned")
    return "Build SDK finished and cleaned"
        