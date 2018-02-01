import argparse
import os
import logging
import tempfile
from git import Repo, GitCommandError
from pathlib import Path
import sys

from .SwaggerToSdkCore import (
    is_travis,
    CONFIG_FILE,
    DEFAULT_BRANCH_NAME,
    DEFAULT_COMMIT_MESSAGE,
    DEFAULT_TRAVIS_BRANCH_NAME,
    DEFAULT_TRAVIS_PR_BRANCH_NAME,
    compute_branch_name,
    read_config,
    get_initial_pr,
    add_comment_to_initial_pr,
    compute_pr_comment_with_sdk_pr,
    get_swagger_project_files_in_git_object,
    get_commit_object_from_travis,
    extract_conf_from_readmes,
    get_input_paths,
)
from .git_tools import (
    do_commit,
    get_repo_hexsha,
)
from .github_tools import (
    do_pr,
    configure_user,
    sync_fork,
    manage_git_folder,
    get_full_sdk_id,
)

_LOGGER = logging.getLogger(__name__)


def generate_sdk(gh_token, config_path, project_pattern, restapi_git_id,
                 sdk_git_id, pr_repo_id, message_template, base_branch_name, branch_name,
                 autorest_bin=None, push=True):
    """Main method of the the file"""
    sdk_git_id = get_full_sdk_id(gh_token, sdk_git_id)

    with tempfile.TemporaryDirectory() as temp_dir, \
            manage_git_folder(gh_token, Path(temp_dir) / Path("rest"), restapi_git_id) as restapi_git_folder, \
            manage_git_folder(gh_token, Path(temp_dir) / Path("sdk"), sdk_git_id+'@'+base_branch_name) as sdk_folder:

        sdk_repo = Repo(str(sdk_folder))
        if gh_token:
            branch_name = compute_branch_name(branch_name, gh_token)

        if branch_name:
            _LOGGER.info('Destination branch for generated code is %s', branch_name)
            try:
                _LOGGER.info('Try to checkout the destination branch if it already exists')
                sdk_repo.git.checkout(branch_name)
            except GitCommandError:
                _LOGGER.info('Destination branch does not exists')

        if gh_token:
            _LOGGER.info('I have a token, try to sync fork')
            configure_user(gh_token, sdk_repo)
            sync_fork(gh_token, sdk_git_id, sdk_repo, push)

        config = read_config(sdk_repo.working_tree_dir, config_path)

        global_conf = config["meta"]
        conf_version = global_conf["version"]
        initial_git_trigger = get_initial_pr(gh_token)
        if not initial_git_trigger:
            initial_git_trigger = get_commit_object_from_travis(gh_token)

        swagger_files_in_pr = get_swagger_project_files_in_git_object(initial_git_trigger, restapi_git_folder) if initial_git_trigger else set()
        _LOGGER.info("Files in PR: %s ", swagger_files_in_pr)

        # Look for configuration in Readme
        extract_conf_from_readmes(swagger_files_in_pr, restapi_git_folder, sdk_git_id, config)

        def skip_callback(project, local_conf):
            if is_travis() and not swagger_files_in_pr:
                return True # Travis with no files found, always skip

            if project_pattern and not any(project.startswith(p) for p in project_pattern):
                return True

            markdown_relative_path, optional_relative_paths = get_input_paths(global_conf, local_conf)

            if swagger_files_in_pr and not (
                    markdown_relative_path in swagger_files_in_pr or
                    any(input_file in swagger_files_in_pr for input_file in optional_relative_paths)):
                _LOGGER.info(f"In project {project} no files involved in this PR")
                return True
            return False

        if conf_version == "0.1.0":
            raise ValueError("Format 0.1.0 is not supported anymore")
        elif conf_version == "0.2.0":
            from . import SwaggerToSdkNewCLI
            SwaggerToSdkNewCLI.build_libraries(config, skip_callback, restapi_git_folder,
                                               sdk_repo, temp_dir, autorest_bin)
        else:
            raise ValueError(f"Unsupported version {conf_version}")

        if gh_token and push:
            hexsha = get_repo_hexsha(restapi_git_folder)
            if do_commit(sdk_repo, message_template, branch_name, hexsha):
                sdk_repo.git.push('origin', branch_name, set_upstream=True)
                if pr_repo_id:
                    pr_body = "Generated from PR: {}".format(initial_git_trigger.html_url)
                    github_pr = do_pr(gh_token, sdk_git_id, pr_repo_id, branch_name, base_branch_name, pr_body)
                    comment = compute_pr_comment_with_sdk_pr(github_pr.html_url, sdk_git_id, branch_name)
                    add_comment_to_initial_pr(gh_token, comment)
        else:
            _LOGGER.warning('Skipping commit creation since no token is provided or no push')

    _LOGGER.info("Build SDK finished and cleaned")


