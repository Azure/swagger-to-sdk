from swaggertosdk.restapi.sdkbot import GithubHandler


def test_sdk_bot_git(github_client, github_token):
    handler = GithubHandler(github_token)

    repo = github_client.get_repo("lmazuel/TestingRepo")
    issue = repo.get_issue(11)

    output = handler.git(issue, "show", "2a0c2f0285117ccb07b6f9c32749d6c50abed70b")
    assert "commit 2a0c2f0285117ccb07b6f9c32749d6c50abed70b" in output
