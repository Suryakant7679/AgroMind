import base64
import os

from fastapi import UploadFile

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


async def generate_ai_response(domain_id: str, tool_id: str, fields: dict[str, str], file: UploadFile | None) -> tuple[str, str]:
    file_summary, image_base64, mime_type = await summarize_file(file)
    system_prompt = build_system_prompt(domain_id, tool_id)
    user_prompt = build_user_prompt(fields, file_summary)

    if os.getenv("OPENAI_API_KEY"):
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
            return completion.choices[0].message.content or "", "openai"
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
                    return result.text or "", f"gemini:{model_name}"
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

    return fallback_response(domain_id, tool_id, fields), "local"
