import re

from mistune import Renderer, Markdown, BlockLexer
import yaml
from io import StringIO

class YamlBlockLexer(BlockLexer):
    def enable_autorest_yaml(self):
        self.rules.autorest_yaml = re.compile(
            r'^ *(`{3,}|~{3,}) *(\S+)? *([^\n]+)? *\n'  # ```lang tag
            r'([\s\S]+?)\s*'
            r'\1 *(?:\n+|$)'  # ```
        )
        self.default_rules.insert(3, 'autorest_yaml')

    def parse_autorest_yaml(self, m):
        self.tokens.append({
            'type': 'code',
            'lang': m.group(2),
            'tag': m.group(3),
            'text': m.group(4),
        })        

class YamlExtractor(Renderer):
    def __init__(self, *args, **kwargs):
        self.yaml_content = []
        Renderer.__init__(self, *args, **kwargs)

    def block_code(self, code, lang=None, tag=None):
        if lang == "yaml":
            yaml_code = yaml.load(code)
            self.yaml_content.append(yaml_code)
        return Renderer.block_code(self, code, lang)

def extract_yaml(markdown_content):
    # Get the YAML code inside the Markdown
    try:
        block = YamlBlockLexer()
        block.enable_autorest_yaml()

        extractor = YamlExtractor()
        markdown_processor = Markdown(extractor, block=block)
        markdown_processor(markdown_content)
        return extract_input_file(extractor.yaml_content)
    except Exception as err:
        raise ValueError("The Markdown/YAML content is not valid: %s", str(err))

def extract_input_file(yaml_dict):
    if isinstance(yaml_dict, list):
        return [o for v in yaml_dict for o in extract_input_file(v)]
    # Not a list
    try:
        inputs = yaml_dict.get("input-file")
        if inputs is not None:
            return inputs
        return [o for v in yaml_dict.values() for o in extract_input_file(v)]
    except AttributeError:
        # Not a dict, not a list => anything else terminal
        return []

