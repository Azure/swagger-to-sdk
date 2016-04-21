import unittest
import os
import logging
logging.basicConfig(level=logging.INFO)

# Fake Travis before importing the Script
os.environ['TRAVIS'] = 'true'

from SwaggerToSdk import *

if not 'GH_TOKEN' in os.environ:
    raise Exception('GH_TOKEN must be defined to do the unitesting')
GH_TOKEN = os.environ['GH_TOKEN']

class TestSwaggerToSDK(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        for key in list(os.environ.keys()):
            if key.startswith('TRAVIS'):
                del os.environ[key]

    def test_add_comment_to_pr(self):
        os.environ['TRAVIS_REPO_SLUG'] = 'lmazuel/TestingRepo'

        os.environ['TRAVIS_PULL_REQUEST'] = 'false'
        os.environ['TRAVIS_COMMIT'] = 'dd82f65f1b6314b18609b8572464b6d328ea70d4'
        self.assertTrue(add_comment_to_initial_pr(GH_TOKEN, 'My comment'))
        del os.environ['TRAVIS_COMMIT']

        os.environ['TRAVIS_PULL_REQUEST'] = '1'
        self.assertTrue(add_comment_to_initial_pr(GH_TOKEN, 'My comment'))

    def test_get_pr_from_travis_commit_sha(self):
        os.environ['TRAVIS_REPO_SLUG'] = 'Azure/azure-sdk-for-python'
        os.environ['TRAVIS_COMMIT'] = '497955507bc152c444bd1785f34cafefc7e4e8d9'
        pr_obj = get_pr_from_travis_commit_sha(GH_TOKEN)
        self.assertIsNotNone(pr_obj)
        self.assertEqual(pr_obj.number, 568)

        os.environ['TRAVIS_COMMIT'] = 'c290e668f17b45be6619f9133c0f15af19144280'
        pr_obj = get_pr_from_travis_commit_sha(GH_TOKEN)
        self.assertIsNone(pr_obj)

    def test_download_autorest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exe_path = download_install_autorest(temp_dir)
            self.assertTrue(exe_path.lower().endswith("autorest.exe"))

        with tempfile.TemporaryDirectory() as temp_dir:
            exe_path = download_install_autorest(temp_dir, "0.16.0-Nightly20160410")
            self.assertTrue(exe_path.lower().endswith("autorest.exe"))

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                exe_path = download_install_autorest(temp_dir, "0.16.0-FakePackage")

    def test_build_autorest_options(self):
        line = build_autorest_options("Python", {"A": "value"}, {"B": "value"})
        self.assertEqual(line, "-A value -B value -CodeGenerator Azure.Python")

        line = build_autorest_options("Python", {"A": "value"}, {"A": "newvalue"})
        self.assertEqual(line, "-A newvalue -CodeGenerator Azure.Python")

        line = build_autorest_options("Python", {"CodeGenerator": "NodeJS"}, {})
        self.assertEqual(line, "-CodeGenerator NodeJS")

        line = build_autorest_options("Python", {"CodeGenerator": "NodeJS"}, {"CodeGenerator": "CSharp"})
        self.assertEqual(line, "-CodeGenerator CSharp")

        line = build_autorest_options("Python", {}, {})
        self.assertEqual(line, "-CodeGenerator Azure.Python")

        line = build_autorest_options("Python", {"A": 12, "B": True})
        self.assertEqual(line, "-A 12 -B True -CodeGenerator Azure.Python")


if __name__ == '__main__':
    unittest.main()