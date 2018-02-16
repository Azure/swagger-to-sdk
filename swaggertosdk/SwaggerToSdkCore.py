"""SwaggerToSdk core tools.
"""
import json
import logging
import os
import re
import tempfile
from pathlib import Path

from github import Github, UnknownObjectException

from .autorest_tools import (
    autorest_latest_version_finder,
    autorest_bootstrap_version_finder,
    autorest_swagger_to_sdk_conf,
)
from .github_tools import (
    get_files,
    GithubLink
)

_LOGGER = logging.getLogger(__name__)

CONFIG_FILE = 'swagger_to_sdk_config.json'

DEFAULT_BRANCH_NAME = 'autorest'
DEFAULT_TRAVIS_PR_BRANCH_NAME = 'RestAPI-PR{number}'
DEFAULT_TRAVIS_BRANCH_NAME = 'RestAPI-{branch}'
DEFAULT_COMMIT_MESSAGE = 'Generated from {hexsha}'


def is_travis():
    return os.environ.get('TRAVIS') == 'true'


def build_file_content():
    autorest_version = autorest_latest_version_finder()
    autorest_bootstrap_version = autorest_bootstrap_version_finder()
    return {
        'autorest': autorest_version,
        'autorest_bootstrap': autorest_bootstrap_version,
    }


def get_repo_tag_meta(meta_conf):
    repotag = meta_conf.get("repotag")
    if repotag:
        return repotag
    # Guess for now, "repotag" should be added everywhere
    if "go" in meta_conf["autorest_options"]:
        return "azure-sdk-for-go"
    if "ruby" in meta_conf["autorest_options"]:
        return "azure-sdk-for-ruby"
    if "java" in meta_conf["autorest_options"]:
        return "azure-libraries-for-java"
    if "nodejs" in meta_conf["autorest_options"]:
        return "azure-sdk-for-node"
    raise ValueError("No repotag found or infered")


def get_context_tag_from_git_object(git_object):
    context_tags = set()
    files_list = get_files(git_object)
    for file in files_list:
        filepath = Path(file.filename)
        filename = filepath.as_posix()
        # Match if RP name
        match = re.match(r"specification/(.*)/Microsoft.\w*/(stable|preview)/", filename, re.I)
        if match:
            context_tags.add(match.groups()[0])
            continue
        # Match if stable/preview but not RP like ARM (i.e. Cognitive Services)
        match = re.match(r"specification/(.*)/(stable|preview)/", filename, re.I)
        if match:
            context_tags.add(match.groups()[0])
            continue
        # Match Readme
        # Do it last step, because if some weird Readme for ServiceFabric...
        match = re.match(r"specification/(.*)/readme.\w*.?md", filename, re.I)
        if match:
            context_tags.add(match.groups()[0])
            continue
        # No context-tags
    return context_tags


def get_readme_files_from_git_objects(git_object, base_dir=Path('.')):
    """Get readme files from this PR.
    Algo is to look for context, and then search for Readme inside this context.
    """
    readme_files = set()
    context_tags = get_context_tag_from_git_object(git_object)
    for context_tag in context_tags:
        expected_folder = Path(base_dir) / Path("specification/{}".format(context_tag))
        if not expected_folder.is_dir():
            _LOGGER.warning("From context {} I didn't find folder {}".format(
                context_tag,
                expected_folder
            ))
            continue
        for expected_readme in [l for l in expected_folder.iterdir() if l.is_file()]:
            # Need to do a case-insensitive test.
            match = re.match(r"readme.\w*.?md", expected_readme.name, re.I)
            if match:
                readme_files.add(expected_readme.relative_to(Path(base_dir)))
    return readme_files

def get_pr_object_from_travis(gh_token=None):
    """If Travis, return the Github object representing the PR.
       If result is None, is not Travis.
       The GH token is optional if the repo is public.
    """
    if not is_travis():
        return
    pr_number = os.environ['TRAVIS_PULL_REQUEST']
    if pr_number == 'false':
        _LOGGER.info("This build don't come from a PR")
        return
    github_con = Github(gh_token)
    github_repo = github_con.get_repo(os.environ['TRAVIS_REPO_SLUG'])

    try:
        return github_repo.get_pull(int(pr_number))
    except UnknownObjectException: # Likely Travis doesn't lie, the Token does not have enough permissions
        pass


