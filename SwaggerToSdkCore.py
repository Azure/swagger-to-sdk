import os
import logging
import tempfile
import json
import re
import shutil
import stat
import datetime
import subprocess
from pathlib import Path
from contextlib import contextmanager

from git import Repo, GitCommandError
from github import Github, GithubException

from markdown_support import extract_yaml

_LOGGER = logging.getLogger(__name__)

LATEST_TAG = 'latest'

CONFIG_FILE = 'swagger_to_sdk_config.json'

DEFAULT_BRANCH_NAME = 'autorest'
DEFAULT_TRAVIS_PR_BRANCH_NAME = 'RestAPI-PR{number}'
DEFAULT_TRAVIS_BRANCH_NAME = 'RestAPI-{branch}'
DEFAULT_COMMIT_MESSAGE = 'Generated from {hexsha}'

IS_TRAVIS = os.environ.get('TRAVIS') == 'true'


def build_file_content(autorest_version):
    utc_time = datetime.datetime.utcnow().replace(microsecond=0).isoformat()+'Z'
    if autorest_version==LATEST_TAG:
        autorest_version = autorest_latest_version_finder()
    return {
        'autorest': autorest_version,
        'date': utc_time,
        'version': ''
    }


def autorest_latest_version_finder():
    my_folder = os.path.dirname(__file__)
    script_path = os.path.join(my_folder, "get_autorest_version.js")
    cmd = ["node", script_path]
    return subprocess.check_output(cmd).decode().strip()


def merge_options(global_conf, local_conf, key):
    """Merge the conf using override: local conf is prioritary over global"""
    global_keyed_conf = global_conf.get(key) # Could be None
    local_keyed_conf = local_conf.get(key) # Could be None

    if global_keyed_conf is None or local_keyed_conf is None:
        return global_keyed_conf or local_keyed_conf

    if isinstance(global_keyed_conf, list):
        options = set(global_keyed_conf)
    else:
        options = dict(global_keyed_conf)

    options.update(local_keyed_conf)
    return options


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

def get_documents_in_markdown_file(markdown_filepath):
    """Get the documents inside this markdown file, relative to the repo root.

    :params str markdown_filepath: The filepath, relative to the repo root or absolute.
    :returns: An iterable of Swagger specs in this markdown file
    :rtype: list<str>"""
    _LOGGER.info("Parsing markdown file %s", markdown_filepath)
    def pathconvert(doc_path):
        if doc_path.startswith('https'):
            return doc_path.split('/master/')[1]
        else:
            return markdown_filepath.parent / doc_path
    with markdown_filepath.open() as markdown_fd:
        try:
            yaml_code = extract_yaml(markdown_fd.read())
            if not yaml_code or 'input-file' not in yaml_code:
                return []
        except Exception as err:
            _LOGGER.critical("Invalid Markdown file: %s (%s)", markdown_filepath, str(err))
            raise
        return [Path(pathconvert(d)) for d in yaml_code['input-file']]

def find_markdown_files(base_dir=Path('.')):
    """Find markdown file.

    The path are relative to base_dir.
    :rtype: pathlib.Path"""
    return [v.relative_to(Path(base_dir)) for v in Path(base_dir).glob('*/*.md')]

def get_composite_file_as_json(composite_filepath):
    """Get the composite file as JSON"""
    with composite_filepath.open() as composite_fd:
        try:
            return json.load(composite_fd)
        except Exception:
            _LOGGER.critical("Invalid JSON file: %s", composite_filepath)
            raise

def get_documents_in_composite_file(composite_filepath):
    """Get the documents inside this composite file, relative to the repo root.

    :params str composite_filepath: The filepath, relative to the repo root or absolute.
    :returns: An iterable of Swagger specs in this composite file
    :rtype: list<str>"""
    _LOGGER.info("Parsing composite file %s", composite_filepath)
    def pathconvert(doc_path):
        if doc_path.startswith('https'):
            return doc_path.split('/master/')[1]
        else:
            return composite_filepath.parent / doc_path
    composite_json = get_composite_file_as_json(composite_filepath)
    return [Path(pathconvert(d)) for d in composite_json['documents']]

def find_composite_files(base_dir=Path('.')):
    """Find composite file.

    The path are relative to base_dir.
    :rtype: pathlib.Path"""
    return [v.relative_to(Path(base_dir)) for v in Path(base_dir).glob('*/composite*.json')]

def swagger_index_from_composite(base_dir=Path('.')):
    """Build a reversed index of the composite files in thie repository.
    :rtype: dict"""
    return {
        doc: composite_file
        for composite_file in find_composite_files(base_dir)
        for doc in get_documents_in_composite_file(composite_file)
    }

def swagger_index_from_markdown(base_dir=Path('.')):
    """Build a reversed index of the markdown files in this repository.
    :rtype: dict"""
    return {
        doc: markdown_file
        for markdown_file in find_markdown_files(base_dir)
        for doc in get_documents_in_markdown_file(markdown_file)
    }

def get_swagger_files_in_pr(pr_object):
    """Get the list of Swagger files in the given PR."""
    return {Path(file.filename) for file in pr_object.get_files()
            if re.match(r".*/swagger/.*\.json", file.filename, re.I)}

def get_swagger_project_files_in_pr(pr_object, base_dir=Path('.')):
    """List project files in the PR, a project file being a Composite file or a Swagger file."""
    swagger_files_in_pr = get_swagger_files_in_pr(pr_object)
    swagger_index = swagger_index_from_composite(base_dir)
    swagger_index.update(swagger_index_from_markdown(base_dir))
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
