"""Main file for Travis testing."""
import argparse
import logging
from pathlib import Path
import tempfile
import sys

from git import Repo

from .SwaggerToSdkCore import (
    CONFIG_FILE,
    read_config,
    extract_conf_from_readmes,
    get_input_paths,
    get_readme_files_from_file_list
)
from .github_tools import (
    manage_git_folder,
)
from .git_tools import (
    get_files_in_commit
)

_LOGGER = logging.getLogger(__name__)


def generate_sdk(config_path,
                 sdk_git_id, base_branch_name,
                 autorest_bin=None):
    """Main method of the the file"""

    # On Travis, local folder is restapi git folder
    restapi_git_folder = '.'

    # No token is provided to clone SDK. Do NOT try to clone a private it will fail.
    with tempfile.TemporaryDirectory() as temp_dir, \
            manage_git_folder(None, Path(temp_dir) / Path("sdk"), sdk_git_id+'@'+base_branch_name) as sdk_folder:

        sdk_repo = Repo(str(sdk_folder))

        config = read_config(sdk_repo.working_tree_dir, config_path)

        global_conf = config["meta"]

        swagger_files_in_pr = get_files_in_commit(restapi_git_folder)
        _LOGGER.info("Files in PR: %s ", swagger_files_in_pr)
        swagger_files_in_pr = get_readme_files_from_file_list(swagger_files_in_pr, restapi_git_folder)
        _LOGGER.info("Readmes in PR: %s ", swagger_files_in_pr)

        # Look for configuration in Readme
        extract_conf_from_readmes(swagger_files_in_pr, restapi_git_folder, sdk_git_id, config)

        def skip_callback(project, local_conf):
            if not swagger_files_in_pr:
                return True # Travis with no files found, always skip

            markdown_relative_path, optional_relative_paths = get_input_paths(global_conf, local_conf)

            if swagger_files_in_pr and not (
                    markdown_relative_path in swagger_files_in_pr or
                    any(input_file in swagger_files_in_pr for input_file in optional_relative_paths)):
                _LOGGER.info(f"In project {project} no files involved in this PR")
                return True
            return False

        from . import SwaggerToSdkNewCLI
        SwaggerToSdkNewCLI.build_libraries(config, skip_callback, restapi_git_folder,
                                           sdk_repo, temp_dir, autorest_bin)

    _LOGGER.info("Build SDK finished and cleaned")


def main(argv):
    """Main method"""

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

    parser = argparse.ArgumentParser(
        description='Travis entry point of SwaggerToSdk only.',
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--base-branch', '-o',
                        dest='base_branch', default='master',
                        help='The base branch to checkout. [default: %(default)s]')
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
                        help='The SDK Github id. Need to be a full ID org/repo.')

    args = parser.parse_args()

    main_logger = logging.getLogger()
    if args.verbose or args.debug:
        logging.basicConfig()
        main_logger.setLevel(logging.DEBUG if args.debug else logging.INFO)

    generate_sdk(args.config_path,
                 args.sdk_git_id,
                 args.base_branch,
                 args.autorest_bin)
