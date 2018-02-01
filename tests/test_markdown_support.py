from pathlib import Path

from swaggertosdk.markdown_support import extract_yaml


def test_extract_md():
    md_text = '# Scenario: Validate a OpenAPI definition file according to the ARM guidelines \r\n\r\n> see https://aka.ms/autorest\r\n\r\n## Inputs\r\n\r\n``` yaml \r\ninput-file:\r\n  - https://github.com/Azure/azure-rest-api-specs/blob/master/arm-storage/2015-06-15/swagger/storage.json\r\n```\r\n\r\n## Validation\r\n\r\nThis time, we not only want to generate code, we also want to validate.\r\n\r\n``` yaml\r\nazure-arm: true # enables validation messages\r\n```\r\n\r\n## Generation\r\n\r\nAlso generate for some languages.\r\n\r\n``` yaml \r\ncsharp:\r\n  output-folder: CSharp\r\njava:\r\n  output-folder: Java\r\nnodejs:\r\n  output-folder: NodeJS\r\npython:\r\n  output-folder: Python\r\nruby:\r\n  output-folder: Ruby\r\n```'
    yaml_content = extract_yaml(md_text)
    assert 'https://github.com/Azure/azure-rest-api-specs/blob/master/arm-storage/2015-06-15/swagger/storage.json' == yaml_content[0]

def test_extract_md_with_no_input():
    md_text = '# Empty md'
    yaml_content = extract_yaml(md_text)
    assert [] == yaml_content
