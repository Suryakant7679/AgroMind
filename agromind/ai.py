import base64
import os
import re
import httpx

from fastapi import UploadFile

from agromind.models import default_groq_model, detect_language_from_text, get_language, resolve_response_language
from agromind.prompts import build_system_prompt, build_user_prompt, fallback_response


async def fetch_environmental_context(location_str: str) -> str:
    if not location_str or not location_str.strip():
        return ""
    
    lat, lon = None, None
    resolved_address = None
    
    # Check if input is already lat, lon
    try:
        parts = location_str.split(",")
        if len(parts) == 2:
            lat_val = float(parts[0].strip())
            lon_val = float(parts[1].strip())
            if -90 <= lat_val <= 90 and -180 <= lon_val <= 180:
                lat, lon = lat_val, lon_val
    except Exception:
        pass

    # OpenStreetMap Nominatim Geocoding
    if lat is None or lon is None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {"User-Agent": "AgroMind/1.0 (contact@agromind.ai)"}
                resp = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": location_str, "format": "json", "limit": 1},
                    headers=headers
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data:
                        lat = float(data[0]["lat"])
                        lon = float(data[0]["lon"])
                        resolved_address = data[0].get("display_name")
        except Exception as e:
            print(f"Nominatim error: {e}")

    if lat is None or lon is None:
        return ""

    weather_data = {}
    soil_data = {}
    nasa_data = {}

    # Open-Meteo API
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,showers_sum,snowfall_sum",
                    "current_weather": "true",
                    "timezone": "auto"
                }
            )
            if resp.status_code == 200:
                weather_data = resp.json()
    except Exception as e:
        print(f"Open-Meteo error: {e}")

    # SoilGrids API
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://rest.isric.org/soilgrids/v2.0/properties/query",
                params={
                    "lon": lon,
                    "lat": lat,
                    "property": ["phh2o", "nitrogen", "soc"],
                    "depth": "0-5cm",
                    "value": "mean"
                }
            )
            if resp.status_code == 200:
                raw_soil = resp.json()
                properties = raw_soil.get("properties", {})
                layers = properties.get("layers", [])
                for layer in layers:
                    name = layer.get("name")
                    depths = layer.get("depths", [])
                    if depths:
                        values = depths[0].get("values", {})
                        mean_val = values.get("mean")
                        if mean_val is not None:
                            if name == "phh2o":
                                soil_data["pH"] = mean_val / 10.0
                            elif name == "nitrogen":
                                soil_data["nitrogen"] = mean_val
                            elif name == "soc":
                                soil_data["organic_carbon"] = mean_val / 10.0
    except Exception as e:
        print(f"SoilGrids error: {e}")

    # NASA POWER API
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://power.larc.nasa.gov/api/temporal/daily/point",
                params={
                    "parameters": "ALLSKY_SNDN,T2M,RH2M",
                    "community": "AG",
                    "longitude": lon,
                    "latitude": lat,
                    "start": "20260510",
                    "end": "20260520",
                    "format": "JSON"
                }
            )
            if resp.status_code == 200:
                nasa_data = resp.json()
    except Exception as e:
        print(f"NASA POWER error: {e}")

    # Compile a beautiful context summary
    lines = []
    lines.append(f"Latitude: {lat}, Longitude: {lon}")
    if resolved_address:
        lines.append(f"Resolved Address: {resolved_address}")
    
    if weather_data:
        curr = weather_data.get("current_weather", {})
        if curr:
            lines.append(f"Current Live Weather: Temp={curr.get('temperature')}C, WindSpeed={curr.get('windspeed')} km/h, Code={curr.get('weathercode')}")
        daily = weather_data.get("daily", {})
        if daily:
            lines.append("7-Day Forecast:")
            dates = daily.get("time", [])
            t_max = daily.get("temperature_2m_max", [])
            t_min = daily.get("temperature_2m_min", [])
            prec = daily.get("precipitation_sum", [])
            for i in range(min(len(dates), 7)):
                lines.append(f"  - {dates[i]}: Max={t_max[i]}C, Min={t_min[i]}C, Rain={prec[i]}mm")
                
    if soil_data:
        lines.append("Soil Analytics:")
        if "pH" in soil_data:
            lines.append(f"  - Soil pH: {soil_data['pH']} (Target: 6.0-7.5)")
        if "nitrogen" in soil_data:
            lines.append(f"  - Nitrogen Content: {soil_data['nitrogen']} mg/kg")
        if "organic_carbon" in soil_data:
            lines.append(f"  - Soil Organic Carbon: {soil_data['organic_carbon']} g/kg")

    if nasa_data:
        properties = nasa_data.get("properties", {})
        parameter = properties.get("parameter", {})
        sol = parameter.get("ALLSKY_SNDN", {})
        if sol:
            avg_sol = sum(sol.values()) / max(len(sol), 1)
            lines.append(f"10-Day Avg Solar Radiation: {avg_sol:.2f} W/m2")

    return "\n".join(lines)


