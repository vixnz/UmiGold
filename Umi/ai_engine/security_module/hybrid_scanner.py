import re
import numpy as np
import torch
from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
from context_analyzer import ContextAnalyzer
import logging
import asyncio
from typing import List, Dict

logging.basicConfig(filename='hybrid_scanner.log', level=logging.WARNING)


class HybridScanner:
    def __init__(self):
        self.owasp_rules = self._load_owasp_rules()

        # Use a generic text classifier (placeholder: you should fine-tune CodeBERT for vuln detection)
        model_name = "microsoft/codebert-base"  # NOTE: not actually trained for classification
        self.anomaly_detector = pipeline(
            "text-classification",
            model=AutoModelForSequenceClassification.from_pretrained("distilbert-base-uncased-finetuned-sst-2-english"),
            tokenizer=AutoTokenizer.from_pretrained("distilbert-base-uncased-finetuned-sst-2-english")
        )

    def _load_owasp_rules(self) -> List[Dict]:
        """Load OWASP Top 10 patterns with risk weights"""
        return [
            {"name": "SQLi", "pattern": r"execute\(.*?\+.*?\)", "risk": 0.95},
            {"name": "XSS", "pattern": r"innerHTML\s*=\s*[^\"']*?[\+\{\$]", "risk": 0.90},
            {"name": "CmdInjection", "pattern": r"os\.system\(.*?\+.*?\)", "risk": 0.97}
        ]

    def rule_based_scan(self, code: str) -> List[Dict]:
        """First-pass detection using regex patterns"""
        findings = []
        for rule in self.owasp_rules:
            matches = re.finditer(rule["pattern"], code)
            for match in matches:
                findings.append({
                    "type": rule["name"],
                    "risk_score": rule["risk"],
                    "line": code[:match.start()].count('\n') + 1,
                    "snippet": match.group(0)
                })
        return findings

    def ml_validation(self, findings: List[Dict], context_embedding) -> List[Dict]:
        """Second-pass verification via anomaly detection"""
        validated = []
        for finding in findings:
            try:
                ml_result = self.anomaly_detector(
                    finding["snippet"],
                    top_k=2,
                    truncation=True
                )

                # Check for 'LABEL_1' (positive) as malicious in SST-2 model
                if ml_result[0]['label'] in ['LABEL_1', 'POSITIVE'] and ml_result[0]['score'] > 0.8:
                    finding["confidence"] = float(ml_result[0]['score'])
                    finding["context_aware_risk"] = min(
                        1.0,
                        finding["risk_score"] * float(torch.norm(context_embedding).item() / 10)
                    )
                    validated.append(finding)
            except Exception as e:
                logging.error(f"ML validation failed: {e}")
        return sorted(validated, key=lambda x: x.get("context_aware_risk", 0), reverse=True)

    def generate_mitigation(self, finding: Dict) -> str:
        """Auto-generate patched code snippet"""
        if finding["type"] == "SQLi":
            return "Use parameterized queries: cursor.execute('SELECT * FROM table WHERE id=%s', (user_input,))"
        elif finding["type"] == "XSS":
            return "Sanitize output: import html; element.innerHTML = html.escape(user_input)"
        elif finding["type"] == "CmdInjection":
            return "Use whitelisting: if user_input in ALLOWED_COMMANDS: os.system(user_input)"
        return "General mitigation: validate inputs, sanitize outputs, apply least privilege."


# Example usage
if __name__ == "__main__":
    async def main():
        scanner = HybridScanner()
        ctx_analyzer = ContextAnalyzer()
        dangerous_code = "cursor.execute('SELECT * FROM users WHERE id=' + user_id)"
        findings = scanner.rule_based_scan(dangerous_code)
        embedding = await ctx_analyzer.get_context_embedding(["app.py"])
        validated = scanner.ml_validation(findings, embedding)
        if validated:
            print(f"Critical {validated[0]['type']} detected: {scanner.generate_mitigation(validated[0])}")
        else:
            print("No validated vulnerabilities found.")

    asyncio.run(main())
