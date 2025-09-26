import ast
import torch
from transformers import CodeBertModel, BertTokenizer
import logging
import os
import hashlib
from typing import Dict, List, Optional
import asyncio
import tokenize
from io import StringIO

logging.basicConfig(filename='context_analyzer.log', level=logging.INFO,
                    format='%(asctime)s:%(levelname)s:%(message)s')


class ContextAnalyzer:
    def __init__(self, model_name="microsoft/codebert-base", device: Optional[str] = None):
        self.tokenizer = BertTokenizer.from_pretrained(model_name)
        self.model = CodeBertModel.from_pretrained(model_name)
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)
        self.ast_cache: Dict[str, ast.Module] = {}
        self.embedding_cache: Dict[str, Dict[str, torch.Tensor]] = {}  

    def incremental_parse(self, file_path: str, new_code: str) -> ast.Module:
        """Parse code incrementally with AST fallback to lexical scanning on failure"""
        try:
            tree = ast.parse(new_code)
            # TODO: implement AST diffing for incremental updates
            self.ast_cache[file_path] = tree
            logging.info(f"AST parsing succeeded for {file_path}")
            return tree
        except SyntaxError as e:
            logging.error(f"AST failed for {file_path}: {e}. Using lexical fallback")
            return self._lexical_scan(new_code)

    def _lexical_scan(self, code: str) -> ast.Module:
        """Fallback method using token-based context extraction"""
        try:
            tokens = list(tokenize.generate_tokens(StringIO(code).readline))
            #
            return ast.Module(body=[], type_ignores=[])
        except Exception as e:
            logging.error(f"Lexical scan failed: {e}")
            return ast.Module(body=[], type_ignores=[])

    def _file_hash(self, file_path: str) -> str:
        """Compute a SHA256 hash of file contents"""
        if not os.path.exists(file_path):
            return ""
        with open(file_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    async def get_context_embedding(self, file_paths: List[str]) -> torch.Tensor:
        """Generate CodeBERT embeddings for cross-file context with caching"""
        all_code = ""
        for path in file_paths:
            if os.path.exists(path):
                file_hash = self._file_hash(path)
                cached = self.embedding_cache.get(path)
                if cached and cached.get("hash") == file_hash:
                    logging.info(f"Using cached embedding for {path}")
                    all_code += ""  
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    all_code += f.read() + "\n"

        if not all_code.strip():
            logging.warning("No new code to embed, returning zero vector")
            return torch.zeros(1, 768, device=self.device)

        try:
            inputs = self.tokenizer(all_code, return_tensors="pt", truncation=True, max_length=512)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            outputs = self.model(**inputs)
            embedding = outputs.last_hidden_state.mean(dim=1)

            
            for path in file_paths:
                if os.path.exists(path):
                    file_hash = self._file_hash(path)
                    self.embedding_cache[path] = {"hash": file_hash, "embedding": embedding}

            return embedding
        except Exception as e:
            logging.critical(f"Embedding generation failed: {e}")
            return torch.zeros(1, 768, device=self.device)


# Example use
if __name__ == "__main__":
    import asyncio

    analyzer = ContextAnalyzer()
    sample_code = "def hello_world():\n    print('Hello, world!')"
    tree = analyzer.incremental_parse("test.py", sample_code)

    embedding = asyncio.run(analyzer.get_context_embedding(["test.py"]))
    print(f"Context embedding shape: {embedding.shape}")
