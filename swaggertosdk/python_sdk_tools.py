"""This file is specific to Azure SDK for Python and should be split somewhere else."""
import logging
from pathlib import Path
import tempfile

from github import Github

from .github_tools import manage_git_folder
from .autorest_tools import execute_simple_command

_LOGGER = logging.getLogger(__name__)


def build_package_from_pr_number(gh_token, sdk_id, pr_number, output_folder):
    """Will clone the given PR branch and vuild the package with the given name."""

    con = Github(gh_token)
    repo = con.get_repo(sdk_id)
    sdk_pr = repo.get_pull(pr_number)
    package_names = {f.filename.split('/')[0] for f in sdk_pr.get_files() if f.filename.startswith("azure")}
    absolute_output_folder = str(Path(output_folder).resolve())

    with tempfile.TemporaryDirectory() as temp_dir, \
            manage_git_folder(gh_token, Path(temp_dir) / Path("sdk"), sdk_id, pr_number=pr_number) as sdk_folder:

        for package_name in package_names:
            _LOGGER.debug("Build {}".format(package_name))
            execute_simple_command(
                ["python", "./build_package.py", "--dest", absolute_output_folder, package_name],
                cwd=sdk_folder
            )
            _LOGGER.debug("Build finished: {}".format(package_name))
