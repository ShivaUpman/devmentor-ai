"""
ml/llm/groq_client.py — Groq LLM API client

WHY Groq specifically?
  Speed: Groq's LPU (Language Processing Unit) hardware runs Llama 3.3 70B
  at ~800 tokens/second — 10-20x faster than GPU-based APIs.
  For a real-time interview platform, 200ms LLM responses feel instant.
  GPT-4 takes 2-8 seconds for equivalent quality. Groq wins for UX.

  Free tier: 14,400 requests/day, 6000 req/min on llama-3.3-70b-versatile.
  For a dev/demo platform, this is effectively unlimited.

  Model quality: llama-3.3-70b-versatile is competitive with GPT-4o-mini
  for structured tasks like classification and feedback generation.

WHY use structured JSON output?
  LLMs can hallucinate structure ("the answer is... actually let me reconsider...").
  Forcing JSON output with a strict system prompt + response_format={"type":"json_object"}
  guarantees machine-parseable output — no regex extraction needed.

  This is called "constrained decoding" — the model can only output valid JSON.
  Groq, OpenAI, and Anthropic all support this mode.

Interview question: "How do you reliably extract structured data from an LLM?"
  Options:
    1. response_format=json_object (if API supports it) — most reliable
    2. Few-shot prompting with JSON examples — good for complex schemas
    3. Output parsers with retry logic — fallback for APIs without JSON mode
    4. Function calling / tool use — best for action-oriented outputs
"""

import json
import os
import time
from typing import Optional

from groq import Groq, APIError, RateLimitError, APIConnectionError


class GroqClient:
    """
    Wrapper around the Groq SDK with:
      - Automatic retry with exponential backoff
      - Structured JSON output enforcement
      - Token usage tracking (for cost monitoring)
      - Graceful error handling

    WHY wrap the SDK instead of using it directly?
      1. Centralize retry logic — one place, not scattered across ML modules
      2. Abstract the API — swap Groq for OpenAI/Anthropic without touching callers
      3. Add observability — token counts, latency, error rates in one place
      4. Testability — mock this client, not the HTTP layer
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.model = model or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        self._client: Optional[Groq] = None
        self.total_tokens_used = 0   # Track usage for monitoring

    def _get_client(self) -> Groq:
        """Lazy-init Groq client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError(
                    "GROQ_API_KEY not set. "
                    "Get a free key at console.groq.com and add it to .env"
                )
            self._client = Groq(api_key=self.api_key)
        return self._client

    def is_available(self) -> bool:
        """Check if Groq is configured (key exists). Doesn't make a network call."""
        return bool(self.api_key and self.api_key != "gsk_your_key_here")

    def complete(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.1,     # Low temp = consistent, deterministic output
        max_tokens: int = 512,
        json_mode: bool = True,
        max_retries: int = 3,
    ) -> dict:
        """
        Call the Groq API and return parsed JSON.

        Args:
            system_prompt: Role and task instructions for the model
            user_message: The actual input to process
            temperature: 0.0=deterministic, 1.0=creative. Use 0.1 for classification.
            max_tokens: Cap output length. Classification needs ~100, feedback ~400.
            json_mode: Force JSON output (recommended for structured tasks)
            max_retries: Retry on rate limit / transient errors

        Returns:
            Parsed dict from the LLM JSON output

        Raises:
            GroqClientError: After max_retries exhausted, or API key invalid

        WHY temperature=0.1 for classification?
          Higher temperature = more randomness = different classifications for
          the same question on different runs. Classification must be deterministic.
          0.1 adds just enough variation to avoid degenerate repeated tokens.
          For creative tasks (feedback generation), 0.3-0.5 gives better variety.
        """
        client = self._get_client()
        last_error = None

        for attempt in range(max_retries):
            try:
                start = time.perf_counter()

                kwargs = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }

                if json_mode:
                    # Groq's JSON mode guarantees valid JSON output
                    # The model cannot output non-JSON in this mode
                    kwargs["response_format"] = {"type": "json_object"}

                response = client.chat.completions.create(**kwargs)

                elapsed_ms = (time.perf_counter() - start) * 1000

                # Track token usage for monitoring dashboards
                if response.usage:
                    self.total_tokens_used += response.usage.total_tokens

                content = response.choices[0].message.content

                # Parse JSON — should never fail with json_mode=True
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    # If JSON mode fails (shouldn't happen), try to extract JSON
                    import re
                    match = re.search(r'\{.*\}', content, re.DOTALL)
                    if match:
                        return json.loads(match.group())
                    raise GroqClientError(f"Could not parse LLM output as JSON: {content[:200]}")

            except RateLimitError:
                # Groq free tier: 6000 req/min. This shouldn't happen in dev.
                # WHY exponential backoff?
                #   Retrying immediately after a rate limit just generates more
                #   rate-limited requests. Exponential backoff (1s, 2s, 4s...)
                #   lets the rate limit window reset between attempts.
                wait = 2 ** attempt
                if attempt < max_retries - 1:
                    time.sleep(wait)
                    last_error = f"Rate limited — waited {wait}s"
                else:
                    raise GroqClientError("Groq rate limit exceeded after retries")

            except APIConnectionError as e:
                last_error = f"Connection error: {e}"
                if attempt < max_retries - 1:
                    time.sleep(1)
                else:
                    raise GroqClientError(f"Groq connection failed: {e}")

            except APIError as e:
                # 4xx client errors (bad API key, invalid request) — don't retry
                if e.status_code and 400 <= e.status_code < 500:
                    raise GroqClientError(f"Groq API client error {e.status_code}: {e.message}")
                last_error = f"API error {e.status_code}: {e.message}"
                if attempt < max_retries - 1:
                    time.sleep(1)

        raise GroqClientError(f"Groq request failed after {max_retries} retries. Last: {last_error}")


class GroqClientError(Exception):
    """Raised when Groq API call fails after all retries."""
    pass


# Module-level singleton
_groq_client: Optional[GroqClient] = None

def get_groq_client() -> GroqClient:
    global _groq_client
    if _groq_client is None:
        _groq_client = GroqClient()
    return _groq_client
