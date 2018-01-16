import unittest.mock
import os.path
import logging
import tempfile
from pathlib import Path
logging.basicConfig(level=logging.INFO)

# Fake Travis before importing the Script
os.environ['TRAVIS'] = 'true'

from swaggertosdk.SwaggerToSdkCore import *
from swaggertosdk.markdown_support import *
import swaggertosdk.SwaggerToSdkNewCLI as SwaggerToSdkNewCLI

if not 'GH_TOKEN' in os.environ:
    raise Exception('GH_TOKEN must be defined to do the unitesting')
GH_TOKEN = os.environ['GH_TOKEN']

CWD = os.path.dirname(os.path.realpath(__file__))

def get_pr(repo_id, pr_number):
    github_client = Github(GH_TOKEN)
    repo = github_client.get_repo(repo_id)
    return repo.get_pull(int(pr_number))

def get_commit(repo_id, sha):
    github_client = Github(GH_TOKEN)
    repo = github_client.get_repo(repo_id)
    return repo.get_commit(sha)

class TestMarkDownSupport(unittest.TestCase):

    def test_extract_md(self):
        md_text = '# Scenario: Validate a OpenAPI definition file according to the ARM guidelines \r\n\r\n> see https://aka.ms/autorest\r\n\r\n## Inputs\r\n\r\n``` yaml \r\ninput-file:\r\n  - https://github.com/Azure/azure-rest-api-specs/blob/master/arm-storage/2015-06-15/swagger/storage.json\r\n```\r\n\r\n## Validation\r\n\r\nThis time, we not only want to generate code, we also want to validate.\r\n\r\n``` yaml\r\nazure-arm: true # enables validation messages\r\n```\r\n\r\n## Generation\r\n\r\nAlso generate for some languages.\r\n\r\n``` yaml \r\ncsharp:\r\n  output-folder: CSharp\r\njava:\r\n  output-folder: Java\r\nnodejs:\r\n  output-folder: NodeJS\r\npython:\r\n  output-folder: Python\r\nruby:\r\n  output-folder: Ruby\r\n```'
        yaml_content = extract_yaml(md_text)
        self.assertEquals(
            'https://github.com/Azure/azure-rest-api-specs/blob/master/arm-storage/2015-06-15/swagger/storage.json',
            yaml_content[0]
        )

    def test_extract_md_with_no_input(self):
        md_text = '# Empty md'
        yaml_content = extract_yaml(md_text)
        self.assertListEqual([], yaml_content)

    def test_extract_md_with_tag(self):
        docs = get_documents_in_markdown_file(Path('files/readme_tag.md_test'), base_dir=Path(CWD))
        self.assertEqual(len(docs), 29, "Not enough document")

