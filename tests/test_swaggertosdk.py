import json
import unittest.mock
import os.path
import logging
import tempfile
from pathlib import Path
logging.basicConfig(level=logging.INFO)

from github import Github

from swaggertosdk.SwaggerToSdkCore import (
    get_documents_in_markdown_file,
    get_swagger_project_files_in_git_object,
    get_swagger_files_in_git_object,
    swagger_index_from_markdown,
    add_comment_to_initial_pr,
    get_pr_from_travis_commit_sha,
    build_file_content,
    extract_conf_from_readmes,
)
from swaggertosdk.github_tools import get_full_sdk_id
from swaggertosdk.SwaggerToSdkNewCLI import (
    solve_relative_path,
    get_input_paths,
    move_wrapper_files_or_dirs,
    delete_extra_files,
    write_build_file,
    move_autorest_files
)

CWD = os.path.dirname(os.path.realpath(__file__))

def get_pr(github_client, repo_id, pr_number):
    repo = github_client.get_repo(repo_id)
    return repo.get_pull(int(pr_number))

def get_commit(github_client, repo_id, sha):
    repo = github_client.get_repo(repo_id)
    return repo.get_commit(sha)

def test_extract_md_with_tag():
    docs = get_documents_in_markdown_file(Path('files/readme_tag.md_test'), base_dir=Path(CWD))
    assert len(docs) == 29


def test_solve_relative_path():
    conf = {
        "test": "basicvalue",
        "sdkrel:retest": "."
    }
    
    solved_conf = solve_relative_path(conf, "/tmp")
    print(solved_conf)
    assert len(solved_conf) == 2
    assert solved_conf["test"] == "basicvalue"
    assert solved_conf["retest"] in  ["/tmp", "C:\\tmp", "D:\\tmp"] # Cross platform tests

def test_get_swagger_project_files_in_git_object(github_client):
    swaggers = get_swagger_project_files_in_git_object(get_pr(github_client, 'Azure/azure-rest-api-specs', 1422), base_dir=Path(CWD))
    for s in swaggers:
        assert isinstance(s, Path)
        assert s in [
            Path('specification/compute/resource-manager/Microsoft.Compute/2017-03-30/compute.json'),
            Path('files/readme.md')
        ]
    assert len(swaggers) == 2


def test_swagger_index_from_markdown():
    assert \
        {
            Path('specification/compute/resource-manager/Microsoft.Compute/2017-03-30/compute.json'):
                Path('files/readme.md'),
        } == \
        swagger_index_from_markdown(Path(CWD))


def test_get_git_files(github_client):
    # Basic test, one Swagger file only (PR)
    assert \
        get_swagger_files_in_git_object(get_pr(github_client, 'Azure/azure-rest-api-specs', 1422)) \
        == \
        {Path('specification/compute/resource-manager/Microsoft.Compute/2017-03-30/compute.json')}

    # Basic test, one Readme file only (PR)
    assert \
        get_swagger_files_in_git_object(get_pr(github_client, 'lmazuel/azure-rest-api-specs', 12)) \
        == \
        {Path('specification/cdn/resource-manager/readme.md')}

    # Basic test, one Swagger file only (commit)
    assert \
        get_swagger_files_in_git_object(get_commit(github_client, 'Azure/azure-rest-api-specs', 'ae25a0505f86349bbe92251dde34d70bfb6be78a')) \
        == \
        {Path('specification/cognitiveservices/data-plane/EntitySearch/v1.0/EntitySearch.json')}

    # Should not find Swagger and not fails
    assert \
        get_swagger_files_in_git_object(get_pr(github_client, 'Azure/azure-sdk-for-python', 627)) \
        == \
        set()


