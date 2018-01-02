import os
import logging
import json
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from contextlib import contextmanager

from git import Repo
from github import Github, GithubException

from .markdown_support import extract_yaml
from .autorest_tools import autorest_latest_version_finder, autorest_bootstrap_version_finder, autorest_swagger_to_sdk_conf

_LOGGER = logging.getLogger(__name__)

CONFIG_FILE = 'swagger_to_sdk_config.json'

DEFAULT_BRANCH_NAME = 'autorest'
DEFAULT_TRAVIS_PR_BRANCH_NAME = 'RestAPI-PR{number}'
DEFAULT_TRAVIS_BRANCH_NAME = 'RestAPI-{branch}'
DEFAULT_COMMIT_MESSAGE = 'Generated from {hexsha}'

IS_TRAVIS = os.environ.get('TRAVIS') == 'true'


def build_file_content():
    autorest_version = autorest_latest_version_finder()
    autorest_bootstrap_version = autorest_bootstrap_version_finder()
    return {
        'autorest': autorest_version,
        'autorest_bootstrap': autorest_bootstrap_version,
    }


def checkout_and_create_branch(repo, name):
    """Checkout branch. Create it if necessary"""
    local_branch = repo.branches[name] if name in repo.branches else None
    if not local_branch:
        if name in repo.remotes.origin.refs:
            # If origin branch exists but not local, git.checkout is the fatest way
            # to create local branch with origin link automatically
            msg = repo.git.checkout(name)
            _LOGGER.debug(msg)
            return
        # Create local branch, will be link to origin later
        local_branch = repo.create_head(name)
    local_branch.checkout()

def get_documents_in_markdown_file(markdown_filepath, base_dir=Path('.')):
    """Get the documents inside this markdown file, relative to the repo root.

    :params str markdown_filepath: The filepath, relative to the repo root or absolute.
    :returns: An iterable of Swagger specs in this markdown file
    :rtype: list<str>"""
    _LOGGER.debug("Parsing markdown file %s", markdown_filepath)
    def pathconvert(doc_path):
        if doc_path.startswith('https'):
            return doc_path.split('/master/')[1]
        else:
            return markdown_filepath.parent / doc_path
    with (base_dir / markdown_filepath).open() as markdown_fd:
        try:
            raw_input_file = extract_yaml(markdown_fd.read())
        except Exception as err:
            _LOGGER.critical("Invalid Markdown file: %s (%s)", markdown_filepath, str(err))
            return []
        return [Path(pathconvert(d)) for d in raw_input_file]

def find_markdown_files(base_dir=Path('.')):
    """Find markdown file.

    The path are relative to base_dir.
    :rtype: pathlib.Path"""
    return [v.relative_to(Path(base_dir)) for v in Path(base_dir).glob('**/*.md')]

def swagger_index_from_markdown(base_dir=Path('.')):
    """Build a reversed index of the markdown files in this repository.
    :rtype: dict"""
    return {
        doc: markdown_file
        for markdown_file in find_markdown_files(base_dir)
        for doc in get_documents_in_markdown_file(markdown_file, base_dir)
    }

def get_swagger_files_in_git_object(git_object):
    """Get the list of Swagger files in the given PR or commit"""
    try:
        files_list = git_object.get_files() # Try as a PR object
    except AttributeError:
        files_list = git_object.files # Try as a commit object
    return {Path(file.filename) for file in files_list
            if re.match(r"specification/.*\.json", file.filename, re.I) or re.match(r"specification/.*/readme.md", file.filename, re.I)
           }

def get_swagger_project_files_in_pr(pr_object, base_dir=Path('.')):
    """List project files in the PR, a project file being a Markdown file or a Swagger file."""
    swagger_files_in_pr = get_swagger_files_in_git_object(pr_object)
    swagger_index = swagger_index_from_markdown(base_dir)
    swagger_files_in_pr |= {swagger_index[s]
                            for s in swagger_files_in_pr
                            if s in swagger_index}
    return swagger_files_in_pr


def do_commit(repo, message_template, branch_name, hexsha):
    "Do a commit if modified/untracked files"
    repo.git.add(repo.working_tree_dir)

    if not repo.git.diff(staged=True):
        _LOGGER.warning('No modified files in this Autorest run')
        return False

    checkout_and_create_branch(repo, branch_name)
    msg = message_template.format(hexsha=hexsha)
    repo.index.commit(msg)
    _LOGGER.info("Commit done: %s", msg)
    return True