def get_commit_object_from_travis(gh_token=None):
    """If Travis, return the Github object representing the current commit.
       If result is None, is not Travis.
       The GH token is optional if the repo is public.
    """
    if not is_travis():
        return
    _LOGGER.warning("Should improved using TRAVIS_COMMIT_RANGE: {}".format(os.environ['TRAVIS_COMMIT_RANGE']))
    commit_sha = os.environ['TRAVIS_COMMIT'] 
    github_con = Github(gh_token)
    github_repo = github_con.get_repo(os.environ['TRAVIS_REPO_SLUG'])

    try:
        return github_repo.get_commit(commit_sha)
    except UnknownObjectException: # Likely Travis doesn't lie, the Token does not have enough permissions
        _LOGGER.critical("Unable to get commit {}".format(commit_sha))


def get_pr_from_travis_commit_sha(gh_token=None):
    """Try to determine the initial PR using #<number> in the current commit comment.
    Will check if the found number is really a merged PR.
    The GH token is optional if the repo is public."""
    if not is_travis():
        return
    github_con = Github(gh_token)
    github_repo = github_con.get_repo(os.environ['TRAVIS_REPO_SLUG'])

    try:
        local_commit = github_repo.get_commit(os.environ['TRAVIS_COMMIT'])
    except UnknownObjectException: # Likely Travis doesn't lie, the Token does not have enough permissions
        _LOGGER.critical("Unable to get commit {}".format(os.environ['TRAVIS_COMMIT']))
        return

    commit_message = local_commit.commit.message
    issues_in_message = re.findall('#([\\d]+)', commit_message)

    issue_object = None
    for issue in issues_in_message:
        try:
            _LOGGER.info('Check if %s is a PR', issue)
            issue_object = github_repo.get_pull(int(issue))
            if not issue_object.is_merged():
                continue
            break
        except Exception:
            pass
    if not issue_object:
        _LOGGER.warning('Was not able to found PR commit message')
    return issue_object

def get_initial_pr(gh_token=None):
    """Try to deduce the initial PR of the current repo state.
    Use Travis env variable first, try with commit regexp otherwise.
    gh_token could be None for public repo.

    :param str gh_token: A Github token. Useful only if the repo is private.
    :return: A PR object if found, None otherwise
    :rtype: github.PullRequest.PullRequest
    """
    return get_pr_object_from_travis(gh_token) or \
        get_pr_from_travis_commit_sha(gh_token)


def compute_branch_name(branch_name, gh_token=None):
    """Compute the branch name depended on Travis, default or not"""
    if branch_name:
        return branch_name
    if not is_travis():
        return DEFAULT_BRANCH_NAME
    _LOGGER.info("Travis detected")
    pr_object = get_initial_pr(gh_token)
    if not pr_object:
        return DEFAULT_TRAVIS_BRANCH_NAME.format(branch=os.environ['TRAVIS_BRANCH'])
    return DEFAULT_TRAVIS_PR_BRANCH_NAME.format(number=pr_object.number)


def compute_pr_comment_with_sdk_pr(comment, sdk_fork_id, branch_name):
    travis_string = "[![Build Status]"\
                        "(https://travis-ci.org/{fork_repo_id}.svg?branch={branch_name})]"\
                        "(https://travis-ci.org/{fork_repo_id})"
    travis_string = travis_string.format(branch_name=branch_name,
                                         fork_repo_id=sdk_fork_id)
    return travis_string+' '+comment


def add_comment_to_initial_pr(gh_token, comment):
    """Add a comment to the initial PR.
    :returns: True is comment added, False if PR not found"""
    if not gh_token:
        return False
    initial_pr = get_initial_pr(gh_token)
    if not initial_pr:
        return False
    initial_pr.create_issue_comment(comment)
    return True


