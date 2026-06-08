from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any
from urllib.parse import urlparse

import httpx
from openai import AsyncOpenAI
from portkey_ai import Portkey

from app.tradebot.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from app.tradebot.models.schema import OpenAIAnalysis, SignalState

logger = logging.getLogger(__name__)


class OpenAIAnalyzer:
    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str | None = None,
        portkey_api_key: str | None = None,
        timeout_seconds: int = 20,
    ) -> None:
        self._model = model
        normalized_base_url = self._normalize_base_url(base_url)
        self._base_url = normalized_base_url
        self._timeout_seconds = timeout_seconds
        self._api_key = api_key
        self._use_portkey = bool(normalized_base_url and 'api.portkey.ai' in normalized_base_url)
        # Use direct httpx for any custom base URL to avoid OpenAI SDK injecting blocked headers
        self._use_direct_httpx = bool(normalized_base_url) and not self._use_portkey
        self._force_chat_completions = normalized_base_url is not None
        self._portkey_client = Portkey(api_key=portkey_api_key) if self._use_portkey and portkey_api_key else None
        self._client = None
        if not self._use_portkey and not self._use_direct_httpx and api_key:
            self._client = AsyncOpenAI(api_key=api_key, base_url=normalized_base_url)

    async def analyze(
        self,
        signal: SignalState,
        chart_image: bytes | None = None,
        chart_timeframe: str | None = None,
    ) -> OpenAIAnalysis:
        payload = self._build_payload(signal, chart_timeframe)

        if self._use_portkey:
            return await self._analyze_with_portkey(signal, payload, chart_image)
        if self._use_direct_httpx:
            return await self._analyze_with_direct_httpx(signal, payload)
        if self._client is None:
            return OpenAIAnalysis()

        if chart_image is not None:
            try:
                content = await self._analyze_with_chat_completions(payload, chart_image=chart_image)
                return OpenAIAnalysis.model_validate(content)
            except Exception as chart_exc:  # noqa: BLE001
                logger.warning(
                    'OpenAI multimodal analysis failed for %s, falling back to text-only: %s',
                    signal.symbol,
                    chart_exc,
                )

        if not self._force_chat_completions:
            try:
                content = await self._analyze_with_responses(payload)
                return OpenAIAnalysis.model_validate(content)
            except Exception as responses_exc:  # noqa: BLE001
                logger.warning(
                    'OpenAI responses API failed for %s, falling back to chat.completions: %s',
                    signal.symbol,
                    responses_exc,
                )
        try:
            content = await self._analyze_with_chat_completions(payload)
            return OpenAIAnalysis.model_validate(content)
        except Exception as exc:  # noqa: BLE001
            logger.warning('OpenAI analysis failed for %s: %s', signal.symbol, exc)
            return OpenAIAnalysis()

    async def _analyze_with_portkey(
        self,
        signal: SignalState,
        payload: dict[str, Any],
        chart_image: bytes | None,
    ) -> OpenAIAnalysis:
        if self._portkey_client is None:
            return OpenAIAnalysis()

        try:
            content = await asyncio.to_thread(self._portkey_chat_completion, payload, chart_image)
            if not content:
                raise ValueError('Empty Portkey chat completion content')
            return OpenAIAnalysis.model_validate(self._extract_json(content))
        except Exception as exc:  # noqa: BLE001
            if chart_image is not None:
                logger.warning(
                    'Portkey multimodal analysis failed for %s, falling back to text-only: %s',
                    signal.symbol,
                    exc,
                )
                try:
                    content = await asyncio.to_thread(self._portkey_chat_completion, payload, None)
                    if not content:
                        raise ValueError('Empty Portkey text-only chat completion content')
                    return OpenAIAnalysis.model_validate(self._extract_json(content))
                except Exception as fallback_exc:  # noqa: BLE001
                    logger.warning('Portkey text-only fallback failed for %s: %s', signal.symbol, fallback_exc)
            logger.warning('Portkey analysis failed for %s: %s', signal.symbol, exc)
            return OpenAIAnalysis()

    async def _analyze_with_direct_httpx(
        self,
        signal: SignalState,
        payload: dict[str, Any],
    ) -> OpenAIAnalysis:
        if not self._base_url or not self._api_key:
            return OpenAIAnalysis()

        try:
            return await self._direct_httpx_request(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning('Direct httpx analysis failed for %s: %s', signal.symbol, exc)
            return OpenAIAnalysis()

    def _portkey_chat_completion(
        self,
        payload: dict[str, Any],
        chart_image: bytes | None = None,
    ) -> str:
        response = self._portkey_client.chat.completions.create(
            model=self._model,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': self._chat_user_content(payload, chart_image=chart_image)},
            ],
            max_tokens=512,
        )
        return response.choices[0].message.content

    async def _analyze_with_responses(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.responses.create(
            model=self._model,
            input=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': build_user_prompt(payload)},
            ],
            text={'format': {'type': 'text'}},
        )
        return self._extract_json(response.output_text)

    async def _analyze_with_chat_completions(
        self,
        payload: dict[str, Any],
        chart_image: bytes | None = None,
    ) -> dict[str, Any]:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': self._chat_user_content(payload, chart_image=chart_image)},
            ],
            max_tokens=512,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError('Empty chat completion content')
        return self._extract_json(content)

    async def _direct_httpx_request(
        self,
        payload: dict[str, Any],
    ) -> OpenAIAnalysis:
        headers = {
            'Authorization': f'Bearer {self._api_key}',
            'Content-Type': 'application/json',
        }
        request_body = {
            'model': self._model,
            'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': build_user_prompt(payload)},
            ],
            'max_tokens': 512,
        }
        url = self._chat_completion_url(self._base_url)

        last_exc: Exception | None = None
        async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout_seconds)) as client:
            for attempt in range(4):
                try:
                    response = await client.post(url, headers=headers, json=request_body)
                    response.raise_for_status()
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt < 3:
                        await asyncio.sleep(3 * (attempt + 1))  # 3s, 6s, 9s
            else:
                raise last_exc
        # Server may append SSE "data: [DONE]" after the JSON — extract the JSON object directly
        raw = self._extract_json(response.text)
        content = raw['choices'][0]['message']['content']
        if not content:
            raise ValueError('Empty chat completion content')
        return OpenAIAnalysis.model_validate(self._extract_json(content))

    def _build_payload(self, signal: SignalState, chart_timeframe: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'symbol': signal.symbol,
            'action': signal.action,
            'confidence': signal.confidence,
            'buy_score': signal.buy_score,
            'sell_score': signal.sell_score,
            'price': signal.price,
            'support': signal.support,
            'resistance': signal.resistance,
            'invalidation': signal.invalidation,
            'timeframes': [
                {
                    'timeframe': score.timeframe,
                    'buy_score': score.buy_score,
                    'sell_score': score.sell_score,
                    'support': score.support,
                    'resistance': score.resistance,
                    'invalidation': score.invalidation,
                    'close': score.indicators.close,
                    'ema_50': score.indicators.ema_50,
                    'ema_200': score.indicators.ema_200,
                    'rsi_14': score.indicators.rsi_14,
                    'macd_histogram': score.indicators.macd_histogram,
                    'reasons': score.reasons[:4],
                }
                for score in signal.timeframe_scores
            ],
            'reasons': signal.reasons[:8],
        }
        if chart_timeframe:
            payload['chart_timeframe'] = chart_timeframe
        return payload

    def _chat_user_content(
        self,
        payload: dict[str, Any],
        chart_image: bytes | None = None,
    ) -> str | list[dict[str, Any]]:
        prompt = build_user_prompt(payload)
        if chart_image is None:
            return prompt
        return [
            {'type': 'text', 'text': prompt},
            {
                'type': 'image_url',
                'image_url': {
                    'url': f'data:image/png;base64,{base64.b64encode(chart_image).decode("ascii")}',
                },
            },
        ]

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """Extract JSON from raw model output, handling markdown code fences."""
        import re
        # Strip markdown code fences (```json ... ``` or ``` ... ```)
        fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if fenced:
            return json.loads(fenced.group(1))
        # Find outermost { ... } in case of surrounding text
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise ValueError(f'No JSON object found in response: {text[:200]}')

    @staticmethod
    def _normalize_base_url(base_url: str | None) -> str | None:
        if not base_url:
            return None
        if 'gateway.ai.cloudflare.com' in base_url:
            return base_url.rstrip('/')
        parsed = urlparse(base_url)
        path = parsed.path.rstrip('/')
        if path in ('', '/'):
            return base_url.rstrip('/') + '/v1'
        return base_url.rstrip('/')

    @staticmethod
    def _chat_completion_url(base_url: str) -> str:
        if base_url.endswith('/chat/completions'):
            return base_url
        return base_url.rstrip('/') + '/chat/completions'
