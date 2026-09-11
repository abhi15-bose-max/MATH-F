"""Factory that turns an ExperimentConfig / ModelConfig into a CandidateModel."""
from __future__ import annotations

from .base import CandidateModel
from .mock import MockModel


def build_model(model_config) -> CandidateModel:
    """`model_config` is a `math_f.config.ModelConfig` (or any object with
    the same `.backend`, `.name`, `.revision`, `.max_new_tokens`,
    `.temperature`, `.top_p`, `.do_sample`, `.device_map`, `.dtype` fields).
    """
    backend = model_config.backend

    if backend == "mock":
        return MockModel()

    if backend == "hf":
        from .hf_model import HFModel  # lazy: avoid importing torch for mock runs

        return HFModel(
            model_name=model_config.name,
            model_revision=model_config.revision,
            max_new_tokens=model_config.max_new_tokens,
            temperature=model_config.temperature,
            top_p=model_config.top_p,
            do_sample=model_config.do_sample,
            device_map=model_config.device_map,
            dtype=model_config.dtype,
        )

    raise ValueError(f"Unknown model backend: {backend!r} (expected 'mock' or 'hf')")
