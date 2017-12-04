[![Build Status](https://travis-ci.org/lmazuel/swagger-to-sdk.svg?branch=master)](https://travis-ci.org/lmazuel/swagger-to-sdk) 
[![Coverage Status](https://coveralls.io/repos/github/lmazuel/swagger-to-sdk/badge.svg?branch=master)](https://coveralls.io/github/lmazuel/swagger-to-sdk?branch=master)

The SwaggerToSDK script is the automation script launched at each commit on any Swagger files to provide:
- Testing against SDK language
- Automatic PR on each language SDK

This is Python 3.6 only.

This works is still in progress and move fast. We'll do our best to keep this page up-to-date.

# Configuration of the script

```bash
usage: SwaggerToSdk.py [-h] [--rest-folder RESTAPI_GIT_FOLDER]
                       [--pr-repo-id PR_REPO_ID] [--message MESSAGE]
                       [--project PROJECT] [--base-branch BASE_BRANCH]
                       [--branch BRANCH] [--config CONFIG_PATH]
                       [--autorest AUTOREST_DIR] [-v] [--debug]
                       sdk_git_id

Build SDK using Autorest and push to Github. The GH_TOKEN environment variable needs to be set to act on Github.

positional arguments:
  sdk_git_id            The SDK Github id. If a simple string, consider it belongs to the GH_TOKEN owner repo. Otherwise, you can use the syntax username/repoid

optional arguments:
  -h, --help            show this help message and exit
  --rest-folder RESTAPI_GIT_FOLDER, -r RESTAPI_GIT_FOLDER
                        Rest API git folder. [default: .]
  --pr-repo-id PR_REPO_ID
                        PR repo id. If not provided, no PR is done
  --message MESSAGE, -m MESSAGE
                        Force commit message. {hexsha} will be the current REST SHA1 [default: Generated from {hexsha}]
  --project PROJECT, -p PROJECT
                        Select a specific project. Do all by default. You can use a substring for several projects.
  --base-branch BASE_BRANCH, -o BASE_BRANCH
                        The base branch from where create the new branch and where to do the final PR. [default: master]
  --branch BRANCH, -b BRANCH
                        The SDK branch to commit. Default if not Travis: autorest. If Travis is detected, see epilog for details
  --config CONFIG_PATH, -c CONFIG_PATH
                        The JSON configuration format path [default: swagger_to_sdk_config.json]
  --autorest AUTOREST_DIR
                        Force the Autorest to be executed. Must be a directory containing Autorest.exe
  -v, --verbose         Verbosity in INFO mode
  --debug               Verbosity in DEBUG mode

The script activates this additional behaviour if Travis is detected:
 --branch is setted by default to "RestAPI-PR{number}" if triggered by a PR, "RestAPI-{branch}" otherwise
 Only the files inside the PR are considered. If the PR is NOT detected, all files are used.
```

# Configuration file swagger_to_sdk.json, version 0.2.0 (new cli autorest)

This is a configuration which MUST be at the root of the repository you wants to generate.

```json
{
  "meta": {
    "version":"0.2.0",
    "autorest_options": {
      "license-header": "MICROSOFT_MIT_NO_VERSION",
      "payload-flattening-threshold": 2,
      "python": "",
      "azure-arm": true,
      "sdkrel:python-sdks-folder": "."
    },
    "wrapper_filesOrDirs": [],
    "delete_filesOrDirs": [
      "credentials.py",
      "exceptions.py"
    ],
    "generated_relative_base_directory": "*client"
  },
  "projects": {
    "authorization": {
      "autorest_options": {
        "input-file": "arm-authorization/2015-07-01/swagger/authorization.json",
        "namespace": "azure.mgmt.authorization",
        "package-version": "0.30.0"
      },
      "output_dir": "azure-mgmt-authorization/azure/mgmt/authorization",
      "build_dir": "azure-mgmt-authorization"
    },
    "compute.compute.2016-04-30-preview": {
      "composite": "arm-compute/compositeComputeClient_2016_04_30_preview.json",
      "autorest_options": {
        "namespace": "azure.mgmt.compute.compute.v2016_04_30_preview"
      },
      "output_dir": "azure-mgmt-compute/azure/mgmt/compute/compute/v2016_04_30_preview",
      "generated_relative_base_directory": "azure/mgmt/compute/compute/v2016_04_30_preview",
      "build_dir": "azure-mgmt-compute/azure/mgmt/compute/compute/v2016_04_30_preview"
    },
    "recoveryservicesbackup": {
      "markdown": "arm-recoveryservicesbackup/readme.md",
      "generated_relative_base_directory": "Generated/Python/azure/mgmt/recoveryservicesbackup",
      "output_dir":  "azure-mgmt-recoveryservicesbackup/azure/mgmt/recoveryservicesbackup",
      "build_dir": "azure-mgmt-recoveryservicesbackup"
    }    
  }
}
```

## Meta

### version
The version must be 0.2.0.

## autorest_options
An optional dictionary of options you want to pass to Autorest. This will be passed in any call, but can be override by "autorest_options" in each data.
Note that you CAN'T override "--output-folder" which is filled contextually.
All options prefixed by "sdkrel:" can be a relative path that will be solved against SDK folder before being sent to Autorest.

## wrapper_filesOrDirs
An optional list of files/directory to keep when we generate new SDK. This support a Bash-like wildcard syntax (i.e. '*/myfile?.py').
This applies to every Swagger files.

## delete_filesOrDirs
An optional list of files/directory to delete from the generated SDK. This support a Bash-like wildcard syntax (i.e. '*/myfile?.py')
This applies to every Swagger files.

## generated_relative_base_directory
If the data to consider generated by Autorest are not directly in the root folder. For instance, if Autorest generates a networkclient folder 
and you want to consider this folder as the root of data. This parameter is applied before 'delete_filesOrDirs', consider it in your paths.
This applies to every Swagger files.

## Projects

It's a dict where keys are a project id. The project id has no constraint, but it's recommended to use namespace style, like 
"datalake.store.account" to provide the best flexibility for the --project parameter.

Values are:

### markdown
This is an optional parameter which specificy the Autorest MD file path for this project. This is relative to the rest-folder paramter.

### composite
This is an optional parameter which specificy the Composite file path for this project. This is relative to the rest-folder paramter.

### autorest_options
A dictionary of options you want to pass to Autorest. This will override parameter from "autorest_options" in "meta" node.
Note that you CAN'T override "--output-folder" which is filled contextually.

## wrapper_filesOrDirs
An optional list of files/directory to keep when we generate new SDK. This support a Bash-like wildcard syntax (i.e. '*/myfile?.py').
This is added with the list in "meta", this NOT override it.

## delete_filesOrDirs
An optional list of files/directory to delete from the generated SDK. This support a Bash-like wildcard syntax (i.e. '*/myfile?.py')
This is added with the list in "meta", this NOT override it.

## generated_relative_base_directory
If the data to consider generated by Autorest are not directly in the root folder. For instance, if Autorest generates a networkclient folder 
and you want to consider this folder as the root of data.  This parameter is applied before 'delete_filesOrDirs', consider it in your paths.
This replace the same parameter in "meta" if both are provided.

## output_dir
This is the folder in your SDK repository where you want to put the generated files.

## build_dir

This is an optional folder where to put metadata about the generation (Autorest version, date of generation, etc.). This can be used
by our monitoring system to detect package that needs an update. Be sure this folder is unique in the entire file, to avoid
overwritting a file from another project.

# Configuration file swagger_to_sdk.json, version 0.1.0 (legacy autorest)

This is a configuration which MUST be at the root of the repository you wants to generate.

```json
{
  "meta": {
    "version":"0.1.0",
    "language": "Python",
    "autorest": "latest",
    "autorest_options": {
        "ft": 2,
        "AddCredentials": true
    },
    "wrapper_filesOrDirs": [],
    "delete_filesOrDirs": [
      "credentials.py",
      "exceptions.py"
    ],
    "generated_relative_base_directory": "*client"
  },
  "projects": {
    "authorization": {
	  "swagger": "arm-authorization/2015-07-01/swagger/authorization.json",
      "autorest_options": {
        "Namespace" : "azure.mgmt.authorization"
      },
      "output_dir": "azure-mgmt-authorization/azure/mgmt/authorization",
      "wrapper_filesOrDirs": [
        "myfile.py"
      ],
    },
  }
}
```

## Meta

### version
The version must be 0.1.0.

### language
The language parameter configure the language you want Autorest to generate. This could be (case-sensitive):
- Python
- CSharp
- Java
- NodeJS
- Ruby

This will trigger the Azure.<language> autorest code generator. Note that you can override this behaviour by specifying the "CodeGenerator" option in any "autorest_options" field.

### autorest
This the version to use from Autorest. Could be "latest" to download the latest nightly build. Could be a string like  '0.16.0-Nightly20160410' to download a specific version.
If node is not present, consider "latest".

## autorest_options
An optional dictionary of options you want to pass to Autorest. This will be passed in any call, but can be override by "autorest_options" in each data.
You can override the default `Azure.<language>` CodeGenerator parameter here (do NOT use "g" but "CodeGenerator").
Note that you CAN'T override "-i/-Input" and "-o/-Output" which are filled contextually.

## wrapper_filesOrDirs
An optional list of files/directory to keep when we generate new SDK. This support a Bash-like wildcard syntax (i.e. '*/myfile?.py').
This applies to every Swagger files.

## delete_filesOrDirs
An optional list of files/directory to delete from the generated SDK. This support a Bash-like wildcard syntax (i.e. '*/myfile?.py')
This applies to every Swagger files.

## generated_relative_base_directory
If the data to consider generated by Autorest are not directly in the root folder. For instance, if Autorest generates a networkclient folder 
and you want to consider this folder as the root of data. This parameter is applied before 'delete_filesOrDirs', consider it in your paths.
This applies to every Swagger files.

## Projects

It's a dict where keys are a project id. The project id has no constraint, but it's recommended to use namespace style, like 
"datalake.store.account" to provide the best flexibility for the --project parameter.

Values are:

### swagger
This is a mandatory parameter which specificy the Swagger file path for this project. This is relative to the rest-folder paramter.

### autorest_options
A dictionary of options you want to pass to Autorest. This will override parameter from "autorest_options" in "meta" node.
You can override the default `Azure.<language>` CodeGenerator parameter here (do NOT use "g" but "CodeGenerator").
Note that you CAN'T override "-i/-Input" and "-o/-Output" which are filled contextually.

## wrapper_filesOrDirs
An optional list of files/directory to keep when we generate new SDK. This support a Bash-like wildcard syntax (i.e. '*/myfile?.py').
This is added with the list in "meta", this NOT override it.

## delete_filesOrDirs
An optional list of files/directory to delete from the generated SDK. This support a Bash-like wildcard syntax (i.e. '*/myfile?.py')
This is added with the list in "meta", this NOT override it.

## generated_relative_base_directory
If the data to consider generated by Autorest are not directly in the root folder. For instance, if Autorest generates a networkclient folder 
and you want to consider this folder as the root of data.  This parameter is applied before 'delete_filesOrDirs', consider it in your paths.
This replace the same parameter in "meta" if both are provided.

## output_dir
This is the folder in your SDK repository where you want to put the generated files.