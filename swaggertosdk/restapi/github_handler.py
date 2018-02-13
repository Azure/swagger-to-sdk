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
