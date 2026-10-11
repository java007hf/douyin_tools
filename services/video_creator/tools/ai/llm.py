"""OpenAI-compatible LLM provider used for prompt improvement."""
from __future__ import annotations

import json
from urllib import error as urlerror, request


class LLMError(RuntimeError):
    pass


class OpenAICompatibleLLM:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 90):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        if self.api_key.lower().startswith("bearer "):
            self.api_key = self.api_key[7:].strip()
        if self.api_key.lower().startswith(("http://", "https://")):
            raise LLMError("LLM API Key 配置错误：API Key 不能填写 API 地址，请填写 ARK_API_KEY 的实际值")
        self.model = model
        self.timeout = timeout

    def improve(self, prompt: str, instruction: str, kind: str) -> str:
        role = "生图" if kind == "image" else "生视频"
        system = (
            f"你是专业的{role}提示词编辑。根据用户原始提示词和改善要求，输出一段可以直接交给生成模型的最终提示词。"
            "保留用户的主体和意图，补充主体外观、动作、环境、构图、镜头、光线、风格等有效细节。"
            "只输出改善后的提示词，不要解释，不要加引号，不要使用Markdown。"
        )
        if instruction.strip():
            system += "\n用户额外的改善要求：" + instruction.strip()
        payload = {
            "model": self.model,
            "temperature": 0.7,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt.strip()},
            ],
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        endpoint = self.base_url if self.base_url.endswith("/chat/completions") else self.base_url + "/chat/completions"
        req = request.Request(
            endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                result = json.loads(response.read())
        except urlerror.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            raise LLMError(f"LLM request failed: HTTP {exc.code}: {detail[:1000]}") from exc
        except Exception as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        try:
            value = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"LLM returned an invalid response: {result}") from exc
        value = str(value).strip()
        if not value:
            raise LLMError("LLM returned an empty prompt")
        return value

    def complete_json(self, system: str, prompt: str) -> dict:
        """Run a structured planning/review turn and require a JSON object."""
        endpoint = self.base_url if self.base_url.endswith("/chat/completions") else self.base_url + "/chat/completions"
        last_error = None
        for attempt in range(2):
            system_prompt = system
            if attempt:
                system_prompt += "\n\n这是一次结构化输出重试。请输出紧凑但完整的 JSON 对象，所有字符串必须正确闭合并转义，不要 Markdown，不要解释，不要省略必需字段。"
            payload = {
                "model": self.model,
                "temperature": 0.2 if attempt else 0.4,
                # Production storyboards can exceed the provider's small default
                # completion budget. A cut-off JSON object cannot be repaired by
                # parsing; request enough room for the complete contract.
                "max_tokens": 12000,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt.strip()},
                ],
            }
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = request.Request(endpoint, data=body, method="POST", headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
            try:
                with request.urlopen(req, timeout=self.timeout) as response:
                    result = json.loads(response.read())
                value = str(result["choices"][0]["message"]["content"]).strip()
                if value.startswith("```"):
                    value = value.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                parsed = json.loads(value)
                if not isinstance(parsed, dict):
                    raise ValueError("root is not an object")
                return parsed
            except urlerror.HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    detail = ""
                last_error = LLMError(f"LLM structured request failed: HTTP {exc.code}: {detail[:1000]}")
                break
            except Exception as exc:
                last_error = exc
                if isinstance(exc, LLMError) or attempt:
                    break
        if isinstance(last_error, LLMError):
            raise last_error
        raise LLMError(f"LLM structured request failed: {last_error}") from last_error
