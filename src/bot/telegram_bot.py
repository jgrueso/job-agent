"""
Telegram Bot — multi-profile job notifications with manual approval flow.
Supports multiple users/profiles via chat_id routing.
"""
import os
import json
import asyncio
import logging
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile, WebAppInfo
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    TypeHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

from src.database.db import get_job, update_job_status, get_pending_jobs, get_approved_jobs
from src.cv_adapter.cv_adapter import adapt_cv
from src.cv_adapter.cv_renderer import render_to_pdf
from src.cv_adapter.cover_letter import generate_cover_letter
from src.cv_adapter.interview_prep import generate_interview_questions

logger = logging.getLogger(__name__)

PROFILES_DIR = Path(__file__).parent.parent / "profile"


def _load_profiles() -> dict:
    """Returns {chat_id: config} mapping."""
    mapping = {}
    for config_path in PROFILES_DIR.glob("*/config.json"):
        config = json.loads(config_path.read_text())
        chat_id = config.get("telegram_chat_id")
        if chat_id:
            profile_path = config_path.parent / "profile.json"
            profile = json.loads(profile_path.read_text()) if profile_path.exists() else {}
            mapping[int(chat_id)] = {**config, "profile_data": profile}
    return mapping


def _get_profile_by_chat(chat_id: int) -> dict | None:
    profiles = _load_profiles()
    return profiles.get(chat_id)


def _match_bar(score: int) -> str:
    filled = round(score / 10)
    return "🟩" * filled + "⬜" * (10 - filled)


