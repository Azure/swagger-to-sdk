import argparse
import logging
from io import open
from pathlib import Path
import tempfile

from swaggertosdk.SwaggerToSdkNewCLI import *
from swaggertosdk.SwaggerToSdkCore import *

_LOGGER = logging.getLogger(__name__)

def generate(config_path, sdk_folder, project_pattern, readme, restapi_git_folder, autorest_bin=None):

    sdk_folder = Path(sdk_folder).expanduser()
    config = read_config(sdk_folder, config_path)

    global_conf = config["meta"]
    global_conf["autorest_options"] = solve_relative_path(global_conf.get("autorest_options", {}), sdk_folder)
    restapi_git_folder = Path(restapi_git_folder).expanduser()

    # Look for configuration in Readme
    if readme:
        swagger_files_in_pr = [Path(readme)]
    else:
        swagger_files_in_pr =  list(restapi_git_folder.glob('specification/**/readme.md'))
    extract_conf_from_readmes(None, swagger_files_in_pr, restapi_git_folder, "azure-sdk-for-go", config)

    with tempfile.TemporaryDirectory() as temp_dir:
        for project, local_conf in config["projects"].items():
            if project_pattern and not any(p in project for p in project_pattern):
                _LOGGER.info("Skip project %s", project)
                continue
            local_conf["autorest_options"] = solve_relative_path(local_conf.get("autorest_options", {}), sdk_folder)

            markdown_relative_path, optional_relative_paths = get_input_paths(global_conf, local_conf)

            _LOGGER.info(f"Markdown input: {markdown_relative_path}")
            _LOGGER.info(f"Optional inputs: {optional_relative_paths}")

            absolute_markdown_path = None
            if markdown_relative_path:
                absolute_markdown_path = Path(restapi_git_folder, markdown_relative_path).resolve()
            if optional_relative_paths:
                local_conf.setdefault('autorest_options', {})['input-file'] = [
                    Path(restapi_git_folder, input_path).resolve()
                    for input_path
                    in optional_relative_paths
                ]

            build_project(
                temp_dir,
                project,
                absolute_markdown_path,
                sdk_folder,
                global_conf,
                local_conf,
                autorest_bin
            )


def generate_main():
    """Main method"""

    parser = argparse.ArgumentParser(
        description='Build SDK using Autorest, offline version.',
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--rest-folder', '-r',
                        dest='restapi_git_folder', default='.',
                        help='Rest API git folder. [default: %(default)s]')
    parser.add_argument('--project', '-p',
                        dest='project', action='append',
                        help='Select a specific project. Do all by default. You can use a substring for several projects.')
    parser.add_argument('--readme', '-m',
                        dest='readme',
                        help='Select a specific readme. Must be a path')
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

    parser.add_argument('sdk_folder',
                        help='A Python SDK folder.')

    args = parser.parse_args()
    main_logger = logging.getLogger()
    if args.verbose or args.debug:
        logging.basicConfig()
        main_logger.setLevel(logging.DEBUG if args.debug else logging.INFO)

    generate(args.config_path,
             args.sdk_folder,
             args.project,
             args.readme,
             args.restapi_git_folder,
             args.autorest_bin)

if __name__ == "__main__":
    generate_main()