def sync_fork(gh_token, github_repo_id, repo):
    """Sync the current branch in this fork against the direct parent on Github"""
    if not gh_token:
        _LOGGER.warning('Skipping the upstream repo sync, no token')
        return
    _LOGGER.info('Check if repo has to be sync with upstream')
    github_con = Github(gh_token)
    github_repo = github_con.get_repo(github_repo_id)

    if not github_repo.parent:
        _LOGGER.warning('This repo has no upstream')
        return

    upstream_url = 'https://github.com/{}.git'.format(github_repo.parent.full_name)
    upstream = repo.create_remote('upstream', url=upstream_url)
    upstream.fetch()
    active_branch_name = repo.active_branch.name
    if not active_branch_name in repo.remotes.upstream.refs:
        _LOGGER.info('Upstream has no branch %s to merge from', active_branch_name)
        return
    else:
        _LOGGER.info('Merge from upstream')
    msg = repo.git.rebase('upstream/{}'.format(repo.active_branch.name))
    _LOGGER.debug(msg)
    msg = repo.git.push()
    _LOGGER.debug(msg)


def get_pr_object_from_travis(gh_token=None):
    """If Travis, return the Github object representing the PR.
       If result is None, is not Travis.
       The GH token is optional if the repo is public.
    """
    if not IS_TRAVIS:
        return
    pr_number = os.environ['TRAVIS_PULL_REQUEST']
    if pr_number == 'false':
        _LOGGER.info("This build don't come from a PR")
        return
    github_con = Github(gh_token)
    github_repo = github_con.get_repo(os.environ['TRAVIS_REPO_SLUG'])

    return github_repo.get_pull(int(pr_number))


def get_commit_object_from_travis(gh_token=None):
    """If Travis, return the Github object representing the current commit.
       If result is None, is not Travis.
       The GH token is optional if the repo is public.
    """
    if not IS_TRAVIS:
        return
    _LOGGER.warning("Should improved using TRAVIS_COMMIT_RANGE: {}".format(os.environ['TRAVIS_COMMIT_RANGE']))
    commit_sha = os.environ['TRAVIS_COMMIT'] 
    github_con = Github(gh_token)
    github_repo = github_con.get_repo(os.environ['TRAVIS_REPO_SLUG'])

    return github_repo.get_commit(commit_sha)


def get_pr_from_travis_commit_sha(gh_token=None):
    """Try to determine the initial PR using #<number> in the current commit comment.
    Will check if the found number is really a merged PR.
    The GH token is optional if the repo is public."""
    if not IS_TRAVIS:
        return
    github_con = Github(gh_token)
    github_repo = github_con.get_repo(os.environ['TRAVIS_REPO_SLUG'])

    local_commit = github_repo.get_commit(os.environ['TRAVIS_COMMIT'])
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


def user_from_token(gh_token):
    """Get user login from GitHub token"""
    github_con = Github(gh_token)
    return github_con.get_user()


def configure_user(gh_token, repo):
    """git config --global user.email "you@example.com"
       git config --global user.name "Your Name"
    """
    user = user_from_token(gh_token)
    repo.git.config('user.email', user.email or 'autorestci@microsoft.com')
    repo.git.config('user.name', user.name or 'SwaggerToSDK Automation')


def compute_branch_name(branch_name, gh_token=None):
    """Compute the branch name depended on Travis, default or not"""
    if branch_name:
        return branch_name
    if not IS_TRAVIS:
        return DEFAULT_BRANCH_NAME
    _LOGGER.info("Travis detected")
    pr_object = get_initial_pr(gh_token)
    if not pr_object:
        return DEFAULT_TRAVIS_BRANCH_NAME.format(branch=os.environ['TRAVIS_BRANCH'])
    return DEFAULT_TRAVIS_PR_BRANCH_NAME.format(number=pr_object.number)

