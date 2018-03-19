import json
import unittest.mock
import os.path
import logging
import tempfile
from pathlib import Path

from swaggertosdk.SwaggerToSdkCore import (
    build_file_content,
    extract_conf_from_readmes,
    get_context_tag_from_git_object,
    get_readme_files_from_git_object,
)
from swaggertosdk.SwaggerToSdkNewCLI import (
    solve_relative_path,
    get_input_paths,
    move_wrapper_files_or_dirs,
    delete_extra_files,
    write_build_file,
    move_autorest_files
)

logging.basicConfig(level=logging.INFO)

CWD = os.path.dirname(os.path.realpath(__file__))

def get_pr(github_client, repo_id, pr_number):
    repo = github_client.get_repo(repo_id)
    return repo.get_pull(int(pr_number))

def get_commit(github_client, repo_id, sha):
    repo = github_client.get_repo(repo_id)
    return repo.get_commit(sha)


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

def test_get_context_tag_from_git_object(github_client):
    context_tags = get_context_tag_from_git_object(get_pr(github_client, 'Azure/azure-rest-api-specs', 2412))
    assert len(context_tags) == 1
    assert 'servicefabric/data-plane' in context_tags

    context_tags = get_context_tag_from_git_object(get_pr(github_client, 'Azure/azure-rest-api-specs', 2411))
    assert len(context_tags) == 2
    assert 'mysql/resource-manager' in context_tags
    assert 'postgresql/resource-manager' in context_tags

    context_tags = get_context_tag_from_git_object(get_pr(github_client, 'Azure/azure-rest-api-specs', 2398))
    assert len(context_tags) == 0

    context_tags = get_context_tag_from_git_object(get_pr(github_client, 'Azure/azure-rest-api-specs', 2413))
    assert len(context_tags) == 2
    assert 'cognitiveservices/data-plane/CustomVision/Prediction' in context_tags
    assert 'cognitiveservices/data-plane/CustomVision/Training' in context_tags

    context_tags = get_context_tag_from_git_object(get_pr(github_client, 'Azure/azure-rest-api-specs', 2422))
    assert len(context_tags) == 1
    assert 'managementpartner/resource-manager' in context_tags

    context_tags = get_context_tag_from_git_object(get_pr(github_client, 'Azure/azure-rest-api-specs', 2473))
    assert len(context_tags) == 1
    assert 'datafactory/resource-manager' in context_tags

    context_tags = get_context_tag_from_git_object(get_pr(github_client, 'Azure/azure-rest-api-specs', 2658))
    assert len(context_tags) == 1
    assert 'applicationinsights/resource-manager' in context_tags

def test_get_readme_files_from_git_object(github_client):
    readme_files = get_readme_files_from_git_object(get_pr(github_client, 'Azure/azure-rest-api-specs', 2473), base_dir=Path(CWD) / Path("files"))
    assert len(readme_files) == 1
    readme_file = readme_files.pop()
    assert readme_file == Path("specification/datafactory/resource-manager/readme.md")

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