class AIProviderError(RuntimeError):
    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


PDF_TEXT_MAX_CHARS = 18000
PDF_TEXT_MAX_PAGES = 25


def extract_pdf_text(content: bytes, max_chars: int = PDF_TEXT_MAX_CHARS, max_pages: int = PDF_TEXT_MAX_PAGES) -> str:
    if not content:
        return ""

    try:
        import fitz
    except Exception as exc:
        raise AIProviderError("PDF reading is not available. Install PyMuPDF to analyze uploaded PDFs.") from exc

    text_parts = []
    with fitz.open(stream=content, filetype="pdf") as document:
        for page_index, page in enumerate(document):
            if page_index >= max_pages:
                break
            page_text = page.get_text("text").strip()
            if page_text:
                text_parts.append(f"--- Page {page_index + 1} ---\n{page_text}")
            if sum(len(part) for part in text_parts) >= max_chars:
                break

    text = "\n\n".join(text_parts).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0].strip()
    return text


async def summarize_file(file: UploadFile | None) -> tuple[str | None, str | None, str | None]:
    if not file or not file.filename:
        return None, None, None
    content = await file.read()
    await file.seek(0)  # Reset pointer as a best practice
    if not content:
        return None, None, None
    size_kb = round(len(content) / 1024)
    summary = f"Name: {file.filename}\nType: {file.content_type or 'unknown'}\nSize: {size_kb} KB"
    is_pdf = (file.content_type or "").lower() == "application/pdf" or file.filename.lower().endswith(".pdf")
    if is_pdf:
        extracted_text = extract_pdf_text(content)
        if extracted_text:
            summary = (
                f"{summary}\n\n"
                "Extracted PDF text for analysis:\n"
                f"{extracted_text}"
            )
        else:
            summary = (
                f"{summary}\n\n"
                "No selectable text could be extracted from this PDF. It may be a scanned/image-only document. "
                "Ask the user for clear page images or enable OCR support before making document-specific claims."
            )
    encoded = base64.b64encode(content).decode("utf-8")
    return summary, encoded, file.content_type


def gemini_model_candidates() -> list[str]:
    values = [
        os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite"),
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-flash-latest",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
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


def extract_youtube_video_id(url: str) -> str | None:
    if not url:
        return None
    url = url.strip()
    
    # 1. Parse standard watch?v=ID or other query params like &v=ID
    query_match = re.search(r'(?:[?&]v=)([a-zA-Z0-9_-]{11})', url)
    if query_match:
        return query_match.group(1)
        
    # 2. Parse paths like /embed/ID, /v/ID, /shorts/ID, /live/ID
    path_match = re.search(r'(?:embed|v|shorts|live)\/([a-zA-Z0-9_-]{11})', url)
    if path_match:
        return path_match.group(1)
        
    # 3. Parse youtu.be/ID
    short_match = re.search(r'youtu\.be\/([a-zA-Z0-9_-]{11})', url)
    if short_match:
        return short_match.group(1)
        
    # 4. General fallback: if it's already just the 11-character ID
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url):
        return url
        
    # 5. Last resort fallback (avoiding 'watch', 'shorts', etc.)
    last_resort = re.search(r'\/([a-zA-Z0-9_-]{11})(?:[?&]|$)', url)
    if last_resort:
        candidate = last_resort.group(1)
        if candidate.lower() not in {"watch", "embed", "shorts", "live"}:
            return candidate
            
    return None


YOUTUBE_TRANSCRIPT_LANGUAGES = ["en", "en-US", "en-GB", "hi", "es"]
YOUTUBE_TRANSCRIPT_MAX_CHARS = 18000


def transcript_to_text(transcript) -> str:
    text_snippets = []
    for item in transcript:
        if hasattr(item, "text"):
            text_snippets.append(item.text)
        elif isinstance(item, dict):
            text_snippets.append(item.get("text", ""))
        else:
            try:
                text_snippets.append(item["text"])
            except Exception:
                text_snippets.append(str(item))
    return " ".join(snippet.strip() for snippet in text_snippets if snippet and snippet.strip())


def fetch_first_available_transcript(transcript_list):
    for finder_name in ("find_transcript", "find_generated_transcript", "find_manually_created_transcript"):
        finder = getattr(transcript_list, finder_name, None)
        if not finder:
            continue
        try:
            return finder(YOUTUBE_TRANSCRIPT_LANGUAGES).fetch()
        except Exception as exc:
            print(f"YouTube transcript {finder_name} fallback failed: {exc}")

    for transcript in transcript_list:
        try:
            return transcript.fetch()
        except Exception as exc:
            print(f"YouTube transcript iteration fallback failed: {exc}")
    return None


