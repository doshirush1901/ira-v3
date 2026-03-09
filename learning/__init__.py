"""
Learning System - Cognitive Maturity for Ira
=============================================

Self-awareness about knowledge quality:
- LearningHub: Central registry of learned patterns with decay and reinforcement
- PredictionLog: Track verifiable predictions and reconcile with outcomes
- Confidence calibration: Patterns earn trust through real-world accuracy
"""
from .learning_hub import (
    LearningHub,
    LearnedPattern,
    PatternType,
    get_learning_hub,
)
from .prediction_log import (
    PredictionLog,
    get_prediction_log,
)

__all__ = [
    "LearningHub",
    "LearnedPattern",
    "PatternType",
    "get_learning_hub",
    "PredictionLog",
    "get_prediction_log",
]
