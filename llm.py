from typing import Dict, List
from abc import ABC, abstractmethod

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

class BaseLLM(ABC):
    @abstractmethod
    def chat(self, messages: List[Dict[str, str]]) -> str:
        raise NotImplementedError

class LocalQwenLLM(BaseLLM):
    def __init__(
        self,
        model_path: str,
        max_tokens: int = 512,
        temperature: float = 0.1,
        down_sample: bool = False,
        torch_dtype: str | torch.dtype = "auto",
        device_map: str | dict | None = "auto",
    ) -> None:
        self.model_path = model_path
        self.device_map = device_map
        self.max_new_tokens = max_tokens
        self.temperature = temperature
        self.do_sample = down_sample
        self.torch_dtype = torch_dtype

        self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)

        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            torch_dtype=self.torch_dtype,
            device_map=self.device_map,
        )
        self.model.eval()

    def chat(self, messages: List[Dict[str, str]]) -> str:
        if not messages:
            raise ValueError("messages must not be empty")

        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        model_inputs = self.tokenizer(
            [text],
            return_tensors="pt",
        ).to(self.model.device)

        with torch.no_grad():
            generated_ids = self.model.generate(
                **model_inputs,
                max_new_tokens=self.max_new_tokens,
                temperature=self.temperature,
                do_sample=self.do_sample,
            )

        generated_ids = [
            output_ids[len(input_ids):]
            for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
        ]

        response = self.tokenizer.batch_decode(
            generated_ids,
            skip_special_tokens=True,
        )[0]

        return response.strip()