def test_add_comment_to_pr(github_token):
    travis_mock_env = dict(os.environ)
    travis_mock_env['TRAVIS'] = 'true'
    travis_mock_env['TRAVIS_REPO_SLUG'] = 'lmazuel/TestingRepo'
    travis_mock_env['TRAVIS_COMMIT'] = 'dd82f65f1b6314b18609b8572464b6d328ea70d4'
    travis_mock_env['TRAVIS_PULL_REQUEST'] = 'false'

    with unittest.mock.patch.dict('os.environ', travis_mock_env):
        assert add_comment_to_initial_pr(github_token, 'My comment')

    del travis_mock_env['TRAVIS_COMMIT']
    travis_mock_env['TRAVIS_PULL_REQUEST'] = '1'

    with unittest.mock.patch.dict('os.environ', travis_mock_env):
        assert add_comment_to_initial_pr(github_token, 'My comment')

def test_get_pr_from_travis_commit_sha(github_token):
    travis_mock_env = dict(os.environ)
    travis_mock_env['TRAVIS'] = 'true'
    travis_mock_env['TRAVIS_REPO_SLUG'] = 'Azure/azure-sdk-for-python'
    travis_mock_env['TRAVIS_COMMIT'] = '497955507bc152c444bd1785f34cafefc7e4e8d9'

    with unittest.mock.patch.dict('os.environ', travis_mock_env):
        pr_obj = get_pr_from_travis_commit_sha(github_token)
    assert pr_obj is not None
    assert pr_obj.number == 568

    travis_mock_env['TRAVIS_COMMIT'] = 'c290e668f17b45be6619f9133c0f15af19144280'
    with unittest.mock.patch.dict('os.environ', travis_mock_env):
        pr_obj = get_pr_from_travis_commit_sha(github_token)
    assert pr_obj is None


def test_get_input_path():
    main, opt = get_input_paths(
        {},
        {"autorest_options": {
            "input-file": ['a', 'b']
        }}
    )
    assert main is None
    assert [Path('a'), Path('b')] == opt

    main, opt = get_input_paths(
        {},
        {"autorest_options": {
            "input-file": ['a', 'b']
        }, "markdown":"c"}
    )
    assert Path('c') == main
    assert [Path('a'), Path('b')] == opt


@unittest.mock.patch('swaggertosdk.SwaggerToSdkCore.autorest_latest_version_finder')
def test_build(mocked_autorest_latest_version_finder):
    build = build_file_content()
    assert 'autorest' in build

def test_move_wrapper_files_or_dirs():
    with tempfile.TemporaryDirectory() as temp_dir:
        output = Path(temp_dir, 'output')
        output.mkdir()

        save_dest = Path(temp_dir, 'save')
        save_dest.mkdir()

        Path(output, 'folder').mkdir()
        Path(output, 'to_keep.txt').write_bytes(b'My content')
        Path(output, 'to_keep_pattern.txt').write_bytes(b'My content')

        move_wrapper_files_or_dirs(
            output,
            save_dest,
            {'wrapper_filesOrDirs': [
                'to_keep.txt',
                'to_*_pattern.txt',
                'dont_exist_no_big_deal.txt',
                'folder'
            ]},
            {
                'output_dir': '.'
            }
        )

        assert Path(save_dest, 'to_keep.txt').exists()
        assert Path(save_dest, 'to_keep_pattern.txt').exists()
        assert Path(save_dest, 'folder').exists()

    with tempfile.TemporaryDirectory() as temp_dir:
        output = Path(temp_dir, 'output')
        output.mkdir()
        subdir = Path(output, 'subdir')
        subdir.mkdir()

        save_dest = Path(temp_dir, 'save')
        save_dest.mkdir()

        Path(subdir, 'folder').mkdir()
        Path(subdir, 'to_keep.txt').write_bytes(b'My content')
        Path(subdir, 'to_keep_pattern.txt').write_bytes(b'My content')

        move_wrapper_files_or_dirs(
            output,
            save_dest,
            {'wrapper_filesOrDirs': [
                'to_keep.txt',
                'to_*_pattern.txt',
                'dont_exist_no_big_deal.txt',
                'folder'
            ]},
            {
                'output_dir': 'subdir'
            }
        )

        save_sub = Path(save_dest, 'subdir')
        assert Path(save_sub, 'to_keep.txt').exists()
        assert Path(save_sub, 'to_keep_pattern.txt').exists()
        assert Path(save_sub, 'folder').exists()

