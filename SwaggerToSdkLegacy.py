"""Swagger to SDK"""
import shutil
import os
import subprocess
import logging
import json
import re
import datetime
from pathlib import Path

from SwaggerToSdkCore import *

_LOGGER = logging.getLogger(__name__)


def build_autorest_options(language, global_conf, local_conf):
    """Build the string of the Autorest options"""
    merged_options = merge_options(global_conf, local_conf, "autorest_options") or {}

    if "CodeGenerator" not in merged_options:
        merged_options["CodeGenerator"] = "Azure.{}".format(language)

    sorted_keys = sorted(list(merged_options.keys())) # To be honest, just to help for tests...
    return " ".join("-{} {}".format(key, str(merged_options[key])) for key in sorted_keys)

def generate_code(language, swagger_file, output_dir, global_conf, local_conf, autorest_bin=None):
    """Call the Autorest process with the given parameters"""

    autorest_options = build_autorest_options(language, global_conf, local_conf)
    autorest_version = global_conf.get("autorest", LATEST_TAG)

    swagger_path = swagger_file.parent

    if not autorest_bin:
        autorest_bin = shutil.which("autorest")
    if not autorest_bin:
        raise ValueError("No autorest found in PATH and no autorest path option used")

    cmd_line = autorest_bin + " --version={} -i {} -o {} {}"
    cmd_line = cmd_line.format(str(autorest_version),
                               str(swagger_file),
                               str(output_dir),
                               autorest_options)
    _LOGGER.info("Autorest cmd line:\n%s", cmd_line)

    try:
        result = subprocess.check_output(cmd_line.split(),
                                         stderr=subprocess.STDOUT,
                                         universal_newlines=True,
                                         cwd=str(swagger_path))
    except subprocess.CalledProcessError as err:
        _LOGGER.error(err)
        _LOGGER.error(err.output)
        raise
    except Exception as err:
        _LOGGER.error(err)
        raise
    else:
        _LOGGER.info(result)
    # Checks that Autorest did something!
    if not output_dir.is_dir() or next(output_dir.iterdir(), None) is None:
        raise ValueError("Autorest call ended with 0, but no files were generated")



def update(client_generated_path, sdk_root, global_conf, local_conf):
    """Update data from generated to final folder"""
    dest = local_conf['output_dir']
    destination_folder = get_sdk_local_path(sdk_root, dest)

    wrapper_files_or_dirs = merge_options(global_conf, local_conf, "wrapper_filesOrDirs") or []
    delete_files_or_dirs = merge_options(global_conf, local_conf, "delete_filesOrDirs") or []
    generated_relative_base_directory = local_conf.get('generated_relative_base_directory') or \
        global_conf.get('generated_relative_base_directory')

    if generated_relative_base_directory:
        client_possible_path = [elt for elt in client_generated_path.glob(generated_relative_base_directory) if elt.is_dir()]
        try:
            client_generated_path = client_possible_path.pop()
        except IndexError:
            err_msg = "Incorrect generated_relative_base_directory folder: {}".format(generated_relative_base_directory)
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
        build_folder = get_sdk_local_path(sdk_root, build_dir)
        build_file = Path(build_folder, "build.json")
        autorest_version = global_conf.get("autorest", LATEST_TAG)
        with open(build_file, 'w') as build_fd:
            json.dump(build_file_content(autorest_version), build_fd)

def get_sdk_local_path(sdk_root, relative_path):
    build_folder = Path(sdk_root, relative_path)
    if not build_folder.is_dir():
        err_msg = "Folder does not exist or is not accessible: {}".format(
            build_folder)
        _LOGGER.critical(err_msg)
        raise ValueError(err_msg)
    return build_folder


def build_libraries(gh_token, config, project_pattern, restapi_git_folder, sdk_repo, temp_dir, initial_pr, autorest_bin=None):
    """Main method of the the file"""

    global_conf = config["meta"]
    language = global_conf["language"]

    swagger_files_in_pr = get_swagger_project_files_in_pr(initial_pr, restapi_git_folder) if initial_pr else set()
    _LOGGER.info("Files in PR: %s ", swagger_files_in_pr)

    for project, local_conf in config["projects"].items():
        if project_pattern and not any(project.startswith(p) for p in project_pattern):
            _LOGGER.info("Skip project %s", project)
            continue

        relative_swagger_path = Path(local_conf['swagger'])
        if initial_pr and relative_swagger_path not in swagger_files_in_pr:
            _LOGGER.info("Skip project %s since file %s not in PR",
                         project,
                         relative_swagger_path)
            continue

        _LOGGER.info("Working on %s", relative_swagger_path)
        absolute_swagger_path = Path(restapi_git_folder, relative_swagger_path).resolve()

        if not absolute_swagger_path.is_file():
            err_msg = "Swagger file does not exist or is not readable: {}".format(
                absolute_swagger_path)
            _LOGGER.critical(err_msg)
            raise ValueError(err_msg)

        absolute_generated_path = Path(temp_dir, relative_swagger_path.name)
        generate_code(language,
                      absolute_swagger_path, absolute_generated_path,
                      global_conf, local_conf,
                      autorest_bin)
        update(absolute_generated_path, sdk_repo.working_tree_dir, global_conf, local_conf)
