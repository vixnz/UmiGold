"""
Core Engine - Manages suggestion pipeline and feedback loop training
"""
from .suggestion_pipeline import SuggestionPipeline
from .feedback_looptrainer import FeedbackLoopTrainer

__all__ = ['SuggestionPipeline', 'FeedbackLoopTrainer']