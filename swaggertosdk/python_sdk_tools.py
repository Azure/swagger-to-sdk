"""This file is specific to Azure SDK for Python and should be split somewhere else."""
import logging
from pathlib import Path
import tempfile

from github import Github

from azure_devtools.ci_tools.github_tools import (
    manage_git_folder,
    DashboardCommentableObject
)
from .autorest_tools import execute_simple_command

_LOGGER = logging.getLogger(__name__)


_STORAGE_ACCOUNT = "http://azuresdkinfrajobstore1.blob.core.windows.net/azure/azure-sdk-for-python/pullrequests/{prnumber}/dist/{file}"

def build_package_from_pr_number(gh_token, sdk_id, pr_number, output_folder, *, with_comment=False):
    """Will clone the given PR branch and vuild the package with the given name."""

    con = Github(gh_token)
    repo = con.get_repo(sdk_id)
    sdk_pr = repo.get_pull(pr_number)
    # "get_files" of Github only download the first 300 files. Might not be enough.
    package_names = {f.filename.split('/')[0] for f in sdk_pr.get_files() if f.filename.startswith("azure")}
    absolute_output_folder = Path(output_folder).resolve()

    with tempfile.TemporaryDirectory() as temp_dir, \
            manage_git_folder(gh_token, Path(temp_dir) / Path("sdk"), sdk_id, pr_number=pr_number) as sdk_folder:

        for package_name in package_names:
            _LOGGER.debug("Build {}".format(package_name))
            execute_simple_command(
                ["python", "./build_package.py", "--dest", str(absolute_output_folder), package_name],
                cwd=sdk_folder
            )
            _LOGGER.debug("Build finished: {}".format(package_name))

    if with_comment:
        files = [f.name for f in absolute_output_folder.iterdir()]
        comment_message = None
        dashboard = DashboardCommentableObject(sdk_pr, "(message created by the CI based on PR content)")
        try:
            installation_message = build_installation_message(sdk_pr)
            download_message = build_download_message(sdk_pr, files)
            comment_message = installation_message + "\n\n" + download_message
            dashboard.create_comment(comment_message)
        except Exception:
            _LOGGER.critical("Unable to do PR comment:\n%s", comment_message)

def build_download_message(sdk_pr, files):
    if not files:
        return ""
    message = "# Direct download\n\nYour files can be directly downloaded here:\n\n"
    for filename in files:
        message += "- [{}]({})\n".format(
            filename,
            _STORAGE_ACCOUNT.format(prnumber=sdk_pr.number, file=filename)
        )
    return message

def build_installation_message(sdk_pr):
    # Package starts with "azure" and is at the root of the repo
    package_names = {f.filename.split('/')[0] for f in sdk_pr.get_files() if f.filename.startswith("azure")}

    result = ["# Installation instruction"]
    for package in package_names:
        result.append("## Package {}".format(package))
        result.append(pr_message_for_package(sdk_pr, package))
    return "\n".join(result)


def pr_message_for_package(sdk_pr, package_name):
    git_path = '"git+{}@{}#egg={}&subdirectory={}"'.format(
        sdk_pr.head.repo.html_url,
        sdk_pr.head.ref,
        package_name,
        package_name
    )

    pip_install = 'pip install {}'
    pip_wheel = 'pip wheel --no-deps {}'

    pr_body = "You can install the package `{}` of this PR using the following command:\n\t`{}`".format(
        package_name,
        pip_install.format(git_path)
    )

    pr_body += "\n\n"

    pr_body += "You can build a wheel to distribute for test using the following command:\n\t`{}`".format(
        pip_wheel.format(git_path)
    )

    pr_body += "\n\n"
    pr_body += "If you have a local clone of this repository, you can also do:\n\n"
    pr_body += "- `git checkout {}`\n".format(sdk_pr.head.ref)
    pr_body += "- `pip install -e ./{}`\n".format(package_name)
    pr_body += "\n\n"
    pr_body += "Or build a wheel file to distribute for testing:\n\n"
    pr_body += "- `git checkout {}`\n".format(sdk_pr.head.ref)
    pr_body += "- `pip wheel --no-deps ./{}`\n".format(package_name)
    return pr_body
