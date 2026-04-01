import os
import json
import threading
import datetime
import pytz
import re
import uvicorn
import firebase_admin
from firebase_admin import credentials, db
from fastapi import FastAPI, Depends, HTTPException, Security, Response
from fastapi.security.api_key import APIKeyHeader
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ==========================================
# 1. CONFIG & FIREBASE SETUP
# ==========================================
FIREBASE_DB_URL = "https://iplpoints-eb557-default-rtdb.firebaseio.com"
TELEGRAM_TOKEN = "8689038827:AAG5YGwCCjl8G1TCK-yhegBCoIFCvn4_Utk"

# API Key Security
API_KEY_NAME = "iplxlinux"
SECRET_VALUE = "linuxxpreet"

# Firebase Initialization
cred = credentials.Certificate("firebase_key.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': FIREBASE_DB_URL
})

# ==========================================
# HELPER FUNCTION: Match name ko URL friendly banana
# ==========================================
def make_slug(text):
    return re.sub(r'[^a-zA-Z0-9]+', '-', text).strip('-').lower()

# ==========================================
# 2. FASTAPI (WEB SERVER)
# ==========================================
api_app = FastAPI()
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

def verify_key(key: str = Security(api_key_header)):
    if key == SECRET_VALUE:
        return key
    raise HTTPException(status_code=403, detail="Galat Key hai bhai!")

# --- YAHAN CHANGE KIYA HAI ---
@api_app.get("/")
async def status():
    # EKDUM SILENT: 204 No Content. 
    # Server chalega par output 0 bytes aayega, cron-job error nahi dega.
    return Response(status_code=204)
# -----------------------------

# ENDPOINT 1: Saare available matches
@api_app.get("/ipl-fantasy-points/")
async def get_all_matches(key: str = Depends(verify_key)):
    ref = db.reference('matches')
    all_matches = ref.get()
    latest_slug = db.reference('latest_match').get()
    
    if all_matches:
        match_list = []
        for slug, details in all_matches.items():
            match_list.append({
                "match_name": details.get("match_name"),
                "endpoint": f"linuxipl.onrender.com/ipl-fantasy-points/{slug}"
            })
            
        return {
            "status": "success", 
            "latest_endpoint": f"linuxipl.onrender.com/ipl-fantasy-points/{latest_slug}" if latest_slug else None,
            "available_matches": match_list
        }
    return {"status": "error", "message": "Koi match available nahi hai!"}

# ENDPOINT 2: Direct LATEST match data
@api_app.get("/ipl-fantasy-points/latest")
async def get_latest_match_points(key: str = Depends(verify_key)):
    latest_slug = db.reference('latest_match').get()
    if not latest_slug:
        return {"status": "error", "message": "Koi match abhi tak upload nahi hua!"}
        
    ref = db.reference(f'matches/{latest_slug}')
    data = ref.get()
    if data:
        data.pop('target_chat_id', None)
        return {"status": "success", "match_slug": latest_slug, "data": data}
    return {"status": "error", "message": "Latest match ka data nahi mila!"}

# ENDPOINT 3: Specific Match data
@api_app.get("/ipl-fantasy-points/{match_slug}")
async def get_specific_match_points(match_slug: str, key: str = Depends(verify_key)):
    ref = db.reference(f'matches/{match_slug}')
    data = ref.get()
    if data:
        data.pop('target_chat_id', None)
        return {"status": "success", "data": data}
    return {"status": "error", "message": f"'{match_slug}' naam ka koi match nahi mila!"}

def start_server():
    # Port configuration for Render (saalo saal chalne ke liye)
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(api_app, host="0.0.0.0", port=port, access_log=False, log_level="error")

# ==========================================
# 3. TELEGRAM BOT (CONVERSATION)
# ==========================================
JSON_IN, MATCH_NAME_IN = range(2)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏏 *IPL Admin Mode*\nJSON text paste kar do bhai:", parse_mode='Markdown')
    return JSON_IN

async def handle_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['players'] = json.loads(update.message.text)
        await update.message.reply_text("✅ JSON sahi hai! Ab Match Name batao (e.g. MI vs GT):")
        return MATCH_NAME_IN
    except:
        await update.message.reply_text("❌ Galat JSON hai! Dobara sahi se bhej.")
        return JSON_IN

async def handle_match(update: Update, context: ContextTypes.DEFAULT_TYPE):
    match_name = update.message.text
    match_slug = make_slug(match_name)
    players = context.user_data.get('players')
    
    final_data = {
        "match_name": match_name,
        "players": players,
        "last_updated": str(datetime.datetime.now(pytz.timezone('Asia/Kolkata'))),
        "target_chat_id": update.effective_chat.id 
    }
    
    db.reference(f'matches/{match_slug}').set(final_data)
    db.reference('latest_match').set(match_slug)
    
    reply_msg = (
        f"🚀 Match '{match_name}' data Firebase pe update ho gaya!\n\n"
        f"🔗 *Tera Endpoint:*\n"
        f"`linuxipl.onrender.com/ipl-fantasy-points/{match_slug}`"
    )
    await update.message.reply_text(reply_msg, parse_mode='Markdown')
    return ConversationHandler.END

async def daily_broadcast(context: ContextTypes.DEFAULT_TYPE):
    latest_slug = db.reference('latest_match').get()
    if not latest_slug: return
    data = db.reference(f'matches/{latest_slug}').get()
    if not data: return
    chat_id = data.get('target_chat_id')
    if not chat_id: return

    msg = f"🏏 *TATA IPL 2026: {data['match_name']}*\n" + "➖"*15 + "\n"
    for p, pts in data['players'].items():
        msg += f"▪️ {p} : `{pts}` pts\n"
    
    await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

# ==========================================
# 4. EXECUTION
# ==========================================
if __name__ == '__main__':
    # Threading server ko background mein chalayega
    threading.Thread(target=start_server, daemon=True).start()

    bot = Application.builder().token(TELEGRAM_TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler('update', start_cmd)],
        states={
            JSON_IN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_json)],
            MATCH_NAME_IN: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_match)],
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
    )
    bot.add_handler(conv)
    
    ist = pytz.timezone('Asia/Kolkata')
    bot.job_queue.run_daily(daily_broadcast, time=datetime.time(hour=23, minute=30, tzinfo=ist))

    print("System started with Silent Root Endpoint! Port listener active.")
    bot.run_polling()
