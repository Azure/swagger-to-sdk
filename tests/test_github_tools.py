from pathlib import Path
from subprocess import CalledProcessError
import tempfile

import pytest

from git import Repo, GitCommandError

from swaggertosdk.github_tools import (
    exception_to_github,
    user_from_token,
    configure_user,
    clone_to_path,
    manage_git_folder,
    do_pr,
    get_files,
    create_comment,
    GithubLink,
)


def test_exception_to_github(github_client):
    # Prepare
    repo = github_client.get_repo("lmazuel/TestingRepo")
    issue = repo.get_issue(13)

    # Act
    with exception_to_github(issue) as error:
        pass

    assert error.comment is None

    # Act
    with exception_to_github(issue) as error:
        "Test".fakemethod(12)  # pylint: disable=no-member

    # Test
    assert error.comment is not None
    assert "Swagger to SDK encountered an unknown error" in error.comment.body

    # Clean my mess
    error.comment.delete()

    # Act
    with exception_to_github(issue, "Python bot") as error:
        "Test".fakemethod(12)  # pylint: disable=no-member

    # Test
    assert error.comment is not None
    assert "Swagger to SDK encountered an unknown error: (Python bot)" in error.comment.body

    # Clean my mess
    error.comment.delete()

    # Act
    with exception_to_github(issue, "Python bot") as error:
        raise CalledProcessError(
            2,
            ["autorest", "readme.md"],
            "Error line 1\nError line 2"
        )

    # Test
    assert error.comment is not None
    assert "Swagger to SDK encountered a Subprocess error: (Python bot)" in error.comment.body
    assert "Error line 1" in error.comment.body

    # Clean my mess
    error.comment.delete()

    # Act
    with exception_to_github(issue, "Python bot") as error:
        raise CalledProcessError(
            2,
            ["autorest", "readme.md"],
        )

    # Test
    assert error.comment is not None
    assert "Swagger to SDK encountered a Subprocess error: (Python bot)" in error.comment.body
    assert "no output" in error.comment.body

    # Clean my mess
    error.comment.delete()

def test_get_user(github_token):
    user = user_from_token(github_token)
    assert user.login == 'lmazuel'

def test_get_files(github_client):
    repo = github_client.get_repo("Azure/azure-sdk-for-python")
    pr = repo.get_pull(1833)
    files = get_files(pr)
    assert "azure-mgmt-consumption/azure/mgmt/consumption/consumption_management_client.py" in [f.filename for f in files]

    commit = repo.get_commit("042b7a5840ff471776bb64e46b50950ee9f84430")
    files = get_files(commit)
    assert "azure-mgmt-consumption/azure/mgmt/consumption/consumption_management_client.py" in [f.filename for f in files]

def test_create_comment(github_client):
    repo = github_client.get_repo("lmazuel/TestingRepo")
    issue = repo.get_issue(14)
    comment = create_comment(issue, "This is a test")
    comment.delete()

    pull = repo.get_pull(2)
    comment = create_comment(pull, "This is a test")
    comment.delete()

def test_configure(github_token):
    finished = False
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                Repo.clone_from('https://github.com/lmazuel/TestingRepo.git', temp_dir)
                repo = Repo(temp_dir)

                # If it's not throwing, I'm happy enough
                configure_user(github_token, repo)

                assert repo.git.config('--get', 'user.name') == 'Laurent Mazuel'
            except Exception as err:
                print(err)
                pytest.fail(err)
            else:
                finished = True
    except PermissionError:
        if finished:
            return
        raise

def test_clone_path(github_token):
    finished = False # Authorize PermissionError on cleanup
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            clone_to_path(github_token, temp_dir, "lmazuel/TestingRepo")
            assert (Path(temp_dir) / Path("README.md")).exists()

            finished = True
    except PermissionError:
        if not finished:
            raise

    finished = False # Authorize PermissionError on cleanup
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            clone_to_path(github_token, temp_dir, "https://github.com/lmazuel/TestingRepo")
            assert (Path(temp_dir) / Path("README.md")).exists()

            finished = True
    except PermissionError:
        if not finished:
            raise

    finished = False # Authorize PermissionError on cleanup
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            clone_to_path(github_token, temp_dir, "lmazuel/TestingRepo", "lmazuel-patch-1")
            assert (Path(temp_dir) / Path("README.md")).exists()

            finished = True
    except PermissionError:
        if not finished:
            raise

    finished = False # Authorize PermissionError on cleanup
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            with pytest.raises(GitCommandError):
                clone_to_path(github_token, temp_dir, "lmazuel/TestingRepo", "fakebranch")

            finished = True
    except (PermissionError, FileNotFoundError):
        if not finished:
            raise

