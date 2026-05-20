import base64
import os

from fastapi import UploadFile

from agromind.models import default_groq_model, detect_language_from_text, get_language, resolve_response_language
from agromind.prompts import build_system_prompt, build_user_prompt, fallback_response


class AIProviderError(RuntimeError):
    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


async def summarize_file(file: UploadFile | None) -> tuple[str | None, str | None, str | None]:
    if not file or not file.filename:
        return None, None, None
    content = await file.read()
    if not content:
        return None, None, None
    size_kb = round(len(content) / 1024)
    summary = f"Name: {file.filename}\nType: {file.content_type or 'unknown'}\nSize: {size_kb} KB"
    encoded = base64.b64encode(content).decode("utf-8")
    return summary, encoded, file.content_type


def gemini_model_candidates() -> list[str]:
    values = [
        os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite"),
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
    ]
    return list(dict.fromkeys(values))


REASONING_TERMS = {
    "analyze",
    "analysis",
    "calculate",
    "compare",
    "diagnose",
    "estimate",
    "evaluate",
    "explain why",
    "forecast",
    "infer",
    "optimize",
    "plan",
    "predict",
    "recommend",
    "risk",
    "solve",
    "strategy",
    "treatment",
    "yield",
}

REASONING_TOOLS = {
    "crop-recommendation",
    "plant-health-inspector",
    "symptom-checker",
    "skin-disease-analyzer",
    "medicine-suggestion",
    "health-report-analyzer",
    "essay-grader",
}


def infer_groq_task(tool_id: str, fields: dict[str, str], language_code: str, has_image: bool) -> str:
    if has_image:
        return "vision"
    if get_language(language_code)["code"] != "en-US":
        return "multilingual"
    if tool_id in REASONING_TOOLS:
        return "reasoning"

    prompt_text = " ".join(fields.values()).lower()
    if not prompt_text.strip():
        return "text"

    matched_terms = sum(1 for term in REASONING_TERMS if term in prompt_text)
    token_count = max(len(prompt_text.split()), 1)
    reasoning_score = matched_terms / token_count
    return "reasoning" if matched_terms >= 2 or reasoning_score >= 0.08 else "text"


async def generate_ai_response(
    domain_id: str,
    tool_id: str,
    fields: dict[str, str],
    file: UploadFile | None,
    language_code: str = "en-US",
    plan: str = "starter",
) -> tuple[str, str, str]:
    file_summary, image_base64, mime_type = await summarize_file(file)
    prompt_text = " ".join(fields.values())
    language = resolve_response_language(prompt_text, language_code)
    has_image = bool(image_base64 and mime_type and mime_type.startswith("image/"))
    task = infer_groq_task(tool_id, fields, language["code"], has_image)
    if not has_image and detect_language_from_text(prompt_text) and task == "text":
        task = "multilingual"

    system_prompt = build_system_prompt(domain_id, tool_id, language["name"])
    user_prompt = build_user_prompt(fields, file_summary)

    prefer_gemini = plan == "starter" and os.getenv("GEMINI_API_KEY")

    if os.getenv("GROQ_API_KEY") and not prefer_gemini:
        try:
            from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

            client = OpenAI(
                api_key=os.getenv("GROQ_API_KEY"),
                base_url="https://api.groq.com/openai/v1",
                timeout=45,
            )
            model = default_groq_model(task)
            content = user_prompt
            if image_base64 and mime_type and mime_type.startswith("image/"):
                model = default_groq_model("vision")
                content = [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}},
                ]
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
            )
            return completion.choices[0].message.content or "", f"groq:{model}", language["code"]
        except APITimeoutError as exc:
            raise AIProviderError("Groq API request timed out. Please try again.") from exc
        except APIConnectionError as exc:
            raise AIProviderError("Could not reach Groq servers. Check your connection.") from exc
        except APIStatusError as exc:
            status = getattr(exc, "status_code", "unknown")
            raise AIProviderError(f"Groq API returned an error ({status}). Check your credentials.") from exc
        except Exception as exc:
            raise AIProviderError("Groq request failed. Check your API key and model config.") from exc

    if os.getenv("OPENAI_API_KEY") and not prefer_gemini:
        try:
            from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI


            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=45)
            content = user_prompt
            if image_base64 and mime_type and mime_type.startswith("image/"):
                content = [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}},
                ]
            completion = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
            )
            return completion.choices[0].message.content or "", "openai", language["code"]
        except APITimeoutError as exc:
            raise AIProviderError("OpenAI timed out. Try again with a shorter prompt or smaller file.") from exc
        except APIConnectionError as exc:
            raise AIProviderError("Could not reach OpenAI. Check network access and provider status.") from exc
        except APIStatusError as exc:
            status = getattr(exc, "status_code", "unknown")
            raise AIProviderError(f"OpenAI returned an error ({status}). Check your API key, quota, and model name.") from exc
        except Exception as exc:
            raise AIProviderError("OpenAI request failed. Check your API key, quota, and model configuration.") from exc

    if os.getenv("GEMINI_API_KEY"):
        try:
            import google.generativeai as genai

            genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
            last_error = None
            for model_name in gemini_model_candidates():
                try:
                    model = genai.GenerativeModel(model_name)
                    if image_base64 and mime_type and mime_type.startswith("image/"):
                        payload = [
                            f"{system_prompt}\n\n{user_prompt}",
                            {"mime_type": mime_type, "data": base64.b64decode(image_base64)},
                        ]
                    else:
                        payload = f"{system_prompt}\n\n{user_prompt}"
                    result = model.generate_content(payload, request_options={"timeout": 45})
                    return result.text or "", f"gemini:{model_name}", language["code"]
                except Exception as error:
                    last_error = error
                    message = str(error).lower()
                    if "429" not in message and "quota" not in message and "not found" not in message:
                        raise
            raise AIProviderError(f"No configured Gemini model is available. Check GEMINI_MODEL and quota. Last error: {last_error}")
        except AIProviderError:
            raise
        except Exception as exc:
            raise AIProviderError("Gemini request failed. Check your API key, quota, and model configuration.") from exc

    return fallback_response(domain_id, tool_id, fields), "local", language["code"]
