"""Model abstraction.

Every backend (mock, Hugging Face Transformers, ...) implements the same
narrow interface: given a task and optional repair context, return the raw
text the model produced. The caller is solely responsible for parsing,
cleaning, and verifying that text -- the model is never trusted.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class GenerationResult:
    raw_text: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


class CandidateModel(ABC):
    #: Human-readable model identity, filled in by concrete backends and
    #: recorded verbatim into every trajectory for provenance (spec section 21).
    model_name: str = "unknown"
    model_revision: Optional[str] = None

    @abstractmethod
    def generate(self, prompt: str) -> GenerationResult:
        """Return the model's raw text completion for `prompt`.

        `prompt` is a fully rendered string built by
        `math_f.repair.prompts`; backends are not responsible for prompt
        construction, only for turning a prompt into raw text.
        """
        raise NotImplementedError
