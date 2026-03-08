"""
Cover Letter Generator — genera carta de presentación personalizada por oferta.
En español para perfiles con primary_language=Spanish.
"""
from src.llm_client import llm_chat

SYSTEM_ES = """Eres un experto en redacción de cartas de presentación profesionales para el mercado laboral latinoamericano.
Genera cartas de presentación concisas, personales y convincentes en español.
REGLAS:
- Máximo 3 párrafos (250-300 palabras total)
- Tono profesional pero cercano, no robótico
- Primer párrafo: por qué me interesa ESTE cargo en ESTA empresa
- Segundo párrafo: 2-3 logros concretos cuantificados más relevantes para el cargo
- Tercer párrafo: cierre con call to action claro
- NO uses frases genéricas como "soy una persona proactiva y dinámica"
- Menciona la empresa por nombre al menos 2 veces
- Output solo el texto de la carta, sin asunto ni firma"""

SYSTEM_EN = """You are an expert cover letter writer.
Generate concise, personal and convincing cover letters.
RULES:
- Maximum 3 paragraphs (250-300 words total)
- Professional but human tone, not robotic
- First paragraph: why THIS role at THIS company specifically
- Second paragraph: 2-3 concrete quantified achievements most relevant to the role
- Third paragraph: clear call to action closing
- NO generic phrases like "I am a proactive team player"
- Mention the company by name at least twice
- Output only the letter body, no subject or signature"""


def _build_prompt(profile: dict, job: dict, lang: str) -> str:
    personal = profile.get("personal", {})
    name = personal.get("name", "")
    experience = profile.get("experience", [])
    top_exp = experience[:3] if experience else []

    if lang == "es":
        return f"""Escribe una carta de presentación para esta candidata y esta oferta.

CANDIDATA: {name}
EXPERIENCIA DESTACADA:
{chr(10).join(f'- {e["title"]} en {e["company"]} ({e["period"]}): {"; ".join(e.get("highlights", [])[:2])}' for e in top_exp)}

OFERTA:
Cargo: {job.get("title", "")}
Empresa: {job.get("company", "")}
Descripción: {job.get("raw_description", "")[:1500]}

Genera la carta de presentación en español."""
    else:
        return f"""Write a cover letter for this candidate and job offer.

CANDIDATE: {name}
TOP EXPERIENCE:
{chr(10).join(f'- {e["title"]} at {e["company"]} ({e["period"]}): {"; ".join(e.get("highlights", [])[:2])}' for e in top_exp)}

JOB OFFER:
Title: {job.get("title", "")}
Company: {job.get("company", "")}
Description: {job.get("raw_description", "")[:1500]}

Generate the cover letter."""


async def generate_cover_letter(job: dict, profile: dict, primary_language: str = "English") -> str:
    lang = "es" if primary_language == "Spanish" else "en"
    return await llm_chat(
        system=SYSTEM_ES if lang == "es" else SYSTEM_EN,
        user=_build_prompt(profile, job, lang),
        max_tokens=800,
        mode="eval",
    )
