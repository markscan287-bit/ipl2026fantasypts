import os
import json
import threading
import datetime
import pytz
import uvicorn
import firebase_admin
from firebase_admin import credentials, db
from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# ==========================================
# 1. CONFIG & FIREBASE SETUP
# ==========================================
FIREBASE_DB_URL = "https://iplpoints-eb557-default-rtdb.firebaseio.com" # e.g. https://your-db.firebaseio.com/
TELEGRAM_TOKEN = "8689038827:AAG5YGwCCjl8G1TCK-yhegBCoIFCvn4_Utk"

# API Key Security
API_KEY_NAME = "iplxlinux"
SECRET_VALUE = "linuxxpreet"

# Firebase Initialization
cred = credentials.Certificate("firebase_key.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': "https://iplpoints-eb557-default-rtdb.firebaseio.com"
})

# ==========================================
# 2. FASTAPI (WEB SERVER)
# ==========================================
api_app = FastAPI()
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

def verify_key(key: str = Security(api_key_header)):
    if key == SECRET_VALUE:
        return key
    raise HTTPException(status_code=403, detail="Galat Key hai bhai!")

@api_app.get("/")
async def status():
    return {"status": "running", "database": "connected"}

@api_app.get("/ipl-fantasy-points/")
async def get_points(key: str = Depends(verify_key)):
    ref = db.reference('current_match')
    data = ref.get()
    if data:
        # Ye safely 'target_chat_id' ko dictionary se uda dega
        data.pop('target_chat_id', None)
        return {"status": "success", "data": data}
    return {"status": "error", "message": "Database empty hai!"}

def start_server():
    # Render se port automatically uthayega
    port = int(os.environ.get("PORT", 8000))
    # 🔥 YAHAN CHANGE KIYA HAI: Faltu logs band kar diye taaki output too large na ho
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
    players = context.user_data.get('players')
    
    final_data = {
        "match_name": match_name,
        "players": players,
        "last_updated": str(datetime.datetime.now(pytz.timezone('Asia/Kolkata'))),
        "target_chat_id": update.effective_chat.id 
    }
    
    db.reference('current_match').set(final_data)
    
    await update.message.reply_text(f"🚀 Match '{match_name}' data Firebase pe update ho gaya!")
    return ConversationHandler.END

async def daily_broadcast(context: ContextTypes.DEFAULT_TYPE):
    data = db.reference('current_match').get()
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

    print("System started with Firebase! Web Server running quietly.")
    bot.run_polling()
