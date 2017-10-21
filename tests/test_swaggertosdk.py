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
import swaggertosdk.SwaggerToSdkLegacy as SwaggerToSdkLegacy
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

    def test_get_swagger_project_files_in_pr(self):
        swaggers = get_swagger_project_files_in_pr(get_pr('Azure/azure-rest-api-specs', 1422), base_dir=Path(CWD))
        for s in swaggers:
            self.assertIsInstance(s, Path)
            self.assertIn(s, [
                Path('specification/compute/resource-manager/Microsoft.Compute/2017-03-30/compute.json'),
                Path('files/readme.md')
            ])
        self.assertEqual(len(swaggers), 2)

    def test_swagger_index_from_composite(self):
        self.assertDictEqual(
            {
                Path('arm-graphrbac/1.6/swagger/graphrbac.json'):
                    Path('files/compositeGraphRbacManagementClient.json'),
                Path('files/arm-graphrbac/1.6-internal/swagger/graphrbac.json'):
                    Path('files/compositeGraphRbacManagementClient.json')
            },
            swagger_index_from_composite(Path(CWD))
        )

    def test_swagger_index_from_markdown(self):
        self.assertDictEqual(
            {
                Path('specification/compute/resource-manager/Microsoft.Compute/2017-03-30/compute.json'):
                    Path('files/readme.md'),
            },
            swagger_index_from_markdown(Path(CWD))
        )

    def test_get_doc_composite(self):
        composite_path = Path('files/compositeGraphRbacManagementClient.json')
        documents = get_documents_in_composite_file(composite_path, base_dir=Path(CWD))
        self.assertEqual(len(documents), 2)
        self.assertEqual(documents[0], Path('arm-graphrbac/1.6/swagger/graphrbac.json'))
        self.assertEqual(documents[1], Path('files/arm-graphrbac/1.6-internal/swagger/graphrbac.json'))

    def test_find_composite_files(self):
        files = find_composite_files(Path(CWD))
        self.assertEqual(files[0], Path('files/compositeGraphRbacManagementClient.json'))

    def test_get_git_files(self):
        # Basic test, one Swagger file only (PR)
        self.assertSetEqual(
            get_swagger_files_in_git_object(get_pr('Azure/azure-rest-api-specs', 1422)),
            {Path('specification/compute/resource-manager/Microsoft.Compute/2017-03-30/compute.json')}
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

    @unittest.mock.patch('subprocess.check_output')
    def test_generate_code(self, mocked_check_output):
        SwaggerToSdkLegacy.generate_code(
            'Java',
            Path('/a/b/c/swagger.json'),
            Path('/'),
            {},
            {},
            "node myautorest"
        )
        call_args = mocked_check_output.call_args
        expected = [
            'node',
            'myautorest',
            '--version=latest',
            '-i',
            str(Path('/a/b/c/swagger.json')),
            '-o',
            str(Path('/')),
            '-CodeGenerator',
            'Azure.Java'
        ]
        self.assertListEqual(call_args[0][0], expected)
        self.assertEqual(call_args[1]['cwd'], str(Path('/a/b/c/')))

        SwaggerToSdkNewCLI.generate_code(
            Path('/a/b/c/swagger.md'),
            Path('/'),
            {"autorest_markdown_cli": True},
            {"autorest_options":{
                "java": '',
                'azure-arm': True,
                "description": "I am a spaced description",
                'input-file': [Path('/a/b/c/swagger.json')]}
            },
            "node myautorest"
        )
        call_args = mocked_check_output.call_args
        expected = [
            'node',
            'myautorest',
            '--version=latest',
            str(Path('/a/b/c/swagger.md')),
            '--output-folder={}{}'.format(str(Path('/')),str(Path('/'))),
            '--azure-arm=True',
            "--description='I am a spaced description'",
            '--input-file={}'.format(str(Path('/a/b/c/swagger.json'))),
            '--java',
        ]
        self.assertListEqual(call_args[0][0], expected)
        self.assertEqual(call_args[1]['cwd'], str(Path('/a/b/c/')))


    @unittest.mock.patch('subprocess.check_output')
    def test_generate_code_no_autorest_in_path(self, mocked_check_output):
        with tempfile.TemporaryDirectory() as temp_dir, self.assertRaises(ValueError) as cm, unittest.mock.patch('shutil.which') as which:
            which.return_value = None
            SwaggerToSdkNewCLI.generate_code(
                Path('/a/b/c/swagger.json'),
                Path(temp_dir),
                {},
                {}
            )
        the_exception = cm.exception
        print(str(the_exception))
        print(str(shutil.which("autorest")))
        self.assertTrue("No autorest found in PATH and no autorest path option used" in str(the_exception))

    @unittest.mock.patch('subprocess.check_output')
    def test_generate_code_fail(self, mocked_check_output):
        with tempfile.TemporaryDirectory() as temp_dir, self.assertRaises(ValueError) as cm:
            SwaggerToSdkNewCLI.generate_code(
                Path('/a/b/c/swagger.json'),
                Path(temp_dir),
                {},
                {},
                "node autorest"
            )
        the_exception = cm.exception
        self.assertTrue("no files were generated" in str(the_exception))

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

    def test_legacy_build_autorest_options(self):
        line = SwaggerToSdkLegacy.build_autorest_options("Python", {"autorest_options": {"A": "value"}}, {"autorest_options": {"B": "value"}})
        self.assertEqual(line, "-A value -B value -CodeGenerator Azure.Python")

        line = SwaggerToSdkLegacy.build_autorest_options("Python", {"autorest_options": {"A": "value"}}, {"autorest_options": {"A": "newvalue"}})
        self.assertEqual(line, "-A newvalue -CodeGenerator Azure.Python")

        line = SwaggerToSdkLegacy.build_autorest_options("Python", {"autorest_options": {"CodeGenerator": "NodeJS"}}, {})
        self.assertEqual(line, "-CodeGenerator NodeJS")

        line = SwaggerToSdkLegacy.build_autorest_options("Python", {"autorest_options": {"CodeGenerator": "NodeJS"}}, {"autorest_options": {"CodeGenerator": "CSharp"}})
        self.assertEqual(line, "-CodeGenerator CSharp")

        line = SwaggerToSdkLegacy.build_autorest_options("Python", {}, {})
        self.assertEqual(line, "-CodeGenerator Azure.Python")

        line = SwaggerToSdkLegacy.build_autorest_options("Python", {"autorest_options": {"A": 12, "B": True}}, {})
        self.assertEqual(line, "-A 12 -B True -CodeGenerator Azure.Python")

    def test_build_autorest_options(self):
        line = SwaggerToSdkNewCLI.build_autorest_options({"autorest_options": {"A": "value"}}, {"autorest_options": {"B": "value value"}})
        self.assertListEqual(line, ["--a=value", "--b='value value'"])

        line = SwaggerToSdkNewCLI.build_autorest_options({"autorest_options": {"A": "value"}}, {"autorest_options": {"B": ["value1", "value2"]}})
        self.assertListEqual(line, ["--a=value", "--b=value1", "--b=value2"])

        line = SwaggerToSdkNewCLI.build_autorest_options({"autorest_options": {"A": "value"}}, {"autorest_options": {"A": "newvalue"}})
        self.assertListEqual(line, ["--a=newvalue"])

        line = SwaggerToSdkNewCLI.build_autorest_options({}, {})
        self.assertListEqual(line, [])

        line = SwaggerToSdkNewCLI.build_autorest_options({"autorest_options": {"A": 12, "B": True, "C": ''}}, {})
        self.assertListEqual(line, ["--a=12", "--b=True", "--c"])

    def test_merge_options(self):
        result = merge_options({}, {}, 'key')
        self.assertFalse(result)

        result = merge_options({'a': [1, 2, 3]}, {'a': [3, 4, 5]}, 'a')
        self.assertSetEqual(set(result), {1, 2, 3, 4, 5})

        result = merge_options({'a': [1, 2, 3]}, {}, 'a')
        self.assertSetEqual(set(result), {1, 2, 3})

        result = merge_options({}, {'a': [3, 4, 5]}, 'a')
        self.assertSetEqual(set(result), {3, 4, 5})

        result = merge_options({'a': {1: 2, 2: 3}}, {'a': {3: 4, 2: 3}}, 'a')
        self.assertDictEqual(result, {1: 2, 2: 3, 3: 4})

    def test_get_input_path(self):
        main, opt, comp = SwaggerToSdkNewCLI.get_input_paths(
            {},
            {"autorest_options": {
                "input-file": ['a', 'b']
            }}
        )
        self.assertEqual(None, main)
        self.assertEqual([Path('a'), Path('b')], opt)

        main, opt, comp = SwaggerToSdkNewCLI.get_input_paths(
            {},
            {"autorest_options": {
                "input-file": ['a', 'b']
            },"markdown":"c"}
        )
        self.assertEqual(Path('c'), main)
        self.assertEqual([Path('a'), Path('b')], opt)

        main, opt, comp = SwaggerToSdkNewCLI.get_input_paths(
            {},
            {"composite": "d"}
        )
        self.assertEqual(None, main)
        self.assertEqual(Path('d'), comp)
        self.assertEqual([], opt)

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

    def test_build(self):
        build = build_file_content('123')
        self.assertEqual('123', build['autorest'])
        self.assertTrue(build['date'].startswith("20"))

    def test_update(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            generated = Path(temp_dir, 'generated')
            generated.mkdir()
            generated_subfolder = generated.joinpath('inside')
            generated_subfolder.mkdir()

            output = Path(temp_dir, 'output')
            output.mkdir()

            Path(generated_subfolder, 'generated.txt').write_bytes(b'My content')
            Path(generated_subfolder, 'dont_need_this.txt').write_bytes(b'My content')
            Path(generated_subfolder, 'del_folder').mkdir()
            Path(output, 'folder').mkdir()
            Path(output, 'to_keep.txt').write_bytes(b'My content')
            Path(output, 'to_keep_pattern.txt').write_bytes(b'My content')
            Path(output, 'erase.txt').write_bytes(b'My content')

            SwaggerToSdkNewCLI.update(generated,
                   output,
                   {'wrapper_filesOrDirs': [
                       'to_keep.txt',
                       'to_*_pattern.txt',
                       'dont_exist_no_big_deal.txt',
                       'folder'
                   ],
                    'delete_filesOrDirs': [
                        'dont_need_this.txt',
                        'dont_exist_no_big_deal_2.txt',
                        'del_folder'
                    ],
                    'generated_relative_base_directory': '*side',
                    'autorest': '123'}, 
                    {
                        'output_dir': '.',
                        'build_dir': '.'
                    }
                  )

            self.assertTrue(Path(output, 'generated.txt').exists())
            self.assertTrue(Path(output, 'to_keep.txt').exists())
            self.assertTrue(Path(output, 'to_keep_pattern.txt').exists())
            self.assertTrue(Path(output, 'folder').exists())
            self.assertTrue(Path(output, 'build.json').exists())
            self.assertFalse(Path(output, 'erase.txt').exists())
            self.assertFalse(Path(output, 'dont_need_this.txt').exists())
            self.assertFalse(Path(output, 'del_folder').exists())
            with open(Path(output, 'build.json'), 'r') as build_fd:
                data = json.load(build_fd)
                self.assertEqual('123', data['autorest'])


if __name__ == '__main__':
    unittest.main()
