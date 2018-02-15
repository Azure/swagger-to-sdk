from enum import Enum
import logging
import os
from pathlib import Path
import tempfile

from git import Repo, GitCommandError
from github import UnknownObjectException, GithubException

from swaggertosdk.SwaggerToSdkCore import (
    CONFIG_FILE,
    read_config,
    DEFAULT_COMMIT_MESSAGE,
    get_input_paths,
    extract_conf_from_readmes,
    get_readme_files_from_git_objects,
    get_context_tag_from_git_object,
)
from swaggertosdk.SwaggerToSdkNewCLI import build_libraries
from swaggertosdk.git_tools import (
    checkout_and_create_branch,
    do_commit,
)
from swaggertosdk.github_tools import (
    configure_user,
    manage_git_folder,
    get_or_create_pull,
    DashboardCommentableObject,
)

_LOGGER = logging.getLogger(__name__)

# How many context tag I authorize in a PR to accept it
_CONTEXT_TAG_LIMITS = 3

# SDK pr branch prefix
_SDK_PR_TEMPLATE = "restapi_auto_{}"

# Default RestAPI branch
_DEFAULT_REST_BRANCH = "master"

# Default SDK branch
_DEFAULT_SDK_BRANCH = "master"

class SwaggerToSdkLabels(Enum):
    merged = "RestPRMerged", "0e8a16"
    refused = "RestPRRefused", "b60205"
    in_progress = "RestPRInProgress", "fbca04"
    service_pr = "ServicePR", "1d76db"

def get_or_create_label(sdk_pr_target_repo, label_enum):
    try:
        return sdk_pr_target_repo.get_label(label_enum.value[0])
    except UnknownObjectException:
        return sdk_pr_target_repo.create_label(*label_enum.value)

def safe_remove_label(issue, label):
    """Remove a label, does not fail if label was not there.
    """
    try:
        issue.remove_from_labels(label)
    except GithubException:
        pass

def manage_labels(issue, to_add=None, to_remove=None):
    if not to_add:
        to_add = []
    if not to_remove:
        to_remove = []
    for label_remove in to_remove:
        safe_remove_label(issue, get_or_create_label(issue.repository, label_remove))
    for label_add in to_add:
        try:
            issue.add_to_labels(get_or_create_label(issue.repository, label_add))
        except Exception as err:
            # Never fail is adding a label was impossible
            _LOGGER.warning("Unable to add label: %s", label_add)

