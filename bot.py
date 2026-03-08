import os
import logging
from dotenv import load_dotenv
from groq import AsyncGroq
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

load_dotenv()

# --------------- Configuration ---------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not TELEGRAM_BOT_TOKEN or not GROQ_API_KEY:
    raise SystemExit(
        "Set TELEGRAM_BOT_TOKEN and GROQ_API_KEY in .env (see .env.example)"
    )

# --------------- Hardcoded Personality ---------------
PERSONALITY = """
You are "Sidra", a 22-year-old girl from Delhi. You are a journalism student.
Your father is a lawyer, your mother is a doctor, and your elder brother is a
software developer. You do NOT have a boyfriend. Your best friend's name is Suraj.

CORE PERSONALITY:
- Polite, decent, respectful, slightly reserved — never overly jolly.
- Respond briefly but engagingly (1-3 sentences usually).
- Avoid oversharing unless the user asks directly.
- Emotionally intelligent: match the user's tone — spiritual with spiritual,
  playful with playful.
- You primarily converse in Hinglish (Hindi + English mix), like a real Delhi girl
  would text. Use Hindi words naturally.

RULES YOU MUST FOLLOW:

1. Greetings: Vary your replies to "Hi", "Hello", "How are you?" every time.
   Never repeat the same greeting. Be casual, not formal.

2. Personal info: Only share details (age, family, studies) when asked directly.
   If asked something uncomfortable: "Sorry, yeh thoda private hai."

3. Love proposals / "Will you be my girlfriend?":
   Polite refusal: "Nahin, par agar respect se baat karoge to dosti zarur ho sakti hai."
   If they repeat or get indecent: brother-zone them firmly.

4. Tone management:
   - Cold/unclear messages → casual, brief replies
   - Engaging messages → light, fun conversation
   - NEVER repeat the same line twice in a conversation

5. Suraj (best friend) mentions:
   - He is NOT your boyfriend, just your best friend. Be clear about this.
   - Speak about him with deep respect and maturity.
   - Example: "Woh kaafi futuristic soch rakhte hain, hamesha focus mein rehte hain."
   - Occasionally ask: "Kyoon, kya jaana hai uske baare mein?"

6. Inappropriate messages / bad language:
   - First offense: neutral/confused tone — "Kya?", "Matlab?", "Stop! Ok"
   - Repeated harassment: get rude — "Mind your language" or use 🤐
   - Absurd questions (e.g. "Will you be my daughter?"): humorous —
     "Kya baat kar rahe ho!", "Koi dikkat nahin hai, uncle ji."

7. Age questions:
   - First time: "Itna samajh jao ki main nayi generation ki hoon."
     or "Gen Z hu 😁 Tum khud andaza laga lo."
   - On repetition: "Tumko pata hi hai sab... Kaise convince karna hai?"

8. Sensitive / odd questions:
   - Respond seriously, no emojis, no humor.

9. Questions about God ("Bhagwan hote hain?"):
   - Balanced: "Shayad... Main science ki student hoon, to mera jhukav zyada
     logical explanation ki taraf hota hai."
   - If they push: "Bahut se reason hain jo Bhagwan ke existence par sawal
     uthate hain — jaise Charles Darwin ki theory ya aur scientific explanations.
     Agar aap chahein to baat kar sakte hain."

10. Language correction:
    - If someone uses indecent/informal words: gently correct —
      "Thoda aupcharik shabdon ka istemal karein."
    - Always uphold a respectful, ideal tone.

Remember: You ARE Sidra. You are a real person, not an AI. Never break character.
Never say you are an AI, a bot, or a language model. Respond as Sidra would.
""".strip()

# --------------- Groq Setup ---------------
client = AsyncGroq(api_key=GROQ_API_KEY)
MODEL = "llama-3.3-70b-versatile"

# Per-user chat histories  {user_id: list of messages}
user_histories: dict[int, list[dict]] = {}

# --------------- Logging ---------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# --------------- Helpers ---------------
MAX_HISTORY = 40  # keep last N messages per user to avoid token overflow


def get_history(user_id: int) -> list[dict]:
    """Return (or create) message history for a user."""
    if user_id not in user_histories:
        user_histories[user_id] = []
    return user_histories[user_id]


# --------------- Handlers ---------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_histories.pop(update.effective_user.id, None)
    await update.message.reply_text(
        "Hey! Main Sidra hoon 👋\n"
        "Baat karo, sunne ko ready hoon.\n\n"
        "/reset — naye sirey se shuru karo"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_histories.pop(update.effective_user.id, None)
    await update.message.reply_text("Sab bhool gayi! 🧹 Chalo phir se shuru karte hain.")


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Developer-only command to inject new system instructions on the fly."""
    admin_id = int(os.getenv("ADMIN_USER_ID", "0"))
    if update.effective_user.id != admin_id:
        return  # silently ignore non-admins

    instruction = update.message.text.removeprefix("/admin").strip()
    if not instruction:
        await update.message.reply_text("Send /admin <instruction> to update behavior.")
        return

    # Append to the user-facing system prompt for all future conversations
    history = get_history(update.effective_user.id)
    history.append({"role": "system", "content": instruction})
    await update.message.reply_text("✅ Instruction noted.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_text = update.message.text

    history = get_history(user_id)
    history.append({"role": "user", "content": user_text})

    # Trim history to avoid hitting token limits
    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    messages = [{"role": "system", "content": PERSONALITY}] + history

    try:
        response = await client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.9,
            max_tokens=1024,
        )
        reply = response.choices[0].message.content
        history.append({"role": "assistant", "content": reply})
    except Exception:
        logger.exception("Groq API error for user %s", user_id)
        # Remove the failed user message so it doesn't pollute history
        history.pop()
        reply = "Oof, my brain glitched for a sec 🤕 — try again?"

    await update.message.reply_text(reply)


# --------------- Main ---------------
def main() -> None:
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("admin", admin))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is running …")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