def main(argv):
    """Main method"""

    if 'GH_TOKEN' not in os.environ:
        gh_token = None
    else:
        gh_token = os.environ['GH_TOKEN']

    if "--rest-server" in argv:
        from .restapi import app
        log_level = logging.WARNING
        if "-v" in argv or "--verbose" in argv:
            log_level = logging.INFO
        if "--debug" in argv:
            log_level = logging.DEBUG

        main_logger = logging.getLogger()
        logging.basicConfig()
        main_logger.setLevel(log_level)

        app.run(debug=log_level == logging.DEBUG, host='0.0.0.0')
        sys.exit(0)

    epilog = "\n".join([
        'The script activates this additional behaviour if Travis is detected:',
        ' --branch is setted by default to "{}" if triggered by a PR, "{}" otherwise'.format(
            DEFAULT_TRAVIS_PR_BRANCH_NAME,
            DEFAULT_TRAVIS_BRANCH_NAME
        ),
        ' Only the files inside the PR are considered. If the PR is NOT detected, all files are used.'
    ])

    parser = argparse.ArgumentParser(
        description='Build SDK using Autorest and push to Github. The GH_TOKEN environment variable needs to be set to act on Github.',
        epilog=epilog,
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--rest-folder', '-r',
                        dest='restapi_git_folder', default='.',
                        help='Rest API git folder. [default: %(default)s]')
    parser.add_argument('--pr-repo-id',
                        dest='pr_repo_id', default=None,
                        help='PR repo id. If not provided, no PR is done')
    parser.add_argument('--message', '-m',
                        dest='message', default=DEFAULT_COMMIT_MESSAGE,
                        help='Force commit message. {hexsha} will be the current REST SHA1 [default: %(default)s]')
    parser.add_argument('--project', '-p',
                        dest='project', action='append',
                        help='Select a specific project. Do all by default in CLI mode, nothing in Travis mode. You can use a substring for several projects.')
    parser.add_argument('--base-branch', '-o',
                        dest='base_branch', default='master',
                        help='The base branch from where create the new branch and where to do the final PR. [default: %(default)s]')
    parser.add_argument('--branch', '-b',
                        dest='branch', default=None,
                        help='The SDK branch to commit. Default if not Travis: {}. If Travis is detected, see epilog for details'.format(DEFAULT_BRANCH_NAME))
    parser.add_argument('--config', '-c',
                        dest='config_path', default=CONFIG_FILE,
                        help='The JSON configuration format path [default: %(default)s]')
    parser.add_argument('--autorest',
                        dest='autorest_bin',
                        help='Force the Autorest to be executed. Must be a executable command.')
    parser.add_argument("--push",
                        dest="push", action="store_true",
                        help="Should this execution push or just read")
    parser.add_argument("-v", "--verbose",
                        dest="verbose", action="store_true",
                        help="Verbosity in INFO mode")
    parser.add_argument("--debug",
                        dest="debug", action="store_true",
                        help="Verbosity in DEBUG mode")

    parser.add_argument('sdk_git_id',
                        help='The SDK Github id. '\
                         'If a simple string, consider it belongs to the GH_TOKEN owner repo. '\
                         'Otherwise, you can use the syntax username/repoid')

    args = parser.parse_args()
    
    main_logger = logging.getLogger()
    if args.verbose or args.debug:
        logging.basicConfig()
        main_logger.setLevel(logging.DEBUG if args.debug else logging.INFO)

    generate_sdk(gh_token,
                 args.config_path,
                 args.project,
                 args.restapi_git_folder,
                 args.sdk_git_id,
                 args.pr_repo_id,
                 args.message,
                 args.base_branch,
                 args.branch,
                 args.autorest_bin,
                 args.push)
