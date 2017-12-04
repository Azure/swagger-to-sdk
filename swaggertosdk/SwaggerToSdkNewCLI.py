"""Swagger to SDK"""
import shutil
import subprocess
import logging
import json
import os.path
from pathlib import Path
import yaml

from .SwaggerToSdkCore import (
    build_file_content,
    merge_options,
    get_documents_in_composite_file,
    get_swagger_project_files_in_pr,
    get_composite_file_as_json
)

_LOGGER = logging.getLogger(__name__)


def build_autorest_options(global_conf, local_conf):
    """Build the string of the Autorest options"""
    merged_options = merge_options(global_conf, local_conf, "autorest_options") or {}
    def value(x):
        escaped = x if " " not in x else "'"+x+"'"
        return "={}".format(escaped) if escaped else ""
    listify = lambda x: x if isinstance(x, list) else [x]

    sorted_keys = sorted(list(merged_options.keys())) # To be honest, just to help for tests...
    return [
        "--{}{}".format(key.lower(), value(str(option)))
        for key in sorted_keys
        for option in listify(merged_options[key])
    ]

def generate_code(input_file, output_dir, global_conf, local_conf, autorest_bin=None):
    """Call the Autorest process with the given parameters.

    Input file can be a Path instance, a str (will be cast to Path), or a str starting with
    http (will be passed to Autorest as is).
    """
    if not autorest_bin:
        autorest_bin = shutil.which("autorest")
    if not autorest_bin:
        raise ValueError("No autorest found in PATH and no autorest path option used")

    params = [str(input_file)] if input_file else []
    params.append("--output-folder={}".format(str(output_dir)+os.path.sep))
    params += build_autorest_options(global_conf, local_conf)

    input_files = local_conf.get("autorest_options", {}).get("input-file", [])

    if not input_file and not input_files:
        raise ValueError("I don't have input files!")

    path_input_files = [pit for pit in input_files if isinstance(pit, Path)]
    if input_file and isinstance(input_file, Path):
        input_path = input_file.parent
    elif path_input_files:
        input_path = path_input_files[0].parent
    else:
        input_path = Path(".")

    cmd_line = autorest_bin.split()
    cmd_line += params
    _LOGGER.info("Autorest cmd line:\n%s", " ".join(cmd_line))

    execute_simple_command(cmd_line, cwd=str(input_path))
    # Checks that Autorest did something!
    if not output_dir.is_dir() or next(output_dir.iterdir(), None) is None:
        raise ValueError("Autorest call ended with 0, but no files were generated")


def execute_simple_command(cmd_line, cwd=None, shell=False):
    try:
        result = subprocess.check_output(cmd_line,
                                         stderr=subprocess.STDOUT,
                                         universal_newlines=True,
                                         cwd=cwd,
                                         shell=shell)
    except subprocess.CalledProcessError as err:
        _LOGGER.error(err)
        _LOGGER.error(err.output)
        raise
    except Exception as err:
        _LOGGER.error(err)
        raise
    else:
        _LOGGER.info(result)


def update(client_generated_path, sdk_root, global_conf, local_conf):
    """Update data from generated to final folder"""
    dest = local_conf['output_dir']
    destination_folder = get_local_path_dir(sdk_root, dest)

    wrapper_files_or_dirs = merge_options(global_conf, local_conf, "wrapper_filesOrDirs") or []
    delete_files_or_dirs = merge_options(global_conf, local_conf, "delete_filesOrDirs") or []
    generated_relative_base_directory = local_conf.get('generated_relative_base_directory') or \
        global_conf.get('generated_relative_base_directory')

    if generated_relative_base_directory:
        client_possible_path = [elt for elt in client_generated_path.glob(generated_relative_base_directory) if elt.is_dir()]
        try:
            client_generated_path = client_possible_path.pop()
        except IndexError:
            err_msg = "Incorrect generated_relative_base_directory folder: {}\n".format(generated_relative_base_directory)
            err_msg += "Base folders were: : {}\n".format([f.relative_to(client_generated_path) for f in client_generated_path.iterdir()])
            _LOGGER.critical(err_msg)
            raise ValueError(err_msg)
        if client_possible_path:
            err_msg = "generated_relative_base_directory parameter is ambiguous: {} {}".format(
                client_generated_path,
                client_possible_path
            )
            _LOGGER.critical(err_msg)
            raise ValueError(err_msg)

    for wrapper_file_or_dir in wrapper_files_or_dirs:
        for file_path in destination_folder.glob(wrapper_file_or_dir):
            relative_file_path = file_path.relative_to(destination_folder)
            file_path_dest = client_generated_path.joinpath(str(relative_file_path))
            # This does not work in Windows if generatd and dest are not in the same drive
            # file_path.replace(file_path_dest)
            shutil.move(file_path, file_path_dest)

    for delete_file_or_dir in delete_files_or_dirs:
        for file_path in client_generated_path.glob(delete_file_or_dir):
            if file_path.is_file():
                file_path.unlink()
            else:
                shutil.rmtree(str(file_path))

    shutil.rmtree(str(destination_folder))
    # This does not work in Windows if generatd and dest are not in the same drive
    # client_generated_path.replace(destination_folder)
    shutil.move(client_generated_path, destination_folder)

    build_dir = local_conf.get('build_dir')
    if build_dir:
        build_folder = get_local_path_dir(sdk_root, build_dir)
        build_file = Path(build_folder, "build.json")
        with open(build_file, 'w') as build_fd:
            json.dump(build_file_content(), build_fd, indent=2)


