"""
AI Job Evaluator — uses Claude (with Groq fallback) to analyze job fit against a candidate profile.
"""
import json
import re

from src.llm_client import llm_chat

SYSTEM_PROMPT_EN = """You are a senior technical recruiter and career coach.
Evaluate how well a job offer matches a candidate's profile and return a structured JSON analysis.
Always respond with valid JSON only, no markdown fences."""

SYSTEM_PROMPT_ES = """Eres un reclutador senior y coach de carrera experto.
Evalúa qué tan bien una oferta de trabajo se ajusta al perfil del candidato y devuelve un análisis JSON estructurado.
IMPORTANTE: Los campos de texto libre (summary, skills_match skill names, skills_missing, strengths, concerns) deben estar en ESPAÑOL.
Responde SOLO con JSON válido, sin bloques de código markdown."""


def _build_prompt(profile: dict, job: dict) -> str:
    primary_language = profile.get("primary_language", "English")
    language_note = ""
    if primary_language == "Spanish":
        language_note = (
            "\nPREFERENCIA DE IDIOMA: El idioma principal de la candidata es español. "
            "Si la oferta está en inglés y/o requiere inglés avanzado/fluido explícitamente, "
            "reduce el match_score entre 15-25 puntos y establece requires_english=true. "
            "Las ofertas en español o que no requieran inglés deben tener mayor puntuación. "
            "Escribe el campo 'summary' y listas de texto en español.\n"
        )

    return f"""
Analyze this job offer against the candidate profile and return a JSON object with this exact structure:

{{
  "match_score": <integer 0-100>,
  "match_level": "<Excellent|Good|Moderate|Low>",
  "summary": "<2-3 sentences explaining the match>",
  "salary_info": "<extracted salary or 'Not specified'>",
  "is_remote": <true|false>,
  "requires_english": <true|false>,
  "english_level": "<required English level or 'Not specified'>",
  "skills_match": [
    {{"skill": "<skill name>", "has": <true|false>, "importance": "<required|nice-to-have>"}}
  ],
  "skills_missing": ["<skill1>", "<skill2>"],
  "strengths": ["<strength1>", "<strength2>"],
  "concerns": ["<concern1>"],
  "ats_keywords": ["<keyword1>", "<keyword2>"],
  "recommendation": "<Apply|Consider|Skip>"
}}
{language_note}
CANDIDATE PROFILE:
{json.dumps(profile, indent=2)}

JOB OFFER:
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Location: {job.get('location', '')}
Salary: {job.get('salary', 'Not specified')}
Source: {job.get('source', '')}

Description:
{job.get('raw_description', '')[:4000]}
""".strip()


async def evaluate_job(job: dict, profile: dict, primary_language: str = "English") -> dict:
    profile = {**profile, "primary_language": primary_language}
    system = SYSTEM_PROMPT_ES if primary_language == "Spanish" else SYSTEM_PROMPT_EN

    raw = await llm_chat(
        system=system,
        user=_build_prompt(profile, job),
        max_tokens=1500,
        mode="eval",
    )
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    evaluation = json.loads(raw)

    return {
        **job,
        "match_score": evaluation.get("match_score", 0),
        "match_summary": evaluation.get("summary", ""),
        "match_level": evaluation.get("match_level", ""),
        "salary_info": evaluation.get("salary_info", job.get("salary", "Not specified")),
        "is_remote": evaluation.get("is_remote", job.get("is_remote", False)),
        "requires_english": evaluation.get("requires_english", True),
        "english_level": evaluation.get("english_level", "Not specified"),
        "skills_match": evaluation.get("skills_match", []),
        "skills_missing": evaluation.get("skills_missing", []),
        "strengths": evaluation.get("strengths", []),
        "concerns": evaluation.get("concerns", []),
        "ats_keywords": evaluation.get("ats_keywords", []),
        "recommendation": evaluation.get("recommendation", "Consider"),
    }
