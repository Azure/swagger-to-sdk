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

        with exception_to_github(issue):
            response = self.comment_command(issue, command)
            new_comment = issue.create_comment(response)
            return 'Posted: {}'.format(new_comment.html_url)
        return "Got an exception, commented on the issue"

    def comment_command(self, issue, text):
        split_text = text.lower().split()
        if split_text[0] == "generate":
            return self.generate(issue, split_text[1])
        elif split_text[0] == "rebuild":
            return self.rebuild(issue, split_text[1])
        elif split_text[0] == "help":
            return self.help(issue)
        elif split_text[0] == "rebase":
            branch = split_text[1] if len(split_text) > 1 else None
            return self.rebase(issue, branch)
        else:
            return "I didn't understand your command:\n```bash\n{}\n```\nin this context, sorry :(".format(text)

    def help(self, issue):
        message = """This is what I can do:
- `help` : this help message
- `generate <raw github path to a readme>` : create a PR for this README
"""
        new_comment = issue.create_comment(message)

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


def generate_sdk_from_git_object(git_object, branch_name, restapi_git_id, sdk_git_id, base_branch_names, *, fallback_base_branch_name="master", sdk_tag=None):
    """Generate SDK from a commit or a PR object.
    
    git_object is the initial commit/PR from the RestAPI repo. restapi_git_id explains where to clone the repo.
    sdk_git_id explains where to push the commit.
    sdk_tag explains what is the tag used in the Readme for the swagger-to-sdk section. If not provided, use sdk_git_id.
    branch_name is the expected branch name in the SDK repo.
    - If this branch exists, use it.
    - If not, use the base branch to create that branch (base branch is where I intend to do my PR)
    - If base_branch_names is not provided, use fallback_base_branch_name as base
    - If this base branch is provided and does not exists, create this base branch first using fallback_base_branch_name (this one is required to exist)

    WARNING:
    This method might push to "branch_name" and "base_branch_name". No push will be made to "fallback_base_branch_name"
    """
    gh_token = os.environ["GH_TOKEN"]
    config_path = CONFIG_FILE
    message_template = DEFAULT_COMMIT_MESSAGE
    autorest_bin = None
    if sdk_tag is None:
        sdk_tag = sdk_git_id

    try:
        checkout_name = git_object.sha # Checkout the sha if commit obj
    except AttributeError:
        checkout_name = git_object.head.ref # Checkout the branch name if PR

    branched_rest_api_id = restapi_git_id+'@'+checkout_name
    branched_sdk_git_id = sdk_git_id+'@'+fallback_base_branch_name

    with tempfile.TemporaryDirectory() as temp_dir, \
            manage_git_folder(gh_token, Path(temp_dir) / Path("rest"), branched_rest_api_id) as restapi_git_folder, \
            manage_git_folder(gh_token, Path(temp_dir) / Path("sdk"), branched_sdk_git_id) as sdk_folder:

        swagger_files_in_commit = get_swagger_project_files_in_git_object(git_object, restapi_git_folder)
        _LOGGER.info("Files in PR: %s ", swagger_files_in_commit)

        # SDK part
        sdk_repo = Repo(str(sdk_folder))

        for base_branch in base_branch_names:
            _LOGGER.info('Checkout and create %s', base_branch)
            checkout_and_create_branch(sdk_repo, base_branch)

        _LOGGER.info('Try to checkout destination branch %s', branch_name)
        try:
            sdk_repo.git.checkout(branch_name)
            _LOGGER.info('The branch exists.')
        except GitCommandError:
            _LOGGER.info('Destination branch does not exists')
            # Will be created by do_commit

        configure_user(gh_token, sdk_repo)

        config = read_config(sdk_repo.working_tree_dir, config_path)
        global_conf = config["meta"]

        # Look for configuration in Readme
        _LOGGER.info('Extract conf from Readmes for target: %s', sdk_git_id)
        extract_conf_from_readmes(swagger_files_in_commit, restapi_git_folder, sdk_tag, config)
        _LOGGER.info('End of extraction')

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

        build_libraries(config, skip_callback, restapi_git_folder,
                        sdk_repo, temp_dir, autorest_bin)

        try:
            commit_for_sha = git_object.commit   # Commit
        except AttributeError:
            commit_for_sha = list(git_object.get_commits())[-1].commit  # PR
        message = message_template + "\n\n" + commit_for_sha.message
        commit_sha = do_commit(sdk_repo, message, branch_name, commit_for_sha.sha)
        if commit_sha:
            for base_branch in base_branch_names:
                sdk_repo.git.push('origin', base_branch, set_upstream=True)    
            sdk_repo.git.push('origin', branch_name, set_upstream=True)
            return "https://github.com/{}/commit/{}".format(sdk_git_id, commit_sha)