def execute_after_script(sdk_root, global_conf, local_conf):
    after_scripts = merge_options(global_conf, local_conf, "after_scripts") or []
    for script in after_scripts:
        _LOGGER.info("Execute after script: %s", script)
        execute_simple_command(script, cwd=sdk_root, shell=True)


def get_local_path_dir(root, relative_path):
    build_folder = Path(root, relative_path)
    if not build_folder.is_dir():
        err_msg = "Folder does not exist or is not accessible: {}".format(
            build_folder)
        _LOGGER.critical(err_msg)
        raise ValueError(err_msg)
    return build_folder


def get_input_paths(global_conf, local_conf):
    """Returns a 3-tuple:
    - Markdown Path or None
    - Input-file Paths or empty list
    - Composite file or None
    """
    del global_conf # Unused

    relative_markdown_path = None # Markdown is optional
    input_files = [] # Input file could be empty
    relative_composite_path = None # Composite is optional
    if "markdown" in local_conf:
        relative_markdown_path = Path(local_conf['markdown'])
    if "composite" in local_conf:
        relative_composite_path = Path(local_conf['composite'])
    input_files = local_conf.get('autorest_options', {}).get('input-file', [])
    if input_files and not isinstance(input_files, list):
        input_files = [input_files]
    input_files = [Path(input_file) for input_file in input_files]
    if not relative_markdown_path and not input_files and not relative_composite_path:
        raise ValueError("No input file found")
    if (relative_markdown_path or input_files) and relative_composite_path:
        raise ValueError("You cannot configure composite and markdown/input-file at the same time")
    return (relative_markdown_path, input_files, relative_composite_path)

def convert_composite_to_markdown(composite_full_path):
    optional_relative_paths = get_documents_in_composite_file(composite_full_path)
    composite_json = get_composite_file_as_json(composite_full_path)

    configuration = {
        'override-info': {
            'title': composite_json["info"]["title"],
            'description': composite_json["info"]["description"],
        },
        'input-file': [str(p) for p in optional_relative_paths]
    }
    configuration_as_yaml = yaml.dump(configuration, default_flow_style=False)
    configuration_as_md = f"# My API\n> see https://aka.ms/autorest\n```yaml\n{configuration_as_yaml}\n```\n"
    _LOGGER.warning(f"Built MD file from composite:\n{configuration_as_md}")
    return configuration_as_md


def solve_relative_path(conf, sdk_root):
    """Solve relative path in conf.

    If a key is prefixed by "sdkrel:", it's solved against SDK root.
    """
    SDKRELKEY = "sdkrel:"
    solved_conf = {}
    for key, value in conf.items():
        if key.startswith(SDKRELKEY):
            subkey = key[len(SDKRELKEY):]
            solved_value = Path(sdk_root, value).resolve()
            solved_conf[subkey] = str(solved_value)
        else:
            solved_conf[key] = value
    return solved_conf


def build_libraries(config, project_pattern, restapi_git_folder, sdk_repo, temp_dir, initial_pr, autorest_bin=None):
    """Main method of the the file"""

    global_conf = config["meta"]
    global_conf = solve_relative_path(global_conf, sdk_repo.working_tree_dir)

    swagger_files_in_pr = get_swagger_project_files_in_pr(initial_pr, restapi_git_folder) if initial_pr else set()
    _LOGGER.info("Files in PR: %s ", swagger_files_in_pr)

    for project, local_conf in config["projects"].items():
        if project_pattern and not any(project.startswith(p) for p in project_pattern):
            _LOGGER.info("Skip project %s", project)
            continue
        local_conf = solve_relative_path(local_conf, sdk_repo.working_tree_dir)

        markdown_relative_path, optional_relative_paths, composite_relative_path = get_input_paths(global_conf, local_conf)

        if initial_pr and not (
                markdown_relative_path in swagger_files_in_pr or
                composite_relative_path in swagger_files_in_pr or
                any(input_file in swagger_files_in_pr for input_file in optional_relative_paths)):
            _LOGGER.info(f"Skip project {project} since no files involved in this PR")
            continue

        _LOGGER.info(f"Markdown input: {markdown_relative_path}")
        _LOGGER.info(f"Optional inputs: {optional_relative_paths}")
        _LOGGER.info(f"Composite input: {composite_relative_path}")

        absolute_markdown_path = None
        if markdown_relative_path:
            absolute_markdown_path = Path(restapi_git_folder, markdown_relative_path).resolve()
        if optional_relative_paths:
            local_conf.setdefault('autorest_options', {})['input-file'] = [
                Path(restapi_git_folder, input_path).resolve()
                for input_path
                in optional_relative_paths
            ]
        if composite_relative_path:
            composite_full_path = Path(restapi_git_folder, composite_relative_path).resolve()
            md_content_from_composite = convert_composite_to_markdown(composite_full_path)
            absolute_markdown_path = Path(temp_dir, "composite.md").resolve()
            with open(absolute_markdown_path, "w") as tmp_fd:
                tmp_fd.write(md_content_from_composite)

        absolute_generated_path = Path(temp_dir, project)
        generate_code(absolute_markdown_path,
                      absolute_generated_path,
                      global_conf,
                      local_conf,
                      autorest_bin)
        update(absolute_generated_path, sdk_repo.working_tree_dir, global_conf, local_conf)
        execute_after_script(sdk_repo.working_tree_dir, global_conf, local_conf)
