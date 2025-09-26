import ast
import numpy as np
import torch
from sklearn.ensemble import RandomForestRegressor
from context_analyzer import ContextAnalyzer
import logging
import re
from typing import Dict, List
import asyncio

logging.basicConfig(filename='refactor_optimizer.log', level=logging.INFO,
                    format='%(asctime)s:%(levelname)s:%(message)s')


class RefactorOptimizer:
    def __init__(self, context_analyzer: ContextAnalyzer):
        self.context = context_analyzer
        self.pattern_registry = self._load_patterns()
        self.impact_model = self._train_impact_model()

    def _load_patterns(self) -> Dict[str, dict]:
        """Load anti-patterns from predefined rules with severity scores"""
        return {
            "NestedLoop": {
                "pattern": r"for\s+.*:\s*\n\s*for\s+.*:",
                "severity": 0.8,
                "fix": "Consider vectorization (NumPy/Pandas) or itertools.product"
            },
            "RedundantCall": {
                "pattern": r"(\w+)\s*=\s*\1\(\)",  # foo = foo()
                "severity": 0.6,
                "fix": "Memoize or cache result instead of redundant calls"
            },
            "UncheckedInput": {
                "pattern": r"input\s*\(.*\)",
                "severity": 0.9,
                "fix": "Validate and sanitize user input"
            }
        }

    def _train_impact_model(self) -> RandomForestRegressor:
        """Train ML model on synthetic performance impact dataset"""
        # Synthetic features: [severity, snippet_length, context_mean]
        X = np.array([
            [0.8, 50, 0.1],
            [0.2, 10, -0.05],
            [0.9, 100, 0.2]
        ])
        y = np.array([0.85, 0.15, 0.92])  # Performance impact scores
        model = RandomForestRegressor(n_estimators=100, random_state=42)
        model.fit(X, y)
        return model

    def detect_anti_patterns(self, code: str) -> List[dict]:
        """Scan code for registered inefficiency patterns with location tracking"""
        findings = []
        for name, rule in self.pattern_registry.items():
            matches = re.finditer(rule["pattern"], code, re.MULTILINE)
            for match in matches:
                start_line = code[:match.start()].count('\n') + 1
                findings.append({
                    "pattern": name,
                    "severity": rule["severity"],
                    "fix_suggestion": rule["fix"],
                    "line": start_line,
                    "code_snippet": match.group(0)
                })
        return findings

    def rank_optimizations(self, findings: List[dict], context_embedding: torch.Tensor) -> List[dict]:
        """Apply ML model to predict optimization impact score"""
        ranked = []
        if context_embedding is None or context_embedding.numel() == 0:
            context_mean = 0.0
        else:
            context_mean = float(torch.mean(context_embedding).item())

        for finding in findings:
            features = np.array([[
                finding["severity"],
                len(finding["code_snippet"]),
                context_mean
            ]])
            impact_score = self.impact_model.predict(features)[0]
            ranked.append({**finding, "impact_score": float(impact_score)})

        return sorted(ranked, key=lambda x: x["impact_score"], reverse=True)


# Example usage
if __name__ == "__main__":
    async def main():
        ctx_analyzer = ContextAnalyzer()
        optimizer = RefactorOptimizer(ctx_analyzer)

        sample_code = """
for i in range(100):
    for j in range(100):
        print(i*j)
user_input = input('Enter: ')
"""

        findings = optimizer.detect_anti_patterns(sample_code)
        embedding = await ctx_analyzer.get_context_embedding(["test.py"])
        ranked = optimizer.rank_optimizations(findings, embedding)

        if ranked:
            print("Top optimization:", ranked[0])
        else:
            print("No anti-patterns detected")

    asyncio.run(main())
