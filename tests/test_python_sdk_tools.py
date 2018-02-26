from pathlib import Path
from subprocess import CalledProcessError
import tempfile

import pytest

from swaggertosdk.python_sdk_tools import build_package_from_pr_number


def test_build_package_from_pr_number(github_token):

    # Should build package azure-mgmt-advisor 1.0.1
    with tempfile.TemporaryDirectory() as temp_dir:
        build_package_from_pr_number(github_token, "Azure/azure-sdk-for-python", 1974, temp_dir)
        temp_dir_path = Path(temp_dir)
        files = set(file.relative_to(temp_dir) for file in temp_dir_path.iterdir())
        assert files == {
            Path("azure_mgmt_advisor-1.0.1-py2.py3-none-any.whl"),
            Path("azure-mgmt-advisor-1.0.1.zip")
        }

    # This PR is broken and can't be built: 2040
    with tempfile.TemporaryDirectory() as temp_dir, pytest.raises(CalledProcessError):
        build_package_from_pr_number(github_token, "Azure/azure-sdk-for-python", 2040, temp_dir)
    