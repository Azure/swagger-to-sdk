import argparse
import logging
import os

from swaggertosdk.python_sdk_tools import build_package_from_pr_number

_LOGGER = logging.getLogger(__name__)

def generate_main():
    """Main method"""

    parser = argparse.ArgumentParser(
        description='Build package.',
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('--pr-number', '-p',
                        dest='pr_number', type=int, required=True,
                        help='PR number')
    parser.add_argument('--repo', '-r',
                        dest='repo_id', default="Azure/azure-sdk-for-python",
                        help='Repo id. [default: %(default)s]')
    parser.add_argument("-v", "--verbose",
                        dest="verbose", action="store_true",
                        help="Verbosity in INFO mode")
    parser.add_argument("--debug",
                        dest="debug", action="store_true",
                        help="Verbosity in DEBUG mode")

    parser.add_argument('--output-folder', '-o',
                        dest='output_folder', default='.',
                        help='Output folder for package. [default: %(default)s]')

    args = parser.parse_args()
    main_logger = logging.getLogger()
    if args.verbose or args.debug:
        logging.basicConfig()
        main_logger.setLevel(logging.DEBUG if args.debug else logging.INFO)

    build_package_from_pr_number(
        os.environ["GH_TOKEN"],
        args.repo_id,
        args.pr_number,
        args.output_folder
    )

if __name__ == "__main__":
    generate_main()
