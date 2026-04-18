# llms/gpt.py
from importlib import import_module
from openai import OpenAI
from loguru import logger
from src.llms_closed.base_llm import BaseLLM
conf = import_module("configs.config")


class DeepSeek(BaseLLM):
    def __init__(self, model_name="deepseek-chat", temperature=None, max_new_tokens=None, report=False):
        super().__init__(model_name, temperature, max_new_tokens)
        self.report = report

        # 初始化 OpenAI 客户端
        self.client = OpenAI(
            api_key=conf.DeepSeek_key,
            base_url=conf.DeepSeek_base
        )
        if model_name is None:
            self.model_name = conf.DeepSeek_model
        else:
            self.model_name = model_name
        if temperature is None:
            self.temperature = conf.DeepSeek_temperature
        else:
            self.temperature = temperature

        if max_new_tokens is None:
            self.max_new_tokens = conf.max_new_tokens
        else:
            self.max_new_tokens = max_new_tokens

    def request(self, query: str) -> str:

        resp = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": query}],
            temperature=self.temperature,
            max_tokens=self.max_new_tokens,
        )
        # print(resp)
        res_text = resp.choices[0].message.content

        if self.report and hasattr(resp, "usage"):
            logger.info(
                f"[DeepSeek] {self.model_name} token consumed: {resp.usage.total_tokens}")

        return res_text


if __name__ == "__main__":
    # logger.info("=== 测试 GPT API ===")
    deepseek = DeepSeek(model_name="deepseek-chat", report=True, temperature=0.01,
                        max_new_tokens=2048,)
    print("DeepSeek 回复:", deepseek.request("介绍一下清华大学"))
