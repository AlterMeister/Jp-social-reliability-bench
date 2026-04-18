# llms/gpt.py
from importlib import import_module
from openai import OpenAI
from loguru import logger
from src.llms_closed.base_llm import BaseLLM
conf = import_module("configs.config")


class Gemini(BaseLLM):
    def __init__(self, model_name="gemini-3-flash-preview", temperature=None, max_new_tokens=None, report=False):
        super().__init__(model_name, temperature, max_new_tokens)
        self.report = report

        # 初始化 OpenAI 客户端
        self.client = OpenAI(
            api_key=conf.Gemini_api_key,
            base_url=conf.Gemini_api_base
        )
        if model_name is None:
            self.model_name = conf.Gemini_model
        else:
            self.model_name = model_name
        if temperature is None:
            self.temperature = conf.Gemini_temperature
        else:
            self.temperature = temperature

        if max_new_tokens is None:
            self.max_new_tokens = conf.max_new_tokens
        else:
            self.max_new_tokens = max_new_tokens

    def request(self, query: str, system_prompt: str = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": query})

        resp = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_new_tokens,
        )

        res_text = resp.choices[0].message.content
        if self.report and hasattr(resp, "usage"):
            logger.info(
                f"[Claude] {self.model_name} token consumed: {resp.usage.total_tokens}"
            )

        return res_text


if __name__ == "__main__":
    # logger.info("=== 测试 GPT API ===")
    gemini = Gemini(model_name="gemini-3-flash-preview", report=True, temperature=0.01,
                    max_new_tokens=2048,)
    print("Gemini 回复:", gemini.request("介绍一下清华大学"))
