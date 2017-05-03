from mistune import Renderer, Markdown
import yaml
from io import StringIO

class YamlExtractor(Renderer):
    def __init__(self, *args, **kwargs):
        self.yaml_content = StringIO()
        Renderer.__init__(self, *args, **kwargs)

    def block_code(self, code, lang=None):
        if lang == "yaml":
            self.yaml_content.write(code+"\n")
        return Renderer.block_code(self, code, lang)

def extract_yaml(markdown_content):
    # Get the YAML code inside the Markdown
    try:
        extractor = YamlExtractor()
        markdown_processor = Markdown(extractor)
        markdown_processor(markdown_content)
        raw_yaml = extractor.yaml_content.getvalue()
    except Exception:
        raise ValueError("The Markdown content is not valid")

    # Get the yaml as a dict
    try:
        return yaml.load(raw_yaml)
    except Exception:
        raise ValueError("Unable to build a valid YAML from this Markdown")
