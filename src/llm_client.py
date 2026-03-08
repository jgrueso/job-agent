"""
LLM Client with Anthropic → Groq fallback.
Tries Anthropic first; if credits are exhausted, falls back to Groq (free tier).
"""
import os
import logging

import anthropic
from groq import AsyncGroq

logger = logging.getLogger(__name__)

GROQ_MODEL_PRIMARY = "llama-3.3-70b-versatile"
GROQ_MODEL_FALLBACK = "llama-3.1-8b-instant"  # 10x fewer tokens, for when daily limit is hit
ANTHROPIC_EVAL_MODEL = "claude-haiku-4-5-20251001"
ANTHROPIC_CV_MODEL = "claude-sonnet-4-6"

_CREDIT_ERRORS = {"credit balance is too low", "insufficient_quota", "billing"}


def _is_credit_error(e: Exception) -> bool:
    return any(msg in str(e).lower() for msg in _CREDIT_ERRORS)


async def llm_chat(
    system: str,
    user: str,
    max_tokens: int = 1500,
    mode: str = "eval",  # "eval" uses Haiku, "cv" uses Sonnet
) -> str:
    """
    Send a chat completion request.
    Tries Anthropic first, falls back to Groq on credit errors.
    """
    anthropic_model = ANTHROPIC_CV_MODEL if mode == "cv" else ANTHROPIC_EVAL_MODEL

    # --- Try Anthropic ---
    try:
        client = anthropic.AsyncAnthropic()
        message = await client.messages.create(
            model=anthropic_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        logger.debug(f"[LLM] Anthropic ({anthropic_model}) OK")
        return message.content[0].text.strip()

    except Exception as e:
        if _is_credit_error(e):
            logger.warning(f"[LLM] Anthropic credits exhausted — falling back to Groq")
        else:
            logger.error(f"[LLM] Anthropic error: {e} — falling back to Groq")

    # --- Fallback: Groq ---
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        raise RuntimeError(
            "Anthropic credits exhausted and GROQ_API_KEY is not set. "
            "Get a free key at https://console.groq.com"
        )

    client = AsyncGroq(api_key=groq_key)

    for groq_model in [GROQ_MODEL_PRIMARY, GROQ_MODEL_FALLBACK]:
        try:
            response = await client.chat.completions.create(
                model=groq_model,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
            )
            logger.info(f"[LLM] Groq ({groq_model}) OK")
            return response.choices[0].message.content.strip()
        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e):
                logger.warning(f"[LLM] Groq {groq_model} rate limited — trying fallback model")
                continue
            raise

    raise RuntimeError("All Groq models rate limited. Try again later or recharge Anthropic credits.")
