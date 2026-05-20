from __future__ import annotations

import math
import os


PLAN_CONFIG = {
    "starter": {
        "name": "Starter",
        "price_inr": 0,
        "daily_requests": 1000,
        "monthly_tokens": 250_000,
        "monthly_credits": 0,
        "model_access": "Gemini Flash-Lite free tier",
        "description": "Free access for basic AI tools with Gemini-style free API limits.",
    },
    "pro": {
        "name": "Pro",
        "price_inr": 499,
        "daily_requests": 5000,
        "monthly_tokens": 2_000_000,
        "monthly_credits": 5000,
        "model_access": "Groq reasoning, vision, multilingual, and speech models",
        "description": "Higher limits for serious individual use.",
    },
    "team": {
        "name": "Team",
        "price_inr": 1499,
        "daily_requests": 20000,
        "monthly_tokens": 10_000_000,
        "monthly_credits": 20000,
        "model_access": "Groq premium routing with shared workspace capacity",
        "description": "Large shared workspace limits and admin use.",
    },
}


MODEL_PRICING_USD_PER_M = {
    "gemini:gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "groq:llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "groq:meta-llama/llama-4-scout-17b-16e-instruct": {"input": 0.11, "output": 0.34},
    "groq:openai/gpt-oss-120b": {"input": 0.15, "output": 0.60},
    "groq:openai/gpt-oss-20b": {"input": 0.10, "output": 0.50},
    "groq:qwen/qwen3-32b": {"input": 0.29, "output": 0.59},
}

USD_TO_INR = float(os.getenv("USD_TO_INR", "84"))


def get_plan(plan: str | None) -> dict:
    return PLAN_CONFIG.get((plan or "starter").lower(), PLAN_CONFIG["starter"])


def all_plans() -> list[dict]:
    return [{**details, "id": plan_id} for plan_id, details in PLAN_CONFIG.items()]


def estimate_text_tokens(text: str) -> int:
    return max(1, math.ceil(len(text or "") / 4))


def estimate_prompt_tokens(fields: dict, file_summary: str | None = None) -> int:
    prompt_text = " ".join(str(value) for value in fields.values())
    if file_summary:
        prompt_text = f"{prompt_text} {file_summary}"
    return estimate_text_tokens(prompt_text)


def estimate_cost(provider: str, input_tokens: int, output_tokens: int) -> dict:
    rates = MODEL_PRICING_USD_PER_M.get(provider)
    if not rates:
        return {"cost_cents": 0, "credits": max(1, math.ceil((input_tokens + output_tokens) / 1000))}

    usd = (input_tokens / 1_000_000 * rates["input"]) + (output_tokens / 1_000_000 * rates["output"])
    inr = usd * USD_TO_INR
    cost_cents = max(1, math.ceil(usd * 100)) if usd > 0 else 0
    credits = max(1, math.ceil(inr * 10))
    return {"cost_cents": cost_cents, "credits": credits}


def can_use_plan(plan: str | None, usage: dict) -> tuple[bool, str | None]:
    config = get_plan(plan)
    if usage.get("requests_today", 0) >= config["daily_requests"]:
        return False, "Daily request limit reached. Upgrade your plan to continue."
    if usage.get("tokens_this_month", 0) >= config["monthly_tokens"]:
        return False, "Monthly token limit reached. Upgrade your plan to continue."
    if config["monthly_credits"] and usage.get("credits_this_month", 0) >= config["monthly_credits"]:
        return False, "Monthly AI credits reached. Upgrade your plan to continue."
    return True, None