def read_config(sdk_git_folder, config_file):
    """Read the configuration file and return JSON"""
    config_path = os.path.join(sdk_git_folder, config_file)
    with open(config_path, 'r') as config_fd:
        return json.loads(config_fd.read())


def extract_conf_from_readmes(swagger_files_in_pr, restapi_git_folder, sdk_git_id, config):
    readme_files_in_pr = {readme for readme in swagger_files_in_pr if getattr(readme, "name", readme).lower().endswith("readme.md")}
    for readme_file in readme_files_in_pr:
        build_swaggertosdk_conf_from_json_readme(readme_file, sdk_git_id, config, base_folder=restapi_git_folder)

def get_readme_path(readme_file, base_folder='.'):
    """Get a readable Readme path.

    If start with http, assume online, ignore base_folder and convert to raw link if necessary.
    If base_folder is not None, assume relative to base_folder.
    """
    if not isinstance(readme_file, Path) and readme_file.startswith("http"):
        return GithubLink.from_string(readme_file).as_raw_link()
    else:
        if base_folder is None:
            base_folder='.'
        return str(Path(base_folder) / Path(readme_file))

def build_swaggertosdk_conf_from_json_readme(readme_file, sdk_git_id, config, base_folder='.'):
    """Get the JSON conf of this README, and create SwaggerToSdk conf.

    Readme path can be any readme syntax accepted by autorest.
    readme_file will be project key as-is.

    :param str readme_file: A path that Autorest accepts. Raw GH link or absolute path.
    :param str sdk_dit_id: Repo ID. IF org/login is provided, will be stripped.
    :config dict config: Config where to update the "projects" key.
    """
    readme_full_path = get_readme_path(readme_file, base_folder)
    with tempfile.TemporaryDirectory() as temp_dir:
        readme_as_conf = autorest_swagger_to_sdk_conf(
            readme_full_path,
            temp_dir
        )
    sdk_git_short_id = sdk_git_id.split("/")[-1].lower()
    for swagger_to_sdk_conf in readme_as_conf:
        repo = swagger_to_sdk_conf.get("repo", "")
        repo = repo.split("/")[-1].lower() # Be sure there is no org/login part
        if repo == sdk_git_short_id:
            _LOGGER.info("This Readme contains a swagger-to-sdk section for repo {}".format(repo))
            generated_config = {
                "markdown": readme_full_path,
                "autorest_options": swagger_to_sdk_conf.get("autorest_options", {}),
                "after_scripts": swagger_to_sdk_conf.get("after_scripts", []),
            }
            config.setdefault("projects", {})[str(readme_file)] = generated_config
            return generated_config
        else:
            _LOGGER.info("Skip mismatch {} from {}".format(repo, sdk_git_short_id))

def get_input_paths(global_conf, local_conf):
    """Returns a 2-tuple:
    - Markdown Path or None
    - Input-file Paths or empty list
    """
    del global_conf # Unused

    relative_markdown_path = None # Markdown is optional
    input_files = [] # Input file could be empty
    if "markdown" in local_conf:
        relative_markdown_path = Path(local_conf['markdown'])
    input_files = local_conf.get('autorest_options', {}).get('input-file', [])
    if input_files and not isinstance(input_files, list):
        input_files = [input_files]
    input_files = [Path(input_file) for input_file in input_files]
    if not relative_markdown_path and not input_files:
        raise ValueError("No input file found")
    return (relative_markdown_path, input_files)


def solve_relative_path(autorest_options, sdk_root):
    """Solve relative path in conf.

    If a key is prefixed by "sdkrel:", it's solved against SDK root.
    """
    SDKRELKEY = "sdkrel:"
    solved_autorest_options = {}
    for key, value in autorest_options.items():
        if key.startswith(SDKRELKEY):
            _LOGGER.debug("Found a sdkrel pair: %s/%s", key, value)
            subkey = key[len(SDKRELKEY):]
            solved_value = Path(sdk_root, value).resolve()
            solved_autorest_options[subkey] = str(solved_value)
        else:
            solved_autorest_options[key] = value
    return solved_autorest_options