def rest_pr_management(rest_pr, sdk_repo, sdk_tag, sdk_default_base=_DEFAULT_SDK_BRANCH):
    """What to do when something happen to a PR in the Rest repo.

    :param restpr: a PyGithub pull object
    :type restpr: github.PullRequest.PullRequest
    :param sdk_repo: a PyGithub repository
    :type sdk_repo: github.Repository.Repository
    :param str sdk_tag: repotag to use to filter SwaggerToSDK conf
    :param str sdk_default_base: Default SDK branch.
    """
    # Extract some metadata as variables
    rest_repo = rest_pr.base.repo
    origin_repo_name = rest_pr.head.repo.full_name
    is_from_a_fork = origin_repo_name != rest_repo.full_name

    # THE comment were we put everything
    dashboard = DashboardCommentableObject(rest_pr, "# Automation for {}".format(sdk_tag))

    #
    # Work on context, ext if context is not good
    #
    context_tags = list(get_context_tag_from_git_object(rest_pr))
    if not context_tags:
        dashboard.create_comment("Unable to detect any generation context from this PR.")
        return
    if len(context_tags) > _CONTEXT_TAG_LIMITS:
        dashboard.create_comment(
            "This PR contains more than {} context, SDK generation is not enabled. Contexts found:\n{}".format(
                _CONTEXT_TAG_LIMITS,
                "\n".join(["- {}".format(ctxt) for ctxt in context_tags])
            ))
        return

    #
    # Compute the "head" of future SDK PR.
    #
    if is_from_a_fork:
        sdk_pr_head = _SDK_PR_TEMPLATE.format(rest_pr.number)
    else:
        sdk_pr_head = _SDK_PR_TEMPLATE.format(rest_pr.head.ref)

    #
    # Compute the "base" of future SDK PR.
    # "sdk_checkout_bases" is an ordered list of branchs to checkout, since this can be several
    # branches that derives from "master".
    # This are branches that SwaggerToSDK should have "push" permission. Do NOT add "master" or a protected
    # branch to that list.
    #
    sdk_checkout_bases = []
    if rest_pr.base.ref == _DEFAULT_REST_BRANCH:
        sdk_pr_base = _DEFAULT_SDK_BRANCH
    else:
        sdk_pr_base = _SDK_PR_TEMPLATE.format(rest_pr.base.ref)
        sdk_checkout_bases.append(sdk_pr_base)

    # In special case where I have one context and it's a fork, use context branch as base
    if is_from_a_fork and len(context_tags) == 1:
        sdk_pr_base = _SDK_PR_TEMPLATE.format(context_tags[0])
        sdk_checkout_bases.insert(0, sdk_pr_base)

    #
    # Try to generate on "head", whatever the state of the PR.
    #
    generate_sdk_from_git_object(
        rest_pr,
        sdk_pr_head,
        origin_repo_name,  # Needed to clone. Should be improved to use "pull/number/head"
        sdk_repo.full_name,
        sdk_checkout_bases,
        fallback_base_branch_name=sdk_default_base,
        sdk_tag=sdk_tag
    )

    #
    # Try to create/get a SDK PR.
    #
    # There is a lot of reasons why a SDK PR could not exist even on a "close" event, so don't assume this exists.
    #
    try:
        sdk_pr = get_or_create_pull(
            sdk_repo,
            title='[AutoPR {}] {}'.format("/".join(context_tags), rest_pr.title),
            body="Created to sync {}".format(rest_pr.html_url),
            head=sdk_repo.owner.login+":"+sdk_pr_head,
            base=sdk_pr_base,
        )
    except Exception as err:
        _LOGGER.warning("Unable to create SDK PR: %s", err)
        dashboard.create_comment("Nothing to generate for {}".format(sdk_tag))
        return

    # Replace whatever message it was if we were able to do a PR
    dashboard.create_comment("A PR has been created for you:\n{}".format(sdk_pr.html_url))

    #
    # Manage labels/state on this SDK PR.
    #
    sdk_pr_as_issue = sdk_repo.get_issue(sdk_pr.number)
    if rest_pr.closed_at:  # If there is a date, this is closed
        if rest_pr.merged:
            manage_labels(sdk_pr_as_issue,
                          to_add=[SwaggerToSdkLabels.merged],
                          to_remove=[SwaggerToSdkLabels.in_progress])
            if len(context_tags) == 1 and sdk_pr.mergeable:
                # Merge "single context PRs" automatically
                sdk_pr.merge(merge_method="squash")
        else:
            manage_labels(sdk_pr_as_issue,
                          to_add=[SwaggerToSdkLabels.refused],
                          to_remove=[SwaggerToSdkLabels.in_progress])
            sdk_pr.edit(state="closed")
    else:
        # Try to remove "refused", if it was re-opened
        manage_labels(sdk_pr_as_issue,
                      to_add=[SwaggerToSdkLabels.in_progress],
                      to_remove=[SwaggerToSdkLabels.refused])

    #
    # Extra work: if this was a context PR from a fork
    #
    if is_from_a_fork and len(context_tags) == 1:
        try:
            context_pr = get_or_create_pull(
                sdk_repo,
                title='[AutoPR] {}'.format("/".join(context_tags)),
                body="Created to accumulate context: {}".format(context_tags[0]),
                head=sdk_repo.owner.login+":"+sdk_pr_base,
                base=_DEFAULT_SDK_BRANCH,
            )
        except Exception as err:
            _LOGGER.warning("Unable to create context PR: %s", err)
            return
        # We got the context PR!
        context_pr_as_issue = sdk_repo.get_issue(context_pr.number)
        manage_labels(context_pr_as_issue, [SwaggerToSdkLabels.service_pr])
        # Update dashboar to talk about this PR
        if sdk_pr.merged:
            msg = "The initial (PR)[{}] has been merged into your service PR:\n{}".format(
                sdk_pr.html_url,
                context_pr.html_url
            )
        else:
            msg = "A (PR)[{}] has been created for you based on this PR content.\n\n".format(
                sdk_pr.html_url
            )
            msg += "Once this PR will be merged, content will be added to your service PR:\n{}".format(
                context_pr.html_url
            )
        dashboard.create_comment(msg)

