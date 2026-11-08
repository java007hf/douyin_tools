"""OpenAI-compatible LLM provider used for prompt improvement."""
from __future__ import annotations

import json
from urllib import error as urlerror, request
from urllib.parse import urlsplit


class LLMError(RuntimeError):
    pass


def validate_agent_config(config):
    """Validate only AI Video's own settings; legacy configs use OpenAI."""
    values = dict(config or {})
    values['api_format'] = values.get('api_format') or 'openai'
    if values['api_format'] not in {'openai', 'ollama'}:
        raise LLMError('AI视频请选择 OpenAI 兼容或 Ollama 接口')
    for key in ('base_url', 'model'):
        values[key] = str(values.get(key) or '').strip()
        if not values[key]:
            raise LLMError('请在后台 AI视频 中填写 Agent API 地址和模型')
    parts = urlsplit(values['base_url'])
    if parts.scheme not in {'http', 'https'} or not parts.hostname:
        raise LLMError('AI视频 Agent API 地址必须是 http/https 地址')
    try:
        context = int(str(values.get('context_window', 16384)))
    except (TypeError, ValueError):
        raise LLMError('AI视频上下文窗口必须是整数') from None
    if not 4096 <= context <= 262144:
        raise LLMError('AI视频上下文窗口必须在 4096 到 262144 之间')
    values['context_window'] = context
    thinking = values.get('thinking_enabled', False)
    if isinstance(thinking, str) and thinking.lower() in {'true', 'false'}:
        thinking = thinking.lower() == 'true'
    if isinstance(thinking, str) and thinking.lower() == 'low':
        thinking = 'low'
    if type(thinking) is not bool and thinking != 'low':
        raise LLMError('AI视频思考模式必须是开启、关闭或低强度')
    values['thinking_enabled'] = thinking
    try:
        output_limit = int(str(values.get('output_token_limit', 6000)))
    except (TypeError, ValueError):
        raise LLMError('Ollama 输出预算必须是整数') from None
    if not 1024 <= output_limit <= 32768:
        raise LLMError('Ollama 输出预算必须在 1024 到 32768 之间')
    values['output_token_limit'] = output_limit
    defaults = values.get('use_model_sampling_defaults', False)
    if isinstance(defaults, str) and defaults.lower() in {'true', 'false'}:
        defaults = defaults.lower() == 'true'
    if type(defaults) is not bool:
        raise LLMError('Ollama 模型默认采样选项必须是开启或关闭')
    values['use_model_sampling_defaults'] = defaults
    return values


def create_agent_llm(config):
    values = validate_agent_config(config)
    if values.get('enabled') is False:
        raise LLMError('AI视频 Agent 已停用')
    client = OpenAICompatibleLLM(values['base_url'], str(values.get('api_key') or values.get('token') or ''),
                               values['model'], 600, api_format=values['api_format'],
                               context_window=values['context_window'], thinking_enabled=values['thinking_enabled'], output_token_limit=values['output_token_limit'],
                               use_model_sampling_defaults=values['use_model_sampling_defaults'])
    if values['api_format'] == 'ollama' and values['thinking_enabled'] == 'low':
        base = values['base_url'].rstrip('/')
        endpoint = base.removesuffix('/chat') + '/show' if base.endswith('/api/chat') else base.removesuffix('/v1') + '/api/show'
        headers = {'Content-Type': 'application/json'}
        if client.api_key:
            headers['Authorization'] = 'Bearer ' + client.api_key
        req = request.Request(endpoint, data=json.dumps({'model': values['model']}).encode(), headers=headers, method='POST')
        try:
            with request.urlopen(req, timeout=15) as response:
                metadata = json.loads(response.read())
        except Exception as exc:
            raise LLMError(f'读取 Ollama 思考档位失败：{exc}') from exc
        if 'low' not in (metadata.get('thinking') or {}).get('values', []):
            raise LLMError('当前 Ollama 模型未声明支持 low 思考档位，请选择普通开启或关闭')
        client.model_sampling_parameters = metadata.get('parameters')
        client.thinking_controls = metadata.get('thinking')
    return client


class OpenAICompatibleLLM:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 90, *, api_format='openai', context_window=16384, thinking_enabled=False, output_token_limit=6000, use_model_sampling_defaults=False):
        self.api_format = api_format
        self.context_window = context_window
        self.thinking_enabled = thinking_enabled
        self.output_token_limit = output_token_limit
        self.use_model_sampling_defaults = use_model_sampling_defaults
        self.last_response_metrics = {}
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

    def complete_json(self, system: str, prompt: str, *, keep_alive: int | None = None) -> dict:
        """Run a structured planning/review turn and require a JSON object."""
        endpoint = self.base_url if self.base_url.endswith("/chat/completions") else self.base_url + "/chat/completions"
        if self.api_format == 'ollama':
            endpoint = self.base_url if urlsplit(self.base_url).path.endswith('/api/chat') else self.base_url.removesuffix('/v1').rstrip('/') + '/api/chat'
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
            if self.api_format == 'ollama':
                payload = {'model': self.model, 'stream': True, 'think': self.thinking_enabled, 'format': 'json',
                           'options': {'temperature': payload['temperature'], 'num_predict': self.output_token_limit, 'num_ctx': self.context_window},
                           'messages': payload['messages']}
                if self.use_model_sampling_defaults:
                    payload['options'].pop('temperature')
                if keep_alive is not None:
                    payload['keep_alive'] = keep_alive
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers['Authorization'] = f'Bearer {self.api_key}'
            req = request.Request(endpoint, data=body, method="POST", headers=headers)
            try:
                with request.urlopen(req, timeout=self.timeout) as response:
                    if self.api_format == 'ollama':
                        chunks=[];size=0;thinking_size=0;metrics={}
                        for line in response:
                            if not line.strip(): continue
                            event=json.loads(line)
                            if event.get('error'): raise LLMError('Ollama: '+str(event['error']))
                            chunk=str(event.get('message',{}).get('content') or '')
                            thinking_size += len(str(event.get('message',{}).get('thinking') or ''))
                            chunks.append(chunk);size+=len(chunk)
                            if event.get('done'):
                                metrics = {key:event.get(key) for key in ('done_reason','eval_count','prompt_eval_count','total_duration')}
                            self.last_response_metrics = {**metrics, 'thinking_characters': thinking_size, 'content_characters': size}
                            if getattr(self,'on_progress',None): self.on_progress(size + thinking_size)
                        value=''.join(chunks).strip()
                        if metrics.get('done_reason') == 'length':
                            raise LLMError('Ollama 输出达到 token 上限，未接受截断的 JSON；请减少单次规划内容或增加模型输出预算')
                    else:
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
