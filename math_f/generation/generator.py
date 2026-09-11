"""Thin orchestration layer: takes an already-built prompt string, calls the
model, times it, and deterministically cleans the result.

Prompt construction itself lives in `math_f.repair.prompts` (it needs
verifier feedback, so it naturally belongs next to the repair loop); this
module stays prompt-agnostic to avoid a circular import between
`generation` and `repair`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from math_f.models.base import CandidateModel
from .output_cleaner import CleanResult, clean_model_output


@dataclass
class GenerationRecord:
    raw_model_output: str
    cleaned_candidate: Optional[str]
    cleaning_status: str
    cleaning_reason: Optional[str]
    generation_latency_ms: int
    input_tokens: Optional[int]
    output_tokens: Optional[int]

    def to_dict(self) -> dict:
        return {
            "raw_model_output": self.raw_model_output,
            "cleaned_candidate": self.cleaned_candidate,
            "cleaning_status": self.cleaning_status,
            "cleaning_reason": self.cleaning_reason,
        }

    def runtime_dict(self) -> dict:
        return {
            "generation_latency_ms": self.generation_latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
        }


class CandidateGenerator:
    def __init__(self, model: CandidateModel, cleaner=clean_model_output):
        self.model = model
        self.cleaner = cleaner

    def generate(self, prompt: str) -> GenerationRecord:
        started = time.perf_counter()
        result = self.model.generate(prompt)
        latency_ms = int((time.perf_counter() - started) * 1000)

        clean_result: CleanResult = self.cleaner(result.raw_text)

        return GenerationRecord(
            raw_model_output=result.raw_text,
            cleaned_candidate=clean_result.cleaned_candidate,
            cleaning_status=clean_result.status,
            cleaning_reason=clean_result.reason,
            generation_latency_ms=latency_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
