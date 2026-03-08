"""
Interview Prep — genera preguntas de entrevista probables para una oferta específica.
"""
from src.llm_client import llm_chat

SYSTEM_ES = """Eres un coach de entrevistas de trabajo experto en el mercado tecnológico latinoamericano.
Genera preguntas de entrevista realistas y específicas para el cargo y empresa dados.
Incluye preguntas técnicas, de comportamiento (STAR) y situacionales.
Sé conciso: solo las preguntas y una pista corta de respuesta para cada una."""

SYSTEM_EN = """You are an expert interview coach for the tech industry.
Generate realistic and specific interview questions for the given role and company.
Include technical, behavioral (STAR), and situational questions.
Be concise: only the questions and a short answer hint for each."""


def _build_prompt(profile: dict, job: dict, lang: str) -> str:
    experience = profile.get("experience", [])
    top_roles = [f"{e['title']} en {e['company']}" for e in experience[:3]]
    skills_missing = job.get("skills_missing", [])

    if lang == "es":
        return f"""Cargo: {job.get('title')}
Empresa: {job.get('company')}
Descripción: {job.get('raw_description', '')[:1000]}

Experiencia de la candidata: {', '.join(top_roles)}
Gaps identificados: {', '.join(skills_missing) if skills_missing else 'Ninguno crítico'}

Genera 7 preguntas de entrevista probables con una pista de respuesta corta para cada una.
Formato:
1. [Pregunta]
   → Pista: [cómo responderla en 1 línea]"""
    else:
        return f"""Role: {job.get('title')}
Company: {job.get('company')}
Description: {job.get('raw_description', '')[:1000]}

Candidate experience: {', '.join(top_roles)}
Identified gaps: {', '.join(skills_missing) if skills_missing else 'None critical'}

Generate 7 likely interview questions with a short answer hint for each.
Format:
1. [Question]
   → Hint: [how to answer in 1 line]"""


async def generate_interview_questions(job: dict, profile: dict, primary_language: str = "English") -> str:
    lang = "es" if primary_language == "Spanish" else "en"
    return await llm_chat(
        system=SYSTEM_ES if lang == "es" else SYSTEM_EN,
        user=_build_prompt(profile, job, lang),
        max_tokens=1000,
        mode="eval",
    )
