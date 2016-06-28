import unittest
import os
import logging
import tempfile
from pathlib import Path
logging.basicConfig(level=logging.INFO)

# Fake Travis before importing the Script
os.environ['TRAVIS'] = 'true'

from SwaggerToSdk import *

if not 'GH_TOKEN' in os.environ:
    raise Exception('GH_TOKEN must be defined to do the unitesting')
GH_TOKEN = os.environ['GH_TOKEN']

def get_pr(repo_id, pr_number):
    github_client = Github(GH_TOKEN)
    repo = github_client.get_repo(repo_id)
    return repo.get_pull(int(pr_number))

class TestSwaggerToSDK(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        for key in list(os.environ.keys()):
            if key.startswith('TRAVIS'):
                del os.environ[key]

    def test_get_swagger_project_files_in_pr(self):
        swaggers = get_swagger_project_files_in_pr(get_pr('Azure/azure-rest-api-specs', 361))
        for s in swaggers:
            self.assertIsInstance(s, Path)
            self.assertIn(s, [
                Path('arm-graphrbac/1.6/swagger/graphrbac.json'),
                Path('test/compositeGraphRbacManagementClient.json')
            ])
        self.assertEqual(len(swaggers), 2)

    def test_swagger_index_from_composite(self):
        self.assertDictEqual(
            {
                Path('arm-graphrbac/1.6/swagger/graphrbac.json'):
                    Path('test/compositeGraphRbacManagementClient.json'),
                Path('arm-graphrbac/1.6-internal/swagger/graphrbac.json'):
                    Path('test/compositeGraphRbacManagementClient.json')
            },
            swagger_index_from_composite()
        )

    def test_get_doc_composite(self):
        composite_path = Path('test/compositeGraphRbacManagementClient.json')
        documents = get_documents_in_composite_file(composite_path)
        self.assertEqual(len(documents), 2)
        self.assertEqual(documents[0], Path('arm-graphrbac/1.6/swagger/graphrbac.json'))
        self.assertEqual(documents[1], Path('arm-graphrbac/1.6-internal/swagger/graphrbac.json'))

    def test_find_composite_files(self):
        files = find_composite_files()
        self.assertEqual(files[0], Path('test/compositeGraphRbacManagementClient.json'))

    def test_get_pr_files(self):
        # Basic test, one Swagger file only
        self.assertSetEqual(
            get_swagger_files_in_pr(get_pr('Azure/azure-rest-api-specs', 342)),
            {Path('search/2015-02-28-Preview/swagger/searchservice.json')}
        )
        # This PR contains a schema and a Swagger, I just want the swagger
        self.assertSetEqual(
            get_swagger_files_in_pr(get_pr('Azure/azure-rest-api-specs', 341)),
            {Path('arm-mobileengagement/2014-12-01/swagger/mobile-engagement.json')}
        )
        # Should not find Swagger and not fails
        self.assertSetEqual(
            get_swagger_files_in_pr(get_pr('Azure/azure-sdk-for-python', 627)),
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

    def test_install_autorest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exe_path = install_autorest(temp_dir)
            self.assertTrue(exe_path.lower().endswith("autorest.exe"))

        with tempfile.TemporaryDirectory() as temp_dir:
            exe_path = install_autorest(temp_dir, {'autorest': "0.16.0-Nightly20160410"})
            self.assertTrue(exe_path.lower().endswith("autorest.exe"))

        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, 'AutoRest.exe').write_text("I'm not a virus")
            exe_path = install_autorest(temp_dir, autorest_dir=temp_dir)
            self.assertTrue(exe_path.lower().endswith("autorest.exe"))

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                install_autorest(temp_dir, {'autorest': "0.16.0-FakePackage"})

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ValueError):
                install_autorest(temp_dir, autorest_dir=temp_dir)

    def test_build_autorest_options(self):
        line = build_autorest_options("Python", {"autorest_options": {"A": "value"}}, {"autorest_options": {"B": "value"}})
        self.assertEqual(line, "-A value -B value -CodeGenerator Azure.Python")

        line = build_autorest_options("Python", {"autorest_options": {"A": "value"}}, {"autorest_options": {"A": "newvalue"}})
        self.assertEqual(line, "-A newvalue -CodeGenerator Azure.Python")

        line = build_autorest_options("Python", {"autorest_options": {"CodeGenerator": "NodeJS"}}, {})
        self.assertEqual(line, "-CodeGenerator NodeJS")

        line = build_autorest_options("Python", {"autorest_options": {"CodeGenerator": "NodeJS"}}, {"autorest_options": {"CodeGenerator": "CSharp"}})
        self.assertEqual(line, "-CodeGenerator CSharp")

        line = build_autorest_options("Python", {}, {})
        self.assertEqual(line, "-CodeGenerator Azure.Python")

        line = build_autorest_options("Python", {"autorest_options": {"A": 12, "B": True}}, {})
        self.assertEqual(line, "-A 12 -B True -CodeGenerator Azure.Python")

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

            update(str(generated), str(output),
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
                    'generated_relative_base_directory': '*side'}, {}
                  )

            self.assertTrue(Path(output, 'generated.txt').exists())
            self.assertTrue(Path(output, 'to_keep.txt').exists())
            self.assertTrue(Path(output, 'to_keep_pattern.txt').exists())
            self.assertTrue(Path(output, 'folder').exists())
            self.assertFalse(Path(output, 'erase.txt').exists())
            self.assertFalse(Path(output, 'dont_need_this.txt').exists())
            self.assertFalse(Path(output, 'del_folder').exists())


if __name__ == '__main__':
    unittest.main()