def generate_sdk_from_git_object(git_object, branch_name, restapi_git_id, sdk_git_id, base_branch_names, *, fallback_base_branch_name="master", sdk_tag=None):
    """Generate SDK from a commit or a PR object.

    git_object is the initial commit/PR from the RestAPI repo. restapi_git_id explains where to clone the repo.
    sdk_git_id explains where to push the commit.
    sdk_tag explains what is the tag used in the Readme for the swagger-to-sdk section. If not provided, use sdk_git_id.
    branch_name is the expected branch name in the SDK repo.
    - If this branch exists, use it.
    - If not, use the base branch to create that branch (base branch is where I intend to do my PR)
    - If base_branch_names is not provided, use fallback_base_branch_name as base
    - If this base branch is provided and does not exists, create this base branch first using fallback_base_branch_name (this one is required to exist)

    WARNING:
    This method might push to "branch_name" and "base_branch_name". No push will be made to "fallback_base_branch_name"
    """
    gh_token = os.environ["GH_TOKEN"]
    config_path = CONFIG_FILE
    message_template = DEFAULT_COMMIT_MESSAGE
    autorest_bin = None
    if sdk_tag is None:
        sdk_tag = sdk_git_id

    try:
        checkout_name = git_object.sha # Checkout the sha if commit obj
    except AttributeError:
        checkout_name = git_object.head.ref # Checkout the branch name if PR

    branched_rest_api_id = restapi_git_id+'@'+checkout_name
    branched_sdk_git_id = sdk_git_id+'@'+fallback_base_branch_name

    with tempfile.TemporaryDirectory() as temp_dir, \
            manage_git_folder(gh_token, Path(temp_dir) / Path("rest"), branched_rest_api_id) as restapi_git_folder, \
            manage_git_folder(gh_token, Path(temp_dir) / Path("sdk"), branched_sdk_git_id) as sdk_folder:

        swagger_files_in_commit = get_readme_files_from_git_objects(git_object, restapi_git_folder)
        _LOGGER.info("Files in PR: %s ", swagger_files_in_commit)

        # SDK part
        sdk_repo = Repo(str(sdk_folder))

        for base_branch in base_branch_names:
            _LOGGER.info('Checkout and create %s', base_branch)
            checkout_and_create_branch(sdk_repo, base_branch)

        _LOGGER.info('Try to checkout destination branch %s', branch_name)
        try:
            sdk_repo.git.checkout(branch_name)
            _LOGGER.info('The branch exists.')
        except GitCommandError:
            _LOGGER.info('Destination branch does not exists')
            # Will be created by do_commit

        configure_user(gh_token, sdk_repo)

        config = read_config(sdk_repo.working_tree_dir, config_path)
        global_conf = config["meta"]

        # Look for configuration in Readme
        _LOGGER.info('Extract conf from Readmes for target: %s', sdk_git_id)
        extract_conf_from_readmes(swagger_files_in_commit, restapi_git_folder, sdk_tag, config)
        _LOGGER.info('End of extraction')

        def skip_callback(project, local_conf):
            if not swagger_files_in_commit:
                return True
            markdown_relative_path, optional_relative_paths = get_input_paths(global_conf, local_conf)
            if not (
                    markdown_relative_path in swagger_files_in_commit or
                    any(input_file in swagger_files_in_commit for input_file in optional_relative_paths)):
                _LOGGER.info(f"In project {project} no files involved in this commit")
                return True
            return False

        build_libraries(config, skip_callback, restapi_git_folder,
                        sdk_repo, temp_dir, autorest_bin)

        try:
            commit_for_sha = git_object.commit   # Commit
        except AttributeError:
            commit_for_sha = list(git_object.get_commits())[-1].commit  # PR
        message = message_template + "\n\n" + commit_for_sha.message
        commit_sha = do_commit(sdk_repo, message, branch_name, commit_for_sha.sha)
        if commit_sha:
            for base_branch in base_branch_names:
                sdk_repo.git.push('origin', base_branch, set_upstream=True)
            sdk_repo.git.push('origin', branch_name, set_upstream=True)
            return "https://github.com/{}/commit/{}".format(sdk_git_id, commit_sha)
