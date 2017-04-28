import argparse
import logging
from pathlib import Path

from SwaggerToSdk import *

_LOGGER = logging.getLogger(__name__)

def generate(config_path, sdk_folder, project_pattern, restapi_git_folder, autorest_bin=None):

    config = read_config(sdk_folder, config_path)

    global_conf = config["meta"]
    language = global_conf["language"]

    with tempfile.TemporaryDirectory() as temp_dir:
        for project, local_conf in config["projects"].items():
            if project_pattern and not any(project.startswith(p) for p in project_pattern):
                _LOGGER.info("Skip project %s", project)
                continue

            relative_swagger_path = Path(local_conf['swagger'])

            _LOGGER.info("Working on %s", relative_swagger_path)
            dest = local_conf['output_dir']
            absolute_swagger_path = Path(restapi_git_folder, relative_swagger_path).resolve()

            if not absolute_swagger_path.is_file():
                err_msg = "Swagger file does not exist or is not readable: {}".format(
                    absolute_swagger_path)
                _LOGGER.critical(err_msg)
                raise ValueError(err_msg)

            absolute_generated_path = Path(temp_dir, relative_swagger_path.name)
            generate_code(language,
                          absolute_swagger_path, absolute_generated_path,
                          global_conf, local_conf,
                          autorest_bin)
            update(absolute_generated_path, sdk_folder, global_conf, local_conf)


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
             args.restapi_git_folder,
             args.autorest_bin)

if __name__ == "__main__":
    generate_main()