class TestSwaggerToSDK(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        for key in list(os.environ.keys()):
            if key.startswith('TRAVIS'):
                del os.environ[key]

    def test_solve_relative_path(self):
        conf = {
            "test": "basicvalue",
            "sdkrel:retest": "."
        }
        
        solved_conf = SwaggerToSdkNewCLI.solve_relative_path(conf, "/tmp")
        print(solved_conf)
        self.assertEquals(len(solved_conf), 2)
        self.assertEquals(solved_conf["test"], "basicvalue")
        self.assertIn(solved_conf["retest"], ["/tmp", "C:\\tmp", "D:\\tmp"]) # Cross platform tests

    def test_get_swagger_project_files_in_pr(self):
        swaggers = get_swagger_project_files_in_pr(get_pr('Azure/azure-rest-api-specs', 1422), base_dir=Path(CWD))
        for s in swaggers:
            self.assertIsInstance(s, Path)
            self.assertIn(s, [
                Path('specification/compute/resource-manager/Microsoft.Compute/2017-03-30/compute.json'),
                Path('files/readme.md')
            ])
        self.assertEqual(len(swaggers), 2)


    def test_swagger_index_from_markdown(self):
        self.assertDictEqual(
            {
                Path('specification/compute/resource-manager/Microsoft.Compute/2017-03-30/compute.json'):
                    Path('files/readme.md'),
            },
            swagger_index_from_markdown(Path(CWD))
        )


    def test_get_git_files(self):
        # Basic test, one Swagger file only (PR)
        self.assertSetEqual(
            get_swagger_files_in_git_object(get_pr('Azure/azure-rest-api-specs', 1422)),
            {Path('specification/compute/resource-manager/Microsoft.Compute/2017-03-30/compute.json')}
        )
        # Basic test, one Readme file only (PR)
        self.assertSetEqual(
            get_swagger_files_in_git_object(get_pr('lmazuel/azure-rest-api-specs', 12)),
            {Path('specification/cdn/resource-manager/readme.md')}
        )
        # Basic test, one Swagger file only (commit)
        self.assertSetEqual(
            get_swagger_files_in_git_object(get_commit('Azure/azure-rest-api-specs', 'ae25a0505f86349bbe92251dde34d70bfb6be78a')),
            {Path('specification/cognitiveservices/data-plane/EntitySearch/v1.0/EntitySearch.json')}
        )
        # Should not find Swagger and not fails
        self.assertSetEqual(
            get_swagger_files_in_git_object(get_pr('Azure/azure-sdk-for-python', 627)),
            set()
        )


    def test_do_commit(self):
        finished = False # Authorize PermissionError on cleanup
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                Repo.clone_from('https://github.com/lmazuel/TestingRepo.git', temp_dir)
                repo = Repo(temp_dir)

                result = do_commit(repo, 'Test {hexsha}', 'testing', 'fakehexsha')
                self.assertFalse(result)
                self.assertNotIn('fakehexsha', repo.head.commit.message)
                self.assertEqual(repo.active_branch.name, 'master')

                file_path = Path(temp_dir, 'file.txt')
                file_path.write_text('Something')

                result = do_commit(repo, 'Test {hexsha}', 'testing', 'fakehexsha')
                self.assertTrue(result)
                self.assertEqual(repo.head.commit.message, 'Test fakehexsha')
                self.assertEqual(repo.active_branch.name, 'testing')
                self.assertIn('file.txt', repo.head.commit.stats.files)

                file_path.write_text('New content')

                result = do_commit(repo, 'Now it is {hexsha}', 'newbranch', 'new-fakehexsha')
                self.assertTrue(result)
                self.assertEqual(repo.head.commit.message, 'Now it is new-fakehexsha')
                self.assertEqual(repo.active_branch.name, 'newbranch')
                self.assertIn('file.txt', repo.head.commit.stats.files)

                file_path.unlink()
                file_path.write_text('New content')

                result = do_commit(repo, 'Now it is {hexsha}', 'fakebranch', 'hexsha_not_used')
                self.assertFalse(result)
                self.assertEqual(repo.head.commit.message, 'Now it is new-fakehexsha')
                self.assertEqual(repo.active_branch.name, 'newbranch')

                finished = True
        except PermissionError:
            if finished:
                return
            raise


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


    def test_get_input_path(self):
        main, opt = SwaggerToSdkNewCLI.get_input_paths(
            {},
            {"autorest_options": {
                "input-file": ['a', 'b']
            }}
        )
        self.assertEqual(None, main)
        self.assertEqual([Path('a'), Path('b')], opt)

        main, opt = SwaggerToSdkNewCLI.get_input_paths(
            {},
            {"autorest_options": {
                "input-file": ['a', 'b']
            }, "markdown":"c"}
        )
        self.assertEqual(Path('c'), main)
        self.assertEqual([Path('a'), Path('b')], opt)

    def test_get_user(self):
        user = user_from_token(GH_TOKEN)
        self.assertEqual(user.login, 'lmazuel')

    def test_configure(self):
        finished = False
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                try:
                    Repo.clone_from('https://github.com/lmazuel/TestingRepo.git', temp_dir)
                    repo = Repo(temp_dir)

                    # If it's not throwing, I'm happy enough
                    configure_user(GH_TOKEN, repo)

                    self.assertEqual(repo.git.config('--get', 'user.name'), 'Laurent Mazuel')
                except Exception as err:
                    print(err)
                    self.fail(err)
                else:
                    finished = True
        except PermissionError:
            if finished:
                return
            raise

    def test_do_pr(self):
        # Should do nothing
        do_pr(None, 'bad', 'bad', 'bad', 'bad')

        # Should do nothing
        do_pr(GH_TOKEN, 'bad', None, 'bad', 'bad')

        # FIXME - more tests

    @unittest.mock.patch('swaggertosdk.SwaggerToSdkCore.autorest_latest_version_finder')
    def test_build(self, mocked_autorest_latest_version_finder):
        build = build_file_content()
        self.assertIn('autorest', build)

    def test_move_wrapper_files_or_dirs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir, 'output')
            output.mkdir()

            save_dest = Path(temp_dir, 'save')
            save_dest.mkdir()

            Path(output, 'folder').mkdir()
            Path(output, 'to_keep.txt').write_bytes(b'My content')
            Path(output, 'to_keep_pattern.txt').write_bytes(b'My content')

            SwaggerToSdkNewCLI.move_wrapper_files_or_dirs(
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

            self.assertTrue(Path(save_dest, 'to_keep.txt').exists())
            self.assertTrue(Path(save_dest, 'to_keep_pattern.txt').exists())
            self.assertTrue(Path(save_dest, 'folder').exists())

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

            SwaggerToSdkNewCLI.move_wrapper_files_or_dirs(
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
            self.assertTrue(Path(save_sub, 'to_keep.txt').exists())
            self.assertTrue(Path(save_sub, 'to_keep_pattern.txt').exists())
            self.assertTrue(Path(save_sub, 'folder').exists())

    def test_delete_extra_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir, 'output')
            output.mkdir()

            Path(output, 'generated.txt').write_bytes(b'My content')
            Path(output, 'dont_need_this.txt').write_bytes(b'My content')
            Path(output, 'del_folder').mkdir()

            SwaggerToSdkNewCLI.delete_extra_files(
                output,
                {'delete_filesOrDirs': [
                    'dont_need_this.txt',
                    'dont_exist_no_big_deal_2.txt',
                    'del_folder'
                ]},
                {}
            )

            self.assertFalse(Path(output, 'erase.txt').exists())
            self.assertFalse(Path(output, 'dont_need_this.txt').exists())
            self.assertFalse(Path(output, 'del_folder').exists())

    @unittest.mock.patch('swaggertosdk.SwaggerToSdkCore.autorest_latest_version_finder')
    def test_write_build_file(self, mocked_autorest_latest_version_finder):
        mocked_autorest_latest_version_finder.return_value = '123'
        with tempfile.TemporaryDirectory() as temp_dir:
            SwaggerToSdkNewCLI.write_build_file(
                temp_dir,
                {
                    'build_dir': '.'
                }
            )
            with open(Path(temp_dir, 'build.json'), 'r') as build_fd:
                data = json.load(build_fd)
                self.assertEqual('123', data['autorest'])

            output = Path(temp_dir, 'output')
            output.mkdir()
            SwaggerToSdkNewCLI.write_build_file(
                temp_dir,
                {
                    'build_dir': 'output'
                }
            )
            with open(Path(output, 'build.json'), 'r') as build_fd:
                data = json.load(build_fd)
                self.assertEqual('123', data['autorest'])

    def test_move_autorest_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            generated = Path(temp_dir, 'generated')
            generated.mkdir()
            generated_subfolder = generated.joinpath('inside')
            generated_subfolder.mkdir()

            output = Path(temp_dir, 'output')
            output.mkdir()

            Path(generated_subfolder, 'generated.txt').write_bytes(b'My content')
            Path(output, 'erase.txt').write_bytes(b'My content')

            SwaggerToSdkNewCLI.move_autorest_files(
                generated,
                output,
                {'generated_relative_base_directory': '*side'}, 
                {
                    'output_dir': '.'
                }
            )

            self.assertTrue(Path(output, 'generated.txt').exists())
            self.assertFalse(Path(output, 'erase.txt').exists())

    @unittest.mock.patch('swaggertosdk.autorest_tools.execute_simple_command')
    def test_extract_conf_from_readmes(self, mocked_execute_simple_command):
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
        sdk_git_id = get_full_sdk_id(GH_TOKEN, "azure-sdk-for-python")
        config = {}
        extract_conf_from_readmes(GH_TOKEN, swagger_files_in_pr, Path(CWD, "files"), sdk_git_id, config)

        assert "projects" in config
        assert "readme.md" in config["projects"]
        assert config["projects"]["readme.md"]["markdown"] == "readme.md"
        print(config)

        config = {
            "projects": {
                "dns": {
                    "markdown": "myreadmd.md"
                }
            }
        }
        extract_conf_from_readmes(GH_TOKEN, swagger_files_in_pr, Path(CWD, "files"), sdk_git_id, config)

        assert len(config["projects"]) == 2

if __name__ == '__main__':
    unittest.main()