def test_delete_extra_files():
    with tempfile.TemporaryDirectory() as temp_dir:
        output = Path(temp_dir, 'output')
        output.mkdir()

        Path(output, 'generated.txt').write_bytes(b'My content')
        Path(output, 'dont_need_this.txt').write_bytes(b'My content')
        Path(output, 'del_folder').mkdir()

        delete_extra_files(
            output,
            {'delete_filesOrDirs': [
                'dont_need_this.txt',
                'dont_exist_no_big_deal_2.txt',
                'del_folder'
            ]},
            {}
        )

        assert not Path(output, 'erase.txt').exists()
        assert not Path(output, 'dont_need_this.txt').exists()
        assert not Path(output, 'del_folder').exists()

@unittest.mock.patch('swaggertosdk.SwaggerToSdkCore.autorest_latest_version_finder')
def test_write_build_file(mocked_autorest_latest_version_finder):
    mocked_autorest_latest_version_finder.return_value = '123'
    with tempfile.TemporaryDirectory() as temp_dir:
        write_build_file(
            temp_dir,
            {
                'build_dir': '.'
            }
        )
        with open(Path(temp_dir, 'build.json'), 'r') as build_fd:
            data = json.load(build_fd)
            assert '123' == data['autorest']

        output = Path(temp_dir, 'output')
        output.mkdir()
        write_build_file(
            temp_dir,
            {
                'build_dir': 'output'
            }
        )
        with open(Path(output, 'build.json'), 'r') as build_fd:
            data = json.load(build_fd)
            assert '123' == data['autorest']

def test_move_autorest_files():
    with tempfile.TemporaryDirectory() as temp_dir:
        generated = Path(temp_dir, 'generated')
        generated.mkdir()
        generated_subfolder = generated.joinpath('inside')
        generated_subfolder.mkdir()

        output = Path(temp_dir, 'output')
        output.mkdir()

        Path(generated_subfolder, 'generated.txt').write_bytes(b'My content')
        Path(output, 'erase.txt').write_bytes(b'My content')

        move_autorest_files(
            generated,
            output,
            {'generated_relative_base_directory': '*side'}, 
            {
                'output_dir': '.'
            }
        )

        assert Path(output, 'generated.txt').exists()
        assert not Path(output, 'erase.txt').exists()

@unittest.mock.patch('swaggertosdk.autorest_tools.execute_simple_command')
def test_extract_conf_from_readmes(mocked_execute_simple_command):
    def side_effect(*args, **kwargs):
        output_param = args[0][-1]
        output_path = Path(output_param[len("--output-folder="):])
        Path(output_path, "configuration.json").write_text(
            json.dumps({
                "swagger-to-sdk": [
                {},
                {
                    "repo": "azure-sdk-for-python"
                }
                ],
            })
        )
    mocked_execute_simple_command.side_effect = side_effect

    swagger_files_in_pr = {Path("readme.md")}
    sdk_git_id = "Giberish/azure-sdk-for-python"  # Whatever the user, should not count
    config = {}
    extract_conf_from_readmes(swagger_files_in_pr, Path(CWD, "files"), sdk_git_id, config)

    assert "projects" in config
    assert len(config["projects"]) == 1
    key = list(config["projects"].keys())[0]
    assert "readme.md" in key
    assert "readme.md" in config["projects"][key]["markdown"]
    print(config)

    config = {
        "projects": {
            "dns": {
                "markdown": "myreadmd.md"
            }
        }
    }
    extract_conf_from_readmes(swagger_files_in_pr, Path(CWD, "files"), sdk_git_id, config)

    assert len(config["projects"]) == 2
