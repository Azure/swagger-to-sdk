import argparse
import os
import logging

from .SwaggerToSdkCore import *

_LOGGER = logging.getLogger(__name__)


def generate_sdk(gh_token, config_path, project_pattern, restapi_git_folder,
         sdk_git_id, pr_repo_id, message_template, base_branch_name, branch_name,
         autorest_bin=None):
    """Main method of the the file"""
    sdk_git_id = get_full_sdk_id(gh_token, sdk_git_id)

    with tempfile.TemporaryDirectory() as temp_dir, \
            manage_sdk_folder(gh_token, temp_dir, sdk_git_id) as sdk_folder:

        sdk_repo = Repo(sdk_folder)
        if gh_token:
            branch_name = compute_branch_name(branch_name, gh_token)

        _LOGGER.info('Destination branch for generated code is %s', branch_name)
        try:
            _LOGGER.info('Try to checkout the destination branch if it already exists')
            sdk_repo.git.checkout(branch_name)
        except GitCommandError:
            _LOGGER.info('Destination branch does not exists')
            sdk_repo.git.checkout(base_branch_name)

        if gh_token:
            _LOGGER.info('I have a token, try to sync fork')
            configure_user(gh_token, sdk_repo)
            sync_fork(gh_token, sdk_git_id, sdk_repo)

        config = read_config(sdk_repo.working_tree_dir, config_path)

        global_conf = config["meta"]
        conf_version = global_conf["version"]
        initial_pr = get_initial_pr(gh_token)

        if conf_version == "0.1.0":
            import SwaggerToSdkLegacy
            SwaggerToSdkLegacy.build_libraries(gh_token, config, project_pattern, restapi_git_folder,
                sdk_repo, temp_dir, initial_pr, autorest_bin)
        elif conf_version == "0.2.0":
            import SwaggerToSdkNewCLI
            SwaggerToSdkNewCLI.build_libraries(gh_token, config, project_pattern, restapi_git_folder,
                sdk_repo, temp_dir, initial_pr, autorest_bin)
        else:
            raise ValueError(f"Unsupported version {conf_version}")

        if gh_token:
            hexsha = get_swagger_hexsha(restapi_git_folder)
            if do_commit(sdk_repo, message_template, branch_name, hexsha):
                sdk_repo.git.push('origin', branch_name, set_upstream=True)
                if pr_repo_id:
                    do_pr(gh_token, sdk_git_id, pr_repo_id, branch_name, base_branch_name)
            else:
                add_comment_to_initial_pr(gh_token, "No modification for {}".format(sdk_git_id))
        else:
            _LOGGER.warning('Skipping commit creation since no token is provided')

    _LOGGER.info("Build SDK finished and cleaned")


def main():
    """Main method"""
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
                        help='Select a specific project. Do all by default. You can use a substring for several projects.')
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

    if 'GH_TOKEN' not in os.environ:
        gh_token = None
    else:
        gh_token = os.environ['GH_TOKEN']

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
                 args.autorest_bin)
