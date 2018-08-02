from types import SimpleNamespace

import pytest

from swaggertosdk.restapi.github_handler import clean_sdk_pr

def test_clean_sdk_pr(github_client):

    # Mock a Rest PR from a fork
    rest_pr = SimpleNamespace(
        number=666,
        head=SimpleNamespace(
            repo=None,  # Deleted fork
        ),
        base=SimpleNamespace(
            repo=None  # Don't need the base repo if fork
        ),
    )

    sdk_repo = github_client.get_repo("lmazuel/TestingRepo")

    # Create a copy of branch "test_clean_base"
    # If this branch does not exist, test will fail
    test_clean_base_ref = sdk_repo.get_git_ref("heads/test_clean_base")
    sdk_repo.create_git_ref(
        "refs/heads/restapi_auto_666",
        test_clean_base_ref.object.sha
    )

    # Create PR
    sdk_repo.create_pull(
        title="Testing clean",
        body="Testing clean",
        head="restapi_auto_666",
        base="master"
    )

    # Actual test
    result = clean_sdk_pr(rest_pr, sdk_repo)
    assert result is None

    # Assert branch is gone, means the PR is gone as well
    try:
        sdk_repo.get_git_ref("heads/restapi_auto_666")
        pytest.fail("Should have fail, because the branch should be gone")
    except Exception:
        pass