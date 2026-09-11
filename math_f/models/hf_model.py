"""Real local inference backend using Hugging Face Transformers.

Heavy dependencies (torch, transformers) are imported lazily inside
`__init__` so that importing `math_f.models` -- and therefore the whole
package, including in unit tests -- never requires a GPU stack to be
installed. Only actually constructing an `HFModel` does.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import CandidateModel, GenerationResult


@dataclass
class HFModel(CandidateModel):
    model_name: str
    model_revision: Optional[str] = None
    max_new_tokens: int = 1024
    temperature: float = 0.0
    top_p: float = 0.95
    do_sample: bool = False
    device_map: str = "auto"
    dtype: str = "auto"

    def __post_init__(self) -> None:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as e:
            raise RuntimeError(
                "The 'hf' model backend requires torch and transformers. "
                "Install them (see requirements.txt) or use --backend mock."
            ) from e

        self._torch = torch

        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name, revision=self.model_revision
        )

        resolved_dtype = self._resolve_dtype(torch)

        load_kwargs = dict(revision=self.model_revision, torch_dtype=resolved_dtype)
        if torch.cuda.is_available():
            load_kwargs["device_map"] = self.device_map

        self.model = AutoModelForCausalLM.from_pretrained(self.model_name, **load_kwargs)
        if not torch.cuda.is_available():
            self.model.to("cpu")
        self.model.eval()

    def _resolve_dtype(self, torch):
        if self.dtype == "float32":
            return torch.float32
        if self.dtype == "float16":
            return torch.float16
        if self.dtype == "bfloat16":
            return torch.bfloat16
        # "auto": prefer bf16 on capable GPUs, else fp16 on GPU, else fp32 on CPU.
        if torch.cuda.is_available():
            return torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
        return torch.float32

    def generate(self, prompt: str) -> GenerationResult:
        torch = self._torch
        messages = [
            {"role": "system", "content": "You are an expert in mathematics and Lean 4."},
            {"role": "user", "content": prompt},
        ]

        if hasattr(self.tokenizer, "apply_chat_template"):
            rendered = self.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        else:
            rendered = prompt

        inputs = self.tokenizer(rendered, return_tensors="pt")
        device = getattr(self.model, "device", None)
        if device is not None:
            inputs = {k: v.to(device) for k, v in inputs.items()}

        gen_kwargs = dict(
            max_new_tokens=self.max_new_tokens,
            do_sample=self.do_sample,
            pad_token_id=(self.tokenizer.pad_token_id or self.tokenizer.eos_token_id),
        )
        if self.do_sample:
            gen_kwargs["temperature"] = max(self.temperature, 1e-5)
            gen_kwargs["top_p"] = self.top_p

        with torch.no_grad():
            output = self.model.generate(**inputs, **gen_kwargs)

        input_len = inputs["input_ids"].shape[1]
        generated_ids = output[0][input_len:]
        text = self.tokenizer.decode(generated_ids, skip_special_tokens=True).strip()

        return GenerationResult(
            raw_text=text,
            input_tokens=int(input_len),
            output_tokens=int(generated_ids.shape[0]),
        )
