import os.path
from pathlib import Path
import shutil
import tempfile
from subprocess import CalledProcessError
from unittest.mock import MagicMock, patch

import pytest

from swaggertosdk.autorest_tools import (
    build_autorest_options,
    merge_options,
    generate_code,
    autorest_swagger_to_sdk_conf,
    execute_simple_command,
)

CWD = os.path.dirname(os.path.realpath(__file__))


def test_execute_simple_command():
    # This test needs to be compatible with both Windows and Linux...
    output = execute_simple_command(["python", "--version"])
    assert "Python" in output

    try:
        execute_simple_command(["python", "--oiuyertuyerituy"])
        pytest.fail("This should raise an exception")
    except CalledProcessError as err:
        assert "python -h" in err.output

def test_build_autorest_options():
    line = build_autorest_options({"autorest_options": {"A": "value"}}, {"autorest_options": {"B": "value value"}})
    assert line == ["--a=value", "--b='value value'"]

    line = build_autorest_options({"autorest_options": {"A": "value"}}, {"autorest_options": {"B": ["value1", "value2"]}})
    assert line == ["--a=value", "--b=value1", "--b=value2"]

    line = build_autorest_options({"autorest_options": {"A": "value"}}, {"autorest_options": {"A": "newvalue"}})
    assert line == ["--a=newvalue"]

    line = build_autorest_options({}, {})
    assert line == []

    line = build_autorest_options({"autorest_options": {"A": 12, "B": True, "C": ''}}, {})
    assert line == ["--a=12", "--b=True", "--c"]

def test_merge_options():
    result = merge_options({}, {}, 'key')
    assert not result

    result = merge_options({'a': [1, 2, 3]}, {'a': [3, 4, 5]}, 'a')
    assert set(result) == {1, 2, 3, 4, 5}

    result = merge_options({'a': [1, 2, 3]}, {}, 'a')
    assert set(result) == {1, 2, 3}

    result = merge_options({}, {'a': [3, 4, 5]}, 'a')
    assert set(result) == {3, 4, 5}

    result = merge_options({'a': {1: 2, 2: 3}}, {'a': {3: 4, 2: 3}}, 'a')
    assert result == {1: 2, 2: 3, 3: 4}

    global_dict = {'after_scripts': [
        'gofmt -w ./services/',
        'go get -u github.com/Azure/azure-sdk-for-go/tools/profileBuilder',
        'profileBuilder -s list -l ./profiles/2017-03-09/defintion.txt -name 2017-03-09',
        'profileBuilder -s preview -name preview',
        'profileBuilder -s latest -name latest'
    ]}
    result = merge_options(global_dict, {'after_scripts': []}, 'after_scripts', keep_list_order=True)
    assert result == [
        'gofmt -w ./services/',
        'go get -u github.com/Azure/azure-sdk-for-go/tools/profileBuilder',
        'profileBuilder -s list -l ./profiles/2017-03-09/defintion.txt -name 2017-03-09',
        'profileBuilder -s preview -name preview',
        'profileBuilder -s latest -name latest'
    ]

def test_generate_code(monkeypatch):
    mocked_check_output = MagicMock()
    monkeypatch.setattr('swaggertosdk.autorest_tools.execute_simple_command', mocked_check_output)

    generate_code(
        Path('/a/b/c/swagger.md'),
        {"autorest_markdown_cli": True},
        {"autorest_options":{
            "java": '',
            'azure-arm': True,
            "description": "I am a spaced description",
            'input-file': [Path('/a/b/c/swagger.json')]}
        },
        Path('/'),
        "node myautorest"
    )
    call_args = mocked_check_output.call_args
    expected = [
        'node',
        'myautorest',
        str(Path('/a/b/c/swagger.md')),
        '--output-folder={}{}'.format(str(Path('/')),str(Path('/'))),
        '--azure-arm=True',
        "--description='I am a spaced description'",
        '--input-file={}'.format(str(Path('/a/b/c/swagger.json'))),
        '--java',
    ]
    assert call_args[0][0] == expected
    assert call_args[1]['cwd'] ==  str(Path('/a/b/c/'))

    generate_code(
        '/a/b/c/swagger.md',
        {},
        {},
        Path('/'),            
        autorest_bin = "node autorest"
    )
    call_args = mocked_check_output.call_args
    expected = [
        'node',
        'autorest',
        '/a/b/c/swagger.md',
        '--output-folder={}{}'.format(str(Path('/')),str(Path('/'))),
    ]
    assert call_args[0][0] == expected


def test_generate_code_no_autorest_in_path(monkeypatch):
    mocked_check_output = MagicMock()
    monkeypatch.setattr('swaggertosdk.autorest_tools.execute_simple_command', mocked_check_output)
    
    with tempfile.TemporaryDirectory() as temp_dir, pytest.raises(ValueError) as cm, patch('shutil.which') as which:
        which.return_value = None
        generate_code(
            Path('/a/b/c/swagger.json'),
            {},
            {},
            Path(temp_dir),                
        )
    the_exception = cm.value
    assert "No autorest found in PATH and no autorest path option used" in str(the_exception)


def test_generate_code_fail(monkeypatch):
    mocked_check_output = MagicMock()
    monkeypatch.setattr('swaggertosdk.autorest_tools.execute_simple_command', mocked_check_output)

    with tempfile.TemporaryDirectory() as temp_dir, pytest.raises(ValueError) as cm:
        generate_code(
            Path('/a/b/c/swagger.json'),
            {},
            {},
            Path(temp_dir),               
            "node autorest",
        )
    the_exception = cm.value
    assert "no files were generated" in str(the_exception)


def test_autorest_swagger_to_sdk_conf(monkeypatch):
    mocked_check_output = MagicMock()
    monkeypatch.setattr('swaggertosdk.autorest_tools.execute_simple_command', mocked_check_output)

    readme_path = Path(CWD, "files", "readme.md")
    temp_dir = Path(CWD, "files")
    conf = autorest_swagger_to_sdk_conf(readme_path, temp_dir)

    assert len(conf) == 1
    assert conf[0]["repo"] == "Azure/azure-sdk-for-python"

    with tempfile.TemporaryDirectory() as temp_dir:
        Path(temp_dir, "configuration.json").write_text(r"{}")
        conf = autorest_swagger_to_sdk_conf(readme_path, temp_dir)
    assert len(conf) == 0
        