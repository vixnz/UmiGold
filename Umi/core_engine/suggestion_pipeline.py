from context_analyzer import ContextAnalyzer
from refactor_optimizer import RefactorEngine
from style_adapter import StyleAdapter
from telemetry_db import TelemetryDB
import threading
import queue
import time
import logging
from enum import Enum
from typing import Optional, Dict, Any, List

logging.basicConfig(
    filename='pipeline.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class PipelineStage(Enum):
    CONTEXT_ANALYSIS = 1
    VULNERABILITY_SCAN = 2
    OPTIMIZATION_GEN = 3
    STYLE_ADAPTATION = 4
    TELEMETRY_HOOK = 5

class SuggestionPipeline:
    def __init__(self, telemetry_db: TelemetryDB, max_queue_size: int = 100):
        self.db = telemetry_db
        self.context_analyzer = ContextAnalyzer()
        self.refactor_engine = RefactorEngine()
        self.style_adapter = StyleAdapter(telemetry_db)
        self.task_queue: queue.PriorityQueue = queue.PriorityQueue(maxsize=max_queue_size)
        self.worker_threads: List[threading.Thread] = []
        self.stop_event = threading.Event()
        self.results: List[Dict[str, Any]] = []

    def ingest_code_context(self, file_path: str, code: str, priority: int = 5):
        """Queue code processing task with configurable priority"""
        task = {
            'stage': PipelineStage.CONTEXT_ANALYSIS,
            'file_path': file_path,
            'code': code,
            'metadata': {},
            'attempts': 0
        }
        logging.info(f"Ingesting code for file {file_path} with priority {priority}")
        self.task_queue.put((priority, task))

    def _worker_loop(self):
        while not self.stop_event.is_set():
            try:
                priority, task = self.task_queue.get(timeout=1)
                self._process_task(task)
            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"Worker encountered unexpected error: {e}")

    def _process_task(self, task: dict):
        """Process a task through the pipeline stages"""
        try:
            task['attempts'] += 1
            stage = task['stage']

            if stage == PipelineStage.CONTEXT_ANALYSIS:
                task['context_report'] = self.context_analyzer.analyze(task['code'])
                task['stage'] = PipelineStage.VULNERABILITY_SCAN

            elif stage == PipelineStage.VULNERABILITY_SCAN:
                task['vuln_report'] = self.context_analyzer.scan_vulnerabilities(
                    task['code'],
                    task['context_report']
                )
                task['stage'] = PipelineStage.OPTIMIZATION_GEN

            elif stage == PipelineStage.OPTIMIZATION_GEN:
                task['optimizations'] = self.refactor_engine.generate_optimizations(
                    task['code'],
                    task['context_report'],
                    vuln_report=task.get('vuln_report')
                )
                task['stage'] = PipelineStage.STYLE_ADAPTATION

            elif stage == PipelineStage.STYLE_ADAPTATION:
                adapted_optimizations = []
                for opt in task['optimizations']:
                    adapted_code = self.style_adapter.adapt_code_snippet(opt['suggested_code'])
                    adapted_optimizations.append({**opt, 'adapted_code': adapted_code})
                task['final_suggestions'] = adapted_optimizations
                task['stage'] = PipelineStage.TELEMETRY_HOOK

            elif stage == PipelineStage.TELEMETRY_HOOK:
                for suggestion in task['final_suggestions']:
                    self.db.record_interaction(
                        event_type='GENERATED',
                        suggestion_id=suggestion['id'],
                        context_embedding=suggestion.get('context_embedding', b'')
                    )
                logging.info(f"Task for {task['file_path']} completed successfully")
                self.results.append(task)
                return  # Terminal stage

            # Requeue for next stage with slightly higher priority to avoid starvation
            self.task_queue.put((max(0, task.get('priority', 5) - 1), task))

        except Exception as e:
            logging.error(f"Pipeline stage {task['stage']} failed: {e}")
            if task['attempts'] < 3:
                logging.info(f"Retrying task {task.get('file_path')}, attempt {task['attempts']}")
                self.task_queue.put((task.get('priority', 5), task))
            else:
                self.db.record_interaction(
                    event_type='PIPELINE_ERROR',
                    suggestion_id=f"ERR_{task['stage'].name}",
                    context_embedding=b''
                )
                logging.error(f"Task failed after 3 attempts: {task.get('file_path')}")

    def start_workers(self, num_workers: int = 4):
        """Launch parallel processing threads"""
        for _ in range(num_workers):
            thread = threading.Thread(target=self._worker_loop, daemon=True)
            thread.start()
            self.worker_threads.append(thread)
        logging.info(f"Started {num_workers} worker threads")

    def shutdown(self):
        """Gracefully shutdown the pipeline"""
        logging.info("Shutting down pipeline...")
        self.stop_event.set()
        for thread in self.worker_threads:
            thread.join(timeout=5)
        logging.info("Pipeline shutdown complete")

if __name__ == "__main__":
    db = TelemetryDB()
    pipeline = SuggestionPipeline(db)
    pipeline.start_workers(num_workers=4)

    # Simulate code ingestion
    sample_code = "def calculate(a, b):\n    return a + b"
    pipeline.ingest_code_context("test.py", sample_code, priority=3)

    time.sleep(2)  # Allow processing
    pipeline.shutdown()
