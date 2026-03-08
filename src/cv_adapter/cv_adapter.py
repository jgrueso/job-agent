"""
CV Adapter — uses Claude to tailor the candidate's CV to a specific job offer.
Output is ATS-optimized plain text, concise (max 2 pages).
"""
import json

from src.llm_client import llm_chat

SYSTEM_PROMPT_EN = """You are an expert resume writer and ATS optimization specialist.
Your task is to adapt a candidate's CV to a specific job offer, maximizing ATS scores while keeping all content 100% truthful.

STRICT RULES:
- NEVER fabricate experience, skills, or achievements
- Mirror the exact keywords and phrases from the job description naturally throughout the text
- Lead with the most relevant experience for this role
- Quantify ALL achievements with numbers, percentages or business impact
- LENGTH: Fill 1.5 to 2 full pages. Do NOT leave the CV short — use all relevant content.
- Up to 5 bullet points per job position. Be thorough, not minimal.
- Professional summary: 4-5 sentences, packed with role-specific keywords.
- Skills section: comma-separated list per category. Include ALL relevant skills from profile.
- Add an ACHIEVEMENTS or KEY PROJECTS section if space allows, highlighting 2-3 notable wins.
- ONE blank line between job positions.
- ONE blank line between sections.
- NO blank lines between bullet points within the same job.
- Use clean ATS-safe formatting: no tables, no columns, no graphics.
- Avoid special characters that break ATS parsers (no *, #, |, ►, →, etc.).
- Section headers in UPPERCASE.
- Bullet points with a dash and space: "- " only.
- Output plain text only. No markdown. No bold markers like ** or __.
- Start directly with the candidate name, no preamble."""

SYSTEM_PROMPT_ES = """Eres un experto en redacción de hojas de vida y optimización ATS.
Tu tarea es adaptar la hoja de vida del candidato a una oferta de trabajo específica, maximizando el puntaje ATS manteniendo todo el contenido 100% verídico.
ESCRIBE TODA LA HOJA DE VIDA EN ESPAÑOL.

REGLAS ESTRICTAS:
- NUNCA inventes experiencia, habilidades o logros
- Usa las palabras clave exactas de la descripción del cargo de forma natural en el texto
- Resalta primero la experiencia más relevante para este cargo
- Cuantifica TODOS los logros con números, porcentajes o impacto de negocio
- EXTENSIÓN: Llena 1.5 a 2 páginas completas. No dejes la hoja de vida corta — usa todo el contenido relevante.
- Hasta 5 viñetas por posición laboral. Sé exhaustivo, no minimalista.
- Perfil profesional: 4-5 oraciones, rico en palabras clave del cargo.
- Sección de habilidades: lista separada por comas por categoría. Incluye TODAS las habilidades relevantes del perfil.
- Agrega una sección de PROYECTOS CLAVE o LOGROS si el espacio lo permite, destacando 2-3 éxitos notables.
- UNA línea en blanco entre posiciones laborales.
- UNA línea en blanco entre secciones.
- SIN líneas en blanco entre viñetas dentro del mismo cargo.
- Formato limpio compatible con ATS: sin tablas, sin columnas, sin gráficos.
- Evita caracteres especiales que dañen los parsers ATS (no *, #, |, ►, →, etc.).
- Encabezados de sección en MAYÚSCULAS.
- Viñetas con guión y espacio: "- " únicamente.
- Solo texto plano. Sin markdown. Sin marcadores en negrita como ** o __.
- Comienza directamente con el nombre del candidato, sin preámbulo."""


def _build_prompt(profile: dict, job: dict, lang: str = "en") -> str:
    ats_keywords = job.get("ats_keywords", [])
    strengths = job.get("strengths", [])

    if lang == "es":
        return f"""
Crea una hoja de vida ATS-optimizada (MAX 2 PÁGINAS) para este candidato adaptada a la oferta de trabajo.

PALABRAS CLAVE ATS A INCLUIR NATURALMENTE:
{', '.join(ats_keywords) if ats_keywords else 'Extrae de la descripción del cargo'}

FORTALEZAS DEL CANDIDATO PARA ESTE ROL:
{chr(10).join(f'- {s}' for s in strengths)}

PERFIL DEL CANDIDATO:
{json.dumps(profile, indent=2)}

OFERTA DE TRABAJO:
Cargo: {job.get('title', '')}
Empresa: {job.get('company', '')}
Descripción:
{job.get('raw_description', '')[:3000]}

---
Genera la hoja de vida completa adaptada. Objetivo: 1.5 a 2 páginas completas.
Usa exactamente esta estructura:

[Nombre Completo]
[Correo] | [Teléfono] | [LinkedIn] | [Ciudad]

PERFIL PROFESIONAL
[4-5 oraciones con palabras clave del cargo]

HABILIDADES TÉCNICAS
[Categoría]: [habilidad1, habilidad2, habilidad3]

EXPERIENCIA LABORAL
[Cargo] | [Empresa] | [Periodo]
- [Logro 1 con impacto cuantificado]
- [Logro 2 con impacto cuantificado]
- [Logro 3]
- [Logro 4 si es relevante]
- [Logro 5 si es relevante]

PROYECTOS CLAVE (si el espacio lo permite)
[Nombre del proyecto]: [descripción en 1 línea con impacto]

EDUCACIÓN
[Título] | [Institución] | [Año]

CERTIFICACIONES (si aplica)
[Nombre cert] | [Entidad] | [Año]
""".strip()

    return f"""
Create a concise ATS-optimized CV (MAX 2 PAGES) for this candidate tailored to the job offer.

ATS KEYWORDS TO INCLUDE NATURALLY:
{', '.join(ats_keywords) if ats_keywords else 'Extract from job description'}

CANDIDATE STRENGTHS FOR THIS ROLE:
{chr(10).join(f'- {s}' for s in strengths)}

CANDIDATE PROFILE:
{json.dumps(profile, indent=2)}

JOB OFFER:
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Description:
{job.get('raw_description', '')[:3000]}

---
Output the complete adapted CV. Target 1.5 to 2 full pages.
Use this exact structure:

[Full Name]
[Email] | [Phone] | [LinkedIn] | [Location]

PROFESSIONAL SUMMARY
[4-5 sentences, keyword-rich, targeted to this exact role]

TECHNICAL SKILLS
[Category]: [skill1, skill2, skill3, skill4, skill5]
[Category]: [skill1, skill2, skill3]

WORK EXPERIENCE
[Job Title] | [Company] | [Period]
- [Achievement 1 with quantified impact]
- [Achievement 2 with quantified impact]
- [Achievement 3 with quantified impact]
- [Achievement 4 if relevant]
- [Achievement 5 if relevant]

KEY PROJECTS (if space allows)
[Project Name]: [1 line description with business impact]

EDUCATION
[Degree] | [Institution] | [Year]

CERTIFICATIONS (if applicable)
[Cert name] | [Issuer] | [Year]
""".strip()


async def adapt_cv(job: dict, profile: dict, primary_language: str = "English") -> str:
    lang = "es" if primary_language == "Spanish" else "en"
    system_prompt = SYSTEM_PROMPT_ES if lang == "es" else SYSTEM_PROMPT_EN

    return await llm_chat(
        system=system_prompt,
        user=_build_prompt(profile, job, lang=lang),
        max_tokens=4000,
        mode="cv",
    )