def build_job_message(job: dict) -> tuple[str, InlineKeyboardMarkup]:
    skills_match = job.get("skills_match", [])
    skills_text = ""
    for s in skills_match[:8]:
        icon = "✅" if s.get("has") else ("⚠️" if s.get("importance") == "nice-to-have" else "❌")
        skills_text += f"  {icon} {s['skill']}\n"
    if not skills_text:
        skills_text = "  (ver oferta)\n"

    missing = job.get("skills_missing", [])
    missing_text = f"\n❗ *Gaps:* {', '.join(missing[:4])}" if missing else ""

    remote_icon = "🌍 Remoto" if job.get("is_remote") else "🏢 Presencial"
    english_icon = "🗣️ Inglés req." if job.get("requires_english") else "🗣️ Sin inglés"
    rec = job.get("recommendation", "Consider")
    rec_icon = {"Apply": "🚀", "Consider": "🤔", "Skip": "🛑"}.get(rec, "🤔")

    text = (
        f"📬 *Nueva oferta*\n\n"
        f"🏢 *Empresa:* {job['company']}\n"
        f"💼 *Cargo:* {job['title']}\n"
        f"💰 *Salario:* {job.get('salary_info') or job.get('salary', 'No especificado')}\n"
        f"📡 *Fuente:* {job.get('source', '')}\n"
        f"{remote_icon} | {english_icon}\n\n"
        f"🎯 *Match: {job['match_score']}%*\n"
        f"{_match_bar(job['match_score'])}\n"
        f"_{job.get('match_summary', '')}_\n\n"
        f"🛠️ *Skills:*\n{skills_text}"
        f"{missing_text}\n\n"
        f"{rec_icon} *Recomendación:* {rec}\n\n"
        f"🔗 [Ver oferta]({job['url']})"
    )

    profile_id = job.get("profile_id", "jeferson")
    webapp_url = os.getenv("WEBAPP_URL", "").rstrip("/")

    keyboard = []
    if webapp_url:
        keyboard.append([
            InlineKeyboardButton("🌐 Ver en App", web_app=WebAppInfo(url=webapp_url)),
        ])
    keyboard += [
        [
            InlineKeyboardButton("✅ Aprobar", callback_data=f"approve:{profile_id}:{job['id']}"),
            InlineKeyboardButton("⏸️ Después", callback_data=f"later:{profile_id}:{job['id']}"),
        ],
        [
            InlineKeyboardButton("❌ Rechazar", callback_data=f"reject:{profile_id}:{job['id']}"),
            InlineKeyboardButton("📄 PDF CV", callback_data=f"dl:{profile_id}:{job['id']}"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


async def send_job_notification(app: Application, job: dict, chat_id: int):
    text, markup = build_job_message(job)
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup,
            disable_web_page_preview=False,
        )
        logger.info(f"Notified [{job.get('profile_id')}] {job['title']} @ {job['company']}")
    except Exception as e:
        logger.error(f"Failed to notify {chat_id}: {e}")


# ── Handlers ──────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    profile = _get_profile_by_chat(chat_id)
    name = profile["name"] if profile else "usuario"
    await update.message.reply_text(
        f"🤖 *Job Agent — Hola {name}!*\n\n"
        f"Comandos:\n"
        f"/pending — Ofertas pendientes\n"
        f"/lastcv — Descargar CV de última oferta aprobada\n"
        f"/status — Estado del agente\n"
        f"/myid — Ver tu chat ID",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    profile = _get_profile_by_chat(chat_id)
    status = f"Perfil configurado: *{profile['name']}*" if profile else "⚠️ Sin perfil configurado aún."
    await update.message.reply_text(
        f"Tu chat ID es: `{chat_id}`\n{status}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    profile = _get_profile_by_chat(chat_id)
    if not profile:
        await update.message.reply_text(f"⚠️ Chat ID {chat_id} no está configurado en ningún perfil.")
        return

    jobs = await get_pending_jobs(profile["id"])
    if not jobs:
        await update.message.reply_text("No hay ofertas pendientes.")
        return

    await update.message.reply_text(f"📋 {len(jobs)} oferta(s) pendiente(s). Enviando...")
    for job in jobs[:5]:
        text, markup = build_job_message(job)
        await update.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=markup, disable_web_page_preview=False,
        )
        await asyncio.sleep(0.5)


async def cmd_lastcv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    profile = _get_profile_by_chat(chat_id)
    if not profile:
        await update.message.reply_text("⚠️ Perfil no configurado.")
        return

    jobs = await get_approved_jobs(profile["id"], limit=3)
    if not jobs:
        await update.message.reply_text("No hay ofertas aprobadas aún.")
        return

    await update.message.reply_text(f"📋 Últimas {len(jobs)} oferta(s) aprobada(s):")
    for job in jobs:
        try:
            cv_text = job.get("cv_adapted", "")
            if not cv_text:
                await update.message.reply_text(f"⏳ Adaptando CV para {job['title']}...")
                profile_data_path = PROFILES_DIR / profile["id"] / "profile.json"
                profile_data = json.loads(profile_data_path.read_text()) if profile_data_path.exists() else {}
                cv_text = await adapt_cv(job, profile_data)
            cfg = json.loads((PROFILES_DIR / profile["id"] / "config.json").read_text())
            candidate_name = cfg.get("name", profile["id"])
            filepath = render_to_pdf(cv_text, job["title"], job["company"], candidate_name)
            with open(filepath, "rb") as f:
                await update.message.reply_document(
                    document=InputFile(f, filename=filepath.name),
                    caption=f"📄 {job['title']} @ {job['company']} ({job['match_score']}%)\n🔗 {job['url']}",
                )
        except Exception as e:
            logger.error(f"lastcv error: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error con {job['title']}: {e}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    profile = _get_profile_by_chat(chat_id)
    name = profile["name"] if profile else "desconocido"
    await update.message.reply_text(f"✅ Job Agent activo — perfil: *{name}*", parse_mode=ParseMode.MARKDOWN)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_chat.id
    data = query.data
    logger.info(f"Callback: {data} from chat_id={chat_id}")

    # Format: action:profile_id:job_id (new) or action:job_id (legacy)
    parts = data.split(":", 2)
    if len(parts) == 3:
        action, profile_id, job_id = parts
    elif len(parts) == 2:
        # Legacy format — infer profile from chat_id
        action, job_id = parts
        profile = _get_profile_by_chat(chat_id)
        profile_id = profile["id"] if profile else "jeferson"
        logger.info(f"Legacy callback detected, inferred profile_id={profile_id}")
    else:
        logger.warning(f"Unrecognized callback format: {data}")
        return

    job = await get_job(job_id, profile_id)
    if not job:
        await query.message.reply_text("Oferta no encontrada.")
        return

    # Load profile data for CV adaptation
    profile_config_path = PROFILES_DIR / profile_id / "config.json"
    profile_data_path = PROFILES_DIR / profile_id / "profile.json"
    profile_data = json.loads(profile_data_path.read_text()) if profile_data_path.exists() else {}

    if action == "approve":
        await update_job_status(job_id, profile_id, "approved")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"✅ *Aprobada:* {job['title']} @ {job['company']}\n\n"
            f"🔗 Aplica aquí: {job['url']}\n\n"
            f"⏳ Generando CV adaptado...",
            parse_mode=ParseMode.MARKDOWN,
        )
        # Auto-send PDF + cover letter on approval
        try:
            cfg = json.loads((PROFILES_DIR / profile_id / "config.json").read_text())
            candidate_name = cfg.get("name", profile_id)
            primary_language = cfg.get("primary_language", "English")

            cv_text = job.get("cv_adapted", "")
            if not cv_text:
                cv_text = await adapt_cv(job, profile_data, primary_language=primary_language)

            filepath = render_to_pdf(cv_text, job["title"], job["company"], candidate_name)
            with open(filepath, "rb") as f:
                await query.message.reply_document(
                    document=InputFile(f, filename=filepath.name),
                    caption=f"📄 CV listo para {job['title']} @ {job['company']}",
                )

            # Cover letter
            cover = await generate_cover_letter(job, profile_data, primary_language=primary_language)
            label = "📝 *Carta de presentación:*" if primary_language == "Spanish" else "📝 *Cover Letter:*"
            await query.message.reply_text(
                f"{label}\n\n{cover}",
                parse_mode=ParseMode.MARKDOWN,
            )

            # Interview questions
            questions = await generate_interview_questions(job, profile_data, primary_language=primary_language)
            qlabel = "🎯 *Preguntas probables de entrevista:*" if primary_language == "Spanish" else "🎯 *Likely Interview Questions:*"
            await query.message.reply_text(
                f"{qlabel}\n\n{questions}",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error(f"Auto PDF on approve failed: {e}", exc_info=True)
            await query.message.reply_text("⚠️ No se pudo generar el PDF. Usa /lastcv para reintentarlo.")

    elif action == "reject":
        await update_job_status(job_id, profile_id, "rejected")
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"❌ Rechazada: {job['title']} @ {job['company']}")

    elif action == "later":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("⏸️ Guardada. Usa /pending para revisarla.")

    elif action == "cv":
        cv_text = job.get("cv_adapted", "")
        if not cv_text:
            await query.message.reply_text("CV no disponible.")
            return
        chunks = [cv_text[i:i+4000] for i in range(0, len(cv_text), 4000)]
        for idx, chunk in enumerate(chunks):
            header = f"📄 *CV Parte {idx+1}/{len(chunks)}*\n\n" if len(chunks) > 1 else "📄 *CV Adaptado:*\n\n"
            await query.message.reply_text(
                header + f"```\n{chunk}\n```",
                parse_mode=ParseMode.MARKDOWN,
            )

    elif action == "dl":
        try:
            await query.message.reply_text("⏳ Generando PDF...")
            cv_text = job.get("cv_adapted", "")
            if not cv_text:
                await query.message.reply_text("⏳ Adaptando CV con IA...")
                cv_text = await adapt_cv(job, profile_data)

            # Get candidate last name for filename
            profile_cfg_path = PROFILES_DIR / profile_id / "config.json"
            cfg = json.loads(profile_cfg_path.read_text()) if profile_cfg_path.exists() else {}
            candidate_name = cfg.get("name", profile_id)
            filepath = render_to_pdf(cv_text, job["title"], job["company"], candidate_name)
            logger.info(f"PDF generated: {filepath} ({filepath.stat().st_size} bytes)")
            with open(filepath, "rb") as f:
                await query.message.reply_document(
                    document=InputFile(f, filename=filepath.name),
                    caption=f"📄 CV — {job['title']} @ {job['company']}",
                )
            logger.info(f"PDF sent to {chat_id}")
        except Exception as e:
            logger.error(f"PDF generation failed: {e}", exc_info=True)
            await query.message.reply_text(f"❌ Error generando PDF: {e}")


def build_app() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set")

    app = Application.builder().token(token).build()
    async def log_all_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info(f"[RAW UPDATE] type={type(update).__name__} data={update.to_dict()}")

    app.add_handler(TypeHandler(Update, log_all_updates), group=-1)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("lastcv", cmd_lastcv))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(handle_callback))
    return app