def test_manage_git_folder(github_token):
    finished = False # Authorize PermissionError on cleanup
    try:
        with tempfile.TemporaryDirectory() as temp_dir, \
                    manage_git_folder(github_token, temp_dir, "lmazuel/TestingRepo") as rest_repo:

            assert (Path(rest_repo) / Path("README.md")).exists()

            finished = True
    except (PermissionError, FileNotFoundError):
        if not finished:
            raise

    finished = False # Authorize PermissionError on cleanup
    try:
        with tempfile.TemporaryDirectory() as temp_dir, \
                    manage_git_folder(github_token, temp_dir, "lmazuel/TestingRepo@lmazuel-patch-1") as rest_repo:

            assert (Path(rest_repo) / Path("README.md")).exists()
            assert "lmazuel-patch-1" in str(Repo(rest_repo).active_branch)

            finished = True
    except (PermissionError, FileNotFoundError):
        if not finished:
            raise

def test_do_pr(github_token):
    # Should do nothing
    do_pr(None, 'bad', 'bad', 'bad', 'bad')

    # Should do nothing
    do_pr(github_token, 'bad', None, 'bad', 'bad')

    # FIXME - more tests


def test_github_link():
    inputstr = "https://raw.githubusercontent.com/Azure/azure-rest-api-specs/master/specification/billing/resource-manager/readme.md"
    link = GithubLink.from_string(inputstr)
    assert link.gitid == "Azure/azure-rest-api-specs"
    assert link.branch_or_commit == "master"
    assert link.link_type == "raw"
    assert link.path == "specification/billing/resource-manager/readme.md"
    assert str(link) == inputstr
    raw_link = link.as_raw_link()
    assert isinstance(raw_link, GithubLink)
    assert str(raw_link) == str(link)

    inputstr = "https://github.com/Azure/azure-rest-api-specs/blob/master/specification/billing/resource-manager/readme.md"
    link = GithubLink.from_string(inputstr)
    assert link.gitid == "Azure/azure-rest-api-specs"
    assert link.branch_or_commit == "master"
    assert link.link_type == "blob"
    assert link.path == "specification/billing/resource-manager/readme.md"
    assert str(link) == inputstr
    raw_link = link.as_raw_link()
    assert isinstance(raw_link, GithubLink)
    assert str(raw_link) == "https://raw.githubusercontent.com/Azure/azure-rest-api-specs/master/specification/billing/resource-manager/readme.md"

    inputstr = "https://github.com/Azure/azure-rest-api-specs/tree/master/specification/billing/resource-manager"
    link = GithubLink.from_string(inputstr)
    assert link.gitid == "Azure/azure-rest-api-specs"
    assert link.branch_or_commit == "master"
    assert link.link_type == "tree"
    assert link.path == "specification/billing/resource-manager"
    assert str(link) == inputstr
    with pytest.raises(ValueError):
        link.as_raw_link()

    inputstr = "https://token@github.com/Azure/azure-rest-api-specs/blob/master/specification/billing/resource-manager/readme.md"
    link = GithubLink.from_string(inputstr)
    assert link.token == "token"
    assert link.gitid == "Azure/azure-rest-api-specs"
    assert link.branch_or_commit == "master"
    assert link.link_type == "blob"
    assert link.path == "specification/billing/resource-manager/readme.md"
    assert str(link) == inputstr
    raw_link = link.as_raw_link()
    assert isinstance(raw_link, GithubLink)    
    assert str(raw_link) == "https://token@raw.githubusercontent.com/Azure/azure-rest-api-specs/master/specification/billing/resource-manager/readme.md"
