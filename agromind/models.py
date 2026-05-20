import os
import re


LANGUAGES = [
    {"code": "en-US", "groq_code": "en", "name": "English"},
    {"code": "hi-IN", "groq_code": "hi", "name": "Hindi"},
    {"code": "es-ES", "groq_code": "es", "name": "Spanish"},
    {"code": "fr-FR", "groq_code": "fr", "name": "French"},
    {"code": "ar-SA", "groq_code": "ar", "name": "Arabic"},
    {"code": "pt-BR", "groq_code": "pt", "name": "Portuguese"},
    {"code": "de-DE", "groq_code": "de", "name": "German"},
    {"code": "it-IT", "groq_code": "it", "name": "Italian"},
    {"code": "ja-JP", "groq_code": "ja", "name": "Japanese"},
    {"code": "ko-KR", "groq_code": "ko", "name": "Korean"},
]

DEFAULT_LANGUAGE = "en-US"

GROQ_MODELS = {
    "reasoning": [
        {"id": "openai/gpt-oss-120b", "name": "GPT OSS 120B", "note": "Deep reasoning, planning, complex reports"},
        {"id": "openai/gpt-oss-20b", "name": "GPT OSS 20B", "note": "Fast reasoning and structured answers"},
        {"id": "qwen/qwen3-32b", "name": "Qwen3 32B", "note": "Reasoning preview model"},
    ],
    "text": [
        {"id": "openai/gpt-oss-120b", "name": "GPT OSS 120B", "note": "Highest quality text output"},
        {"id": "openai/gpt-oss-20b", "name": "GPT OSS 20B", "note": "Fast text output"},
        {"id": "meta-llama/llama-4-scout-17b-16e-instruct", "name": "Llama 4 Scout", "note": "Fast multimodal text model"},
        {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B", "note": "Strong multilingual assistant model"},
    ],
    "vision": [
        {"id": "meta-llama/llama-4-scout-17b-16e-instruct", "name": "Llama 4 Scout", "note": "Leaf, report, and uploaded image inspection"},
    ],
    "multilingual": [
        {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B", "note": "Preferred for 10-language conversations"},
        {"id": "openai/gpt-oss-120b", "name": "GPT OSS 120B", "note": "Reasoning in supported languages"},
        {"id": "openai/gpt-oss-20b", "name": "GPT OSS 20B", "note": "Fast multilingual responses"},
        {"id": "meta-llama/llama-4-scout-17b-16e-instruct", "name": "Llama 4 Scout", "note": "Multilingual image understanding"},
        {"id": "whisper-large-v3", "name": "Whisper Large v3", "note": "Speech recognition"},
    ],
    "speech_to_text": [
        {"id": "whisper-large-v3", "name": "Whisper Large v3", "note": "Accurate multilingual transcription"},
        {"id": "whisper-large-v3-turbo", "name": "Whisper Large v3 Turbo", "note": "Faster multilingual transcription"},
    ],
    "text_to_speech": [
        {"id": "canopylabs/orpheus-v1-english", "name": "Orpheus English", "note": "English voice output"},
        {"id": "canopylabs/orpheus-arabic-saudi", "name": "Orpheus Arabic Saudi", "note": "Arabic voice output"},
    ],
    "safety": [
        {"id": "openai/gpt-oss-safeguard-20b", "name": "Safety GPT OSS 20B", "note": "Content safety and moderation"},
    ],
}


def language_options() -> list[dict[str, str]]:
    return LANGUAGES


def get_language(code: str | None) -> dict[str, str]:
    return next((language for language in LANGUAGES if language["code"] == code), LANGUAGES[0])


def language_from_groq_code(code: str | None) -> dict[str, str] | None:
    return next((language for language in LANGUAGES if language["groq_code"] == code), None)


LANGUAGE_ALIASES = {
    "english": "en-US",
    "hindi": "hi-IN",
    "spanish": "es-ES",
    "french": "fr-FR",
    "arabic": "ar-SA",
    "portuguese": "pt-BR",
    "german": "de-DE",
    "italian": "it-IT",
    "japanese": "ja-JP",
    "korean": "ko-KR",
}


def requested_language_from_text(text: str) -> str | None:
    lowered = text.lower()
    patterns = [
        r"(?:reply|respond|answer|give response|write|translate).{0,32}\b(?:in|to)\s+([a-z]+)",
        r"\bin\s+([a-z]+)\s+(?:language|please)",
        r"(?:भाषा|में जवाब|उत्तर).{0,24}(hindi|english|spanish|french|arabic|portuguese|german|italian|japanese|korean)",
    ]
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match and match.group(1) in LANGUAGE_ALIASES:
            return LANGUAGE_ALIASES[match.group(1)]
    for name, code in LANGUAGE_ALIASES.items():
        if f"respond in {name}" in lowered or f"answer in {name}" in lowered or f"reply in {name}" in lowered:
            return code
    return None


def detect_language_from_text(text: str) -> str | None:
    if re.search(r"[\u0900-\u097F]", text):
        return "hi-IN"
    if re.search(r"[\u0600-\u06FF]", text):
        return "ar-SA"
    if re.search(r"[\u3040-\u30FF\u4E00-\u9FFF]", text):
        return "ja-JP"
    if re.search(r"[\uAC00-\uD7AF]", text):
        return "ko-KR"

    lowered = f" {text.lower()} "
    language_markers = {
        "es-ES": [" que ", " para ", " por favor ", " gracias ", " cultivo ", " salud "],
        "fr-FR": [" le ", " la ", " pour ", " merci ", " sante ", " reponse "],
        "pt-BR": [" voce ", " para ", " obrigado ", " saude ", " relatorio "],
        "de-DE": [" bitte ", " und ", " der ", " die ", " gesundheit ", " bericht "],
        "it-IT": [" per favore ", " grazie ", " salute ", " rapporto ", " coltura "],
    }
    scores = {code: sum(1 for marker in markers if marker in lowered) for code, markers in language_markers.items()}
    best_code, best_score = max(scores.items(), key=lambda item: item[1])
    return best_code if best_score >= 2 else None


def resolve_response_language(text: str, default_code: str | None = DEFAULT_LANGUAGE) -> dict[str, str]:
    requested = requested_language_from_text(text)
    if requested:
        return get_language(requested)
    detected = detect_language_from_text(text)
    if detected:
        return get_language(detected)
    return get_language(default_code)


def groq_tts_model_for_language(language_code: str) -> str | None:
    language = get_language(language_code)
    if language["groq_code"] == "ar":
        return "canopylabs/orpheus-arabic-saudi"
    if language["groq_code"] == "en":
        return default_groq_model("text_to_speech")
    return None


def groq_model_groups() -> dict[str, list[dict[str, str]]]:
    return GROQ_MODELS


def default_groq_model(task: str = "text") -> str:
    env_by_task = {
        "reasoning": "GROQ_REASONING_MODEL",
        "text": "GROQ_TEXT_MODEL",
        "vision": "GROQ_VISION_MODEL",
        "multilingual": "GROQ_MULTILINGUAL_MODEL",
        "speech_to_text": "GROQ_STT_MODEL",
        "text_to_speech": "GROQ_TTS_MODEL",
        "safety": "GROQ_SAFETY_MODEL",
    }
    configured = os.getenv(env_by_task.get(task, "GROQ_MODEL")) or os.getenv("GROQ_MODEL")
    if configured:
        return configured
    return GROQ_MODELS.get(task, GROQ_MODELS["text"])[0]["id"]


def normalize_task(task: str | None) -> str:
    return task if task in {"reasoning", "text", "multilingual"} else "text"
