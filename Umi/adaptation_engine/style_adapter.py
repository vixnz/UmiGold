import ast
import json
from telemetry_db import TelemetryDB
from collections import defaultdict
import logging
import re

logging.basicConfig(filename='style_adapter.log', level=logging.INFO)

class StyleAdapter:
    def __init__(self, telemetry_db: TelemetryDB):
        self.db = telemetry_db
        self.style_rules = self._load_base_rules()
        self.user_profile = self._build_initial_profile()

    def _load_base_rules(self) -> dict:
        """Load language-agnostic formatting conventions"""
        return {
            "brace_style": {"options": ["same-line", "next-line"], "default": "same-line"},
            "indentation": {"options": [2, 4, 8], "default": 4},
            "naming_convention": {"options": ["snake_case", "camelCase", "PascalCase"], "default": "snake_case"}
        }

    def _build_initial_profile(self) -> dict:
        """Create style profile from telemetry acceptance patterns"""
        adaptation_data = self.db.get_adaptation_data()
        profile = {}
        for rule_name, rule_info in self.style_rules.items():
            pref_scores = defaultdict(float)
            for suggestion_id, accept_ratio in adaptation_data.items():
                # Expect suggestion_id format: "rule=brace_style:choice=next-line"
                if f"rule={rule_name}" in suggestion_id:
                    match = re.search(r"choice=([A-Za-z0-9_-]+)", suggestion_id)
                    if match:
                        choice = match.group(1)
                        pref_scores[choice] = accept_ratio
            profile[rule_name] = (
                max(pref_scores, key=pref_scores.get) if pref_scores else rule_info["default"]
            )
        return profile

    def generate_editorconfig(self) -> str:
        """Output .editorconfig snippet reflecting user profile (with custom fields)"""
        return f"""
[*.py]
indent_size = {self.user_profile['indentation']}
indent_style = space
# Custom fields for personalization (non-standard)
brace_style = {self.user_profile['brace_style']}
identifier_case = {self.user_profile['naming_convention']}
"""

    def adapt_ast(self, tree: ast.Module) -> ast.Module:
        """Modify AST nodes to match user's style profile"""

        def to_camel_case(name: str) -> str:
            parts = name.split('_')
            return parts[0].lower() + ''.join(x.title() for x in parts[1:])

        def to_snake_case(name: str) -> str:
            return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()

        def to_pascal_case(name: str) -> str:
            return ''.join(x.title() for x in name.split('_'))

        class StyleTransformer(ast.NodeTransformer):
            def __init__(self, profile):
                self.profile = profile
                super().__init__()

            def visit_FunctionDef(self, node):
                # Naming convention for function names
                if self.profile['naming_convention'] == "camelCase":
                    node.name = to_camel_case(node.name)
                elif self.profile['naming_convention'] == "snake_case":
                    node.name = to_snake_case(node.name)
                elif self.profile['naming_convention'] == "PascalCase":
                    node.name = to_pascal_case(node.name)
                return self.generic_visit(node)

            def visit_Name(self, node):
                # Variable names
                if self.profile['naming_convention'] == "camelCase":
                    node.id = to_camel_case(node.id)
                elif self.profile['naming_convention'] == "snake_case":
                    node.id = to_snake_case(node.id)
                elif self.profile['naming_convention'] == "PascalCase":
                    node.id = to_pascal_case(node.id)
                return node

        return StyleTransformer(self.user_profile).visit(tree)

# Example usage
if __name__ == "__main__":
    db = TelemetryDB()
    adapter = StyleAdapter(db)
    print("Generated .editorconfig:\n", adapter.generate_editorconfig())

    sample_code = "def TestFunction():\n    myVar = 10\n    print(myVar)"
    tree = ast.parse(sample_code)
    adapted_tree = adapter.adapt_ast(tree)
    print("Adapted AST:", ast.dump(adapted_tree, indent=4))