def do_pr(gh_token, sdk_git_id, sdk_pr_target_repo_id, branch_name, base_branch):
    "Do the PR"
    if not gh_token:
        _LOGGER.info('Skipping the PR, no token found')
        return
    if not sdk_pr_target_repo_id:
        _LOGGER.info('Skipping the PR, no target repo id')
        return

    github_con = Github(gh_token)
    sdk_pr_target_repo = github_con.get_repo(sdk_pr_target_repo_id)

    if '/' in sdk_git_id:
        sdk_git_owner = sdk_git_id.split('/')[0]
        _LOGGER.info("Do the PR from %s", sdk_git_owner)
        head_name = "{}:{}".format(sdk_git_owner, branch_name)
    else:
        head_name = branch_name

    body = ''
    rest_api_pr = get_initial_pr(gh_token)
    if rest_api_pr:
        body += "Generated from RestAPI PR: {}".format(rest_api_pr.html_url)
    try:
        github_pr = sdk_pr_target_repo.create_pull(
            title='Automatic PR from {}'.format(branch_name),
            body=body,
            head=head_name,
            base=base_branch
        )
    except GithubException as err:
        if err.status == 422 and err.data['errors'][0]['message'].startswith('A pull request already exists'):
            _LOGGER.info('PR already exists, it was a commit on an open PR')
            return
        raise
    _LOGGER.info("Made PR %s", github_pr.html_url)
    comment = compute_pr_comment_with_sdk_pr(github_pr.html_url, sdk_git_id, branch_name)
    add_comment_to_initial_pr(gh_token, comment)


def get_swagger_hexsha(restapi_git_folder):
    """Get the SHA1 of the current repo"""
    repo = Repo(restapi_git_folder)
    if repo.bare:
        not_git_hexsha = "notgitrepo"
        _LOGGER.warning("Not a git repo, SHA1 used will be: %s", not_git_hexsha)
        return not_git_hexsha
    hexsha = repo.head.commit.hexsha
    _LOGGER.info("Found REST API repo SHA1: %s", hexsha)
    return hexsha

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


def clone_to_path(gh_token, temp_dir, sdk_git_id):
    """Clone the given repo_id to the 'sdk' folder in given temp_dir"""
    _LOGGER.info("Clone SDK repository %s", sdk_git_id)

    credentials_part = ''
    if gh_token:
        login = user_from_token(gh_token).login
        credentials_part = '{user}:{token}@'.format(
            user=login,
            token=gh_token
        )
    else:
        _LOGGER.warning('Will clone the repo without writing credentials')

    https_authenticated_url = 'https://{credentials}github.com/{sdk_git_id}.git'.format(
        credentials=credentials_part,
        sdk_git_id=sdk_git_id
    )
    sdk_path = os.path.join(temp_dir, 'sdk')
    Repo.clone_from(https_authenticated_url, sdk_path)
    _LOGGER.info("Clone success")

    return sdk_path

def remove_readonly(func, path, _):
    "Clear the readonly bit and reattempt the removal"
    os.chmod(path, stat.S_IWRITE)
    func(path)

@contextmanager
def manage_sdk_folder(gh_token, temp_dir, sdk_git_id):
    """Context manager to avoid readonly problem while cleanup the temp dir"""
    sdk_path = clone_to_path(gh_token, temp_dir, sdk_git_id)
    _LOGGER.debug("SDK path %s", sdk_path)
    try:
        yield sdk_path
        # Pre-cleanup for Windows http://bugs.python.org/issue26660
    finally:
        _LOGGER.debug("Preclean SDK folder")
        shutil.rmtree(sdk_path, onerror=remove_readonly)


def get_full_sdk_id(gh_token, sdk_git_id):
    """If the SDK git id is incomplete, try to complete it with user login"""
    if not '/' in sdk_git_id:
        login = user_from_token(gh_token).login
        return '{}/{}'.format(login, sdk_git_id)
    return sdk_git_id


def read_config(sdk_git_folder, config_file):
    """Read the configuration file and return JSON"""
    config_path = os.path.join(sdk_git_folder, config_file)
    with open(config_path, 'r') as config_fd:
        return json.loads(config_fd.read())


def extract_conf_from_readmes(gh_token, swagger_files_in_pr, restapi_git_folder, sdk_git_id, config):
    readme_files_in_pr = {readme for readme in swagger_files_in_pr if readme.name.lower() == "readme.md"}
    with tempfile.TemporaryDirectory() as temp_dir:
        for readme_file in readme_files_in_pr:
            abs_readme_path = Path(restapi_git_folder, readme_file)
            readme_as_conf = autorest_swagger_to_sdk_conf(abs_readme_path, temp_dir)
            for swagger_to_sdk_conf in readme_as_conf:
                repo = swagger_to_sdk_conf.get("repo", "")
                if gh_token:
                    repo = get_full_sdk_id(gh_token, repo)
                if repo.split("/")[-1] == sdk_git_id.split("/")[-1]:
                    _LOGGER.info("This Readme contains a swagger-to-sdk section for repo {}".format(repo))
                    config.setdefault("projects",{})[str(readme_file)] = {
                        "markdown": str(readme_file),
                        "autorest_options": swagger_to_sdk_conf.get("autorest_options", {})
                    }
    