def fetch_youtube_transcript_text(video_id: str) -> str | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        # Newer versions of youtube-transcript-api require instantiation.
        if hasattr(YouTubeTranscriptApi, "get_transcript"):
            api_instance = YouTubeTranscriptApi
        else:
            api_instance = YouTubeTranscriptApi()

        try:
            if hasattr(api_instance, "get_transcript"):
                transcript = api_instance.get_transcript(video_id, languages=YOUTUBE_TRANSCRIPT_LANGUAGES)
            else:
                transcript = api_instance.fetch(video_id, languages=YOUTUBE_TRANSCRIPT_LANGUAGES)
        except Exception as fetch_exc:
            print(f"First-stage transcript fetch failed: {fetch_exc}. Trying fallback...")
            if hasattr(api_instance, "list_transcripts"):
                transcript_list = api_instance.list_transcripts(video_id)
            else:
                transcript_list = api_instance.list(video_id)

            transcript = fetch_first_available_transcript(transcript_list)

        if not transcript:
            return None
        return transcript_to_text(transcript)
    except Exception as e:
        print(f"Error getting youtube transcript: {e}")
        return None


def truncate_youtube_transcript(transcript: str) -> tuple[str, bool]:
    if len(transcript) <= YOUTUBE_TRANSCRIPT_MAX_CHARS:
        return transcript, False
    return transcript[:YOUTUBE_TRANSCRIPT_MAX_CHARS].rsplit(" ", 1)[0], True


def fetch_youtube_video_title(url: str) -> str | None:
    try:
        response = httpx.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            timeout=10.0,
            follow_redirects=True,
        )
        if response.status_code >= 400:
            return None
        title = response.json().get("title")
        return title.strip() if isinstance(title, str) and title.strip() else None
    except Exception as exc:
        print(f"Error getting youtube video title: {exc}")
        return None


async def generate_ai_response(
    domain_id: str,
    tool_id: str,
    fields: dict[str, str],
    file: UploadFile | None,
    language_code: str = "en-US",
    plan: str = "starter",
) -> tuple[str, str, str]:
    fields_copy = fields.copy()
    if tool_id in {"agriculture-tools", "smart-farming-assistant"}:
        loc_str = fields.get("location", "")
        if not loc_str:
            # Fallback to state or market district if location not provided
            loc_str = fields.get("state", "") or fields.get("marketDistrict", "")
        if loc_str:
            env_ctx = await fetch_environmental_context(loc_str)
            if env_ctx:
                fields_copy["live_environmental_telemetry"] = env_ctx

    if tool_id == "youtube-learning-tool":
        url = fields.get("url", "").strip()
        if not url:
            raise AIProviderError("Please enter a valid YouTube URL to generate notes.")
        
        video_id = extract_youtube_video_id(url)
        if not video_id:
            raise AIProviderError("Invalid YouTube URL. Please verify the link format (e.g., https://www.youtube.com/watch?v=...).")
        
        transcript = fetch_youtube_transcript_text(video_id)
        if transcript:
            transcript, was_truncated = truncate_youtube_transcript(transcript)
            fields_copy["video_transcript"] = transcript
            if was_truncated:
                fields_copy["transcript_note"] = (
                    "The transcript was very long, so only the first section was used. "
                    "Create useful material from the available transcript and mention that later sections may be missing."
                )
        else:
            title = fetch_youtube_video_title(url)
            fields_copy["transcript_note"] = (
                "The YouTube transcript could not be retrieved by the server. "
                "Generate helpful study material from the available video title, URL, and study goal. "
                "Clearly state that transcript-based details may be incomplete."
            )
            if title:
                fields_copy["video_title"] = title

    file_summary, image_base64, mime_type = await summarize_file(file)
    prompt_text = " ".join(fields_copy.values())
    language = resolve_response_language(prompt_text, language_code)
    has_image = bool(image_base64 and mime_type and mime_type.startswith("image/"))
    task = infer_groq_task(tool_id, fields_copy, language["code"], has_image)
    if not has_image and detect_language_from_text(prompt_text) and task == "text":
        task = "multilingual"

    system_prompt = build_system_prompt(domain_id, tool_id, language["name"])
    user_prompt = build_user_prompt(fields_copy, file_summary)

    prefer_gemini = plan == "starter" and os.getenv("GEMINI_API_KEY")

    if os.getenv("GROQ_API_KEY") and not prefer_gemini:
        try:
            from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

            client = OpenAI(
                api_key=os.getenv("GROQ_API_KEY"),
                base_url="https://api.groq.com/openai/v1",
                timeout=45,
            )
            # Dynamic Model Selection based on user prompt/question complexity
            is_simple_query = len(prompt_text.split()) < 15 and not any(term in prompt_text.lower() for term in REASONING_TERMS)
            if is_simple_query and task == "text":
                model = "llama-3.1-8b-instant"  # Ultra-fast and efficient for simple/short queries
            else:
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

    return fallback_response(domain_id, tool_id, fields_copy), "local", language["code"]
