import torch
import numpy as np
from telemetry_db import TelemetryDB
from refactor_optimizer import RefactorEngine
import docker
import time
import logging
from collections import deque
import os
import threading

logging.basicConfig(filename='trainer.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


class FeedbackTrainer:
    def __init__(self, telemetry_db: TelemetryDB, refactor_engine: RefactorEngine,
                 replay_size: int = 10000, exploration_rate: float = 0.15):
        self.db = telemetry_db
        self.engine = refactor_engine
        self.client = docker.from_env()
        self.replay_buffer = deque(maxlen=replay_size)
        self.model_version = 1.0
        self.exploration_rate = exploration_rate
        self.lock = threading.Lock()  # Thread safety for version updates

    def _sample_training_batch(self, batch_size: int = 32):
        """Create training samples from telemetry with acceptance/rejection labels"""
        adaptation_data = self.db.get_adaptation_data()
        samples = []

        for suggestion_id, acceptance_ratio in adaptation_data.items():
            context = self.engine.get_suggestion_context(suggestion_id)
            if context:
                samples.append({
                    'input': context['embedding'],
                    'label': 1 if acceptance_ratio > 0.5 else 0,
                    'weight': abs(acceptance_ratio - 0.5) * 2
                })
        
        # Store in replay buffer
        self.replay_buffer.extend(samples)

        # Sample batch from replay buffer
        return list(np.random.choice(list(self.replay_buffer), min(batch_size, len(self.replay_buffer))))

    def _update_model(self, model_path: str):
        """Launch isolated training container with mounted model volume"""
        container = self.client.containers.run(
            "pytorch/training:latest",
            command=f"python train.py --input /data/model.pt --version {self.model_version}",
            volumes={os.path.abspath(model_path): {'bind': '/data/model.pt', 'mode': 'rw'}},
            detach=True,
            runtime="nvidia" if torch.cuda.is_available() else None
        )
        return container

    def _validate_model(self, container):
        """Monitor training and validate new model performance"""
        try:
            for line in container.logs(stream=True):
                decoded = line.decode().strip()
                logging.info(decoded)
                if "Validation accuracy" in decoded:
                    acc = float(decoded.split(": ")[1])
                    if acc < 0.7:
                        logging.warning(f"Model accuracy {acc} below threshold, rolling back")
                        return False
            return True
        finally:
            container.remove(force=True)  # Ensure container cleanup

    def run_training_cycle(self):
        """Execute full training pipeline with safety checks"""
        try:
            training_data = self._sample_training_batch()
            if not training_data:
                logging.info("No sufficient data for training")
                return

            model_file = f"model_v{self.model_version:.1f}.pt"
            torch.save(training_data, f"training_batch_v{self.model_version:.1f}.pt")
            container = self._update_model(model_file)

            if self._validate_model(container):
                with self.lock:
                    self.engine.load_model(model_file)
                    logging.info(f"Model promoted to v{self.model_version:.1f}")
                    self.model_version += 0.1
            else:
                os.remove(model_file)
                logging.warning(f"Discarded model {model_file} due to validation failure")

        except docker.errors.DockerException as e:
            logging.error(f"Docker container failed: {e}")
        except Exception as e:
            logging.critical(f"Training cycle aborted: {e}")

    def start_periodic_training(self, interval_hours: float = 12):
        """Start periodic training in a separate thread"""
        def periodic():
            while True:
                self.run_training_cycle()
                time.sleep(interval_hours * 3600)

        thread = threading.Thread(target=periodic, daemon=True)
        thread.start()
        logging.info("Started periodic training thread.")


# Example usage
if __name__ == "__main__":
    db = TelemetryDB()
    engine = RefactorEngine()
    trainer = FeedbackTrainer(db, engine)

    # Run a single cycle
    trainer.run_training_cycle()

    # Optional: start periodic cycles
    # trainer.start_periodic_training(interval_hours=6)
