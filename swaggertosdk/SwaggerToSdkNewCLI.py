"""Swagger to SDK"""
import shutil
import logging
import json
from pathlib import Path

from .SwaggerToSdkCore import (
    build_file_content,
    solve_relative_path,
    get_input_paths
)
from .autorest_tools import (
    execute_simple_command,
    generate_code,
    merge_options,
)

_LOGGER = logging.getLogger(__name__)


def move_wrapper_files_or_dirs(src_root, dst_root, global_conf, local_conf):
    """Save wrapper files somewhere for replace them after generation.
    """
    src_relative_path = local_conf.get('output_dir', '')
    src_abs_path = Path(src_root, src_relative_path)
    dst_abs_path = Path(dst_root, src_relative_path)

    wrapper_files_or_dirs = merge_options(global_conf, local_conf, "wrapper_filesOrDirs") or []

    for wrapper_file_or_dir in wrapper_files_or_dirs:
        for file_path in src_abs_path.glob(wrapper_file_or_dir):
            relative_file_path = file_path.relative_to(src_abs_path)
            file_path_dest = Path(dst_abs_path, relative_file_path)
            if file_path.is_file():
                file_path_dest.parent.mkdir(parents=True, exist_ok=True)
            _LOGGER.info("Moving %s to %s", str(file_path), str(file_path_dest))
            # This does not work in Windows if generatd and dest are not in the same drive
            # file_path.replace(file_path_dest)
            shutil.move(file_path, file_path_dest)


def delete_extra_files(sdk_root, global_conf, local_conf):
    src_relative_path = local_conf.get('output_dir', '')
    src_abs_path = Path(sdk_root, src_relative_path)

    delete_files_or_dirs = merge_options(global_conf, local_conf, "delete_filesOrDirs") or []

    for delete_file_or_dir in delete_files_or_dirs:
        for file_path in src_abs_path.glob(delete_file_or_dir):
            if file_path.is_file():
                file_path.unlink()
            else:
                shutil.rmtree(str(file_path))


def move_autorest_files(client_generated_path, sdk_root, global_conf, local_conf):
    """Update data from generated to final folder.

    This is one only if output_dir is set, otherwise it's considered generated in place 
    and does not required moving
    """
    dest = local_conf.get('output_dir', None)
    if not dest:
        return
    destination_folder = get_local_path_dir(sdk_root, dest)

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

    shutil.rmtree(str(destination_folder))
    # This does not work in Windows if generatd and dest are not in the same drive
    # client_generated_path.replace(destination_folder)
    shutil.move(client_generated_path, destination_folder)


def write_build_file(sdk_root, local_conf):
    build_dir = local_conf.get('build_dir')
    if build_dir:
        build_folder = get_local_path_dir(sdk_root, build_dir)
        build_file = Path(build_folder, "build.json")
        with open(build_file, 'w') as build_fd:
            json.dump(build_file_content(), build_fd, indent=2)


def execute_after_script(sdk_root, global_conf, local_conf):
    after_scripts = merge_options(global_conf, local_conf, "after_scripts", keep_list_order=True) or []
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


def build_project(temp_dir, project, absolute_markdown_path, sdk_folder, global_conf, local_conf, autorest_bin=None):
    absolute_generated_path = Path(temp_dir, project)
    absolute_save_path = Path(temp_dir, "save")
    move_wrapper_files_or_dirs(sdk_folder, absolute_save_path, global_conf, local_conf)
    generate_code(absolute_markdown_path,
                  global_conf,
                  local_conf,
                  absolute_generated_path if "output_dir" in local_conf else None,
                  autorest_bin)
    move_autorest_files(absolute_generated_path, sdk_folder, global_conf, local_conf)
    move_wrapper_files_or_dirs(absolute_save_path, sdk_folder, global_conf, local_conf)
    delete_extra_files(sdk_folder, global_conf, local_conf)
    write_build_file(sdk_folder, local_conf)
    execute_after_script(sdk_folder, global_conf, local_conf)


def build_libraries(config, skip_callback, restapi_git_folder, sdk_repo, temp_dir, autorest_bin=None):
    """Main method of the the file"""

    global_conf = config["meta"]
    global_conf["autorest_options"] = solve_relative_path(global_conf.get("autorest_options", {}), sdk_repo.working_tree_dir)


    for project, local_conf in config.get("projects", {}).items():
        if skip_callback(project, local_conf):
            _LOGGER.info("Skip project %s", project)
            continue
        local_conf["autorest_options"] = solve_relative_path(local_conf.get("autorest_options", {}), sdk_repo.working_tree_dir)

        markdown_relative_path, optional_relative_paths = get_input_paths(global_conf, local_conf)
        _LOGGER.info(f"Markdown input: {markdown_relative_path}")
        _LOGGER.info(f"Optional inputs: {optional_relative_paths}")

        absolute_markdown_path = None
        if markdown_relative_path:
            absolute_markdown_path = Path(restapi_git_folder, markdown_relative_path).resolve()
        if optional_relative_paths:
            local_conf.setdefault('autorest_options', {})['input-file'] = [
                Path(restapi_git_folder, input_path).resolve()
                for input_path
                in optional_relative_paths
            ]

        sdk_folder = sdk_repo.working_tree_dir
        build_project(
            temp_dir,
            project,
            absolute_markdown_path,
            sdk_folder,
            global_conf,
            local_conf,
            autorest_bin
        )
