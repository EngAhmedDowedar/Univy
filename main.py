import os
import telebot
import json
import re
import requests
import time
from threading import Lock

# إضافة مكتبات Google Drive و PDF
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import fitz  # PyMuPDF

# --- إعدادات البوت ---
LOG_BOT_TOKEN = os.getenv('LOG_BOT_TOKEN', '8141683551:AAELKx91_D5coF3X5Amnv_d44REWh3gkDxc')
LOG_CHAT_ID = os.getenv('LOG_CHAT_ID', '2029139293')
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '7739465299:AAGOANXaygnCyjmInyAfpfOYoepE2W8_m1M')
API_KEY = os.getenv('GEMINI_API_KEY', 'AIzaSyBGgDeRu83fMID-rCFDQJRDywhqCO1cRPE')

if not all([BOT_TOKEN, API_KEY, LOG_BOT_TOKEN, LOG_CHAT_ID]):
    raise ValueError("يجب تعيين جميع متغيرات البيئة المطلوبة!")

bot = telebot.TeleBot(BOT_TOKEN)

# ... (باقي الإعدادات والدوال كما هي حتى نصل إلى دالة send_to_gemini) ...

# --- دوال التعامل مع الملفات (users.json) ---
def load_users():
    try:
        with file_lock:
            with open("users.json", "r", encoding='utf-8') as f:
                return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    except Exception as e:
        print(f"خطأ في تحميل المستخدمين: {e}")
        return {}

def save_users(data):
    with file_lock:
        try:
            with open("users.json", "w", encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"خطأ في حفظ المستخدمين: {e}")

# --- دوال Google Drive ---
def get_drive_service():
    try:
        creds = service_account.Credentials.from_service_account_file(
            'credentials.json', scopes=['https://www.googleapis.com/auth/drive.readonly'])
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"خطأ في إعداد خدمة Google Drive: {e}")
        return None
# ... (باقي دوال Drive كما هي) ...

def list_books():
    service = get_drive_service()
    if not service: return []
    try:
        results = service.files().list(
            q=f"'{DRIVE_FOLDER_ID}' in parents and trashed=false",
            fields="nextPageToken, files(id, name)").execute()
        return results.get('files', [])
    except Exception as e:
        print(f"خطأ في جلب قائمة الكتب: {e}")
        return []

def get_book_content(file_id, file_name):
    if file_id in book_cache:
        print(f"جلب الكتاب '{file_name}' من الذاكرة المؤقتة (Cache).")
        return book_cache[file_id]
    service = get_drive_service()
    if not service: return "خطأ: لا يمكن الاتصال بخدمة Google Drive."
    try:
        request = service.files().get_media(fileId=file_id)
        file_io = io.BytesIO()
        downloader = MediaIoBaseDownload(file_io, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            print(f"Downloading {file_name}: {int(status.progress() * 100)}%.")
        file_io.seek(0)
        text = ""
        if file_name.lower().endswith('.pdf'):
            with fitz.open(stream=file_io, filetype="pdf") as doc:
                text = "".join(page.get_text() for page in doc)
        elif file_name.lower().endswith('.txt'):
            text = file_io.read().decode('utf-8')
        else:
            return f"خطأ: صيغة الملف '{file_name}' غير مدعومة."
        book_cache[file_id] = text
        print(f"تمت معالجة وتخزين الكتاب '{file_name}' في الكاش.")
        return text
    except Exception as e:
        print(f"خطأ في جلب محتوى الكتاب '{file_name}': {e}")
        return f"حدث خطأ أثناء محاولة الوصول للكتاب: {file_name}"

# --- دوال البوت ---
def log_interaction(from_user, event_type, details=""):
    try:
        user_info = (
            f"👤 *المستخدم:*\n"
            f"- الاسم: {from_user.first_name} {from_user.last_name or ''}\n"
            f"- اليوزر: @{from_user.username or 'N/A'}\n"
            f"- الآي دي: `{from_user.id}`"
        )
        log_message = f"📌 *{event_type}*\n\n{user_info}\n\n{details}"
        url = f"https://api.telegram.org/bot{LOG_BOT_TOKEN}/sendMessage"
        params = {'chat_id': LOG_CHAT_ID, 'text': log_message, 'parse_mode': 'Markdown', 'disable_web_page_preview': True}
        requests.post(url, json=params, timeout=10)
    except Exception as e:
        print(f"❌ فشل إرسال اللوج: {e}")

# --- تم تعديل هذه الدالة لإضافة الإبلاغ عن الأخطاء ---
def send_to_gemini(from_user, prompt, chat_history=None, context=""):
    headers = {'Content-Type': 'application/json'}
    final_prompt = prompt
    if context:
        final_prompt = (
            f"أجب على السؤال التالي بناءً على النص المرفق فقط. إذا كانت الإجابة غير موجودة في النص، قل بوضوح 'الإجابة غير متوفرة في المصدر'.\n\n"
            f"--- بداية النص المرجعي ---\n{context}\n--- نهاية النص المرجعي ---\n\n"
            f"السؤال: {prompt}"
        )
    contents = chat_history or []
    contents.append({"role": "user", "parts": [{"text": final_prompt}]})
    data = {"contents": contents, "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192}}
    try:
        response = requests.post(
            f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}',
            headers=headers, json=data, timeout=120
        )
        response.raise_for_status()  # سيعطي خطأ للاستجابات غير 2xx
        result = response.json()
        if 'candidates' in result and result['candidates']:
            if 'content' in result['candidates'][0] and 'parts' in result['candidates'][0]['content']:
                return result['candidates'][0]['content']['parts'][0]['text']
        # إذا لم يجد ردًا مناسبًا
        log_interaction(from_user, "⚠️ تحذير من Gemini", f"الرد من API لم يكن بالتنسيق المتوقع.\n`{result}`")
        return "لم أتمكن من توليد رد. يرجى المحاولة مرة أخرى."
    except requests.exceptions.RequestException as e:
        print(f"خطأ في اتصال Gemini API: {e}")
        # --- جديد: إرسال تفاصيل الخطأ لبوت اللوجات ---
        log_interaction(from_user, "❌ خطأ في اتصال Gemini", f"تفاصيل الخطأ:\n`{e}`")
        return "حدثت مشكلة في الاتصال بالخادم. يرجى المحاولة لاحقًا."
    except Exception as e:
        print(f"خطأ غير متوقع في Gemini: {e}")
        log_interaction(from_user, "❌ خطأ غير متوقع في Gemini", f"تفاصيل الخطأ:\n`{e}`")
        return "حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى."

def send_long_message(chat_id, text, **kwargs):
    # ... الكود كما هو ...
    MAX_LENGTH = 4096
    if len(text) <= MAX_LENGTH:
        bot.send_message(chat_id, text, **kwargs)
        return

    parts = []
    current_part = ""
    paragraphs = text.split('\n\n')
    for para in paragraphs:
        if len(current_part) + len(para) + 2 > MAX_LENGTH:
            parts.append(current_part)
            current_part = para + "\n\n"
        else:
            current_part += para + "\n\n"
    if current_part:
        parts.append(current_part)

    for part in parts:
        if part.strip():
            bot.send_message(chat_id, part, **kwargs)
            time.sleep(1)

# ... (باقي الدوال ومعالجات الرسائل كما هي حتى نصل إلى handle_user_message) ...
@bot.message_handler(func=lambda m: True)
def handle_user_message(message):
    chat_id = str(message.chat.id)
    if not check_membership(message.from_user.id):
        send_subscription_message(chat_id)
        return
    users = load_users()
    if chat_id not in users:
        handle_start(message)
        return
    if message.text == "⬅️ العودة إلى قائمة الكتب":
        log_interaction(message.from_user, "العودة لقائمة الكتب")
        remove_markup = telebot.types.ReplyKeyboardRemove()
        bot.send_message(chat_id, "جاري العودة لقائمة الكتب...", reply_markup=remove_markup)
        show_book_list(chat_id)
        return
    user_data = users[chat_id]
    user_state = user_data.get('state')
    if user_state == 'awaiting_feedback':
        feedback_text = message.text
        log_interaction(message.from_user, "📝 اقتراح/مشكلة جديدة", f"الرسالة: {feedback_text}")
        bot.send_message(chat_id, "✅ شكرًا لك! تم استلام رسالتك وسيتم مراجعتها.")
        user_data['state'] = 'main_menu'
        save_users(users)
        show_main_menu(chat_id)
        return
    
    if user_state in ['general_chat', 'book_chat']:
        current_time = time.time()
        last_query_time = user_data.get('last_query_time', 0)
        
        if current_time - last_query_time < COOLDOWN_SECONDS:
            remaining_time = round(COOLDOWN_SECONDS - (current_time - last_query_time))
            bot.send_message(chat_id, f"⏳ الرجاء الانتظار {remaining_time} ثانية قبل طرح سؤال جديد.")
            return
            
        user_data['last_query_time'] = current_time
        save_users(users)

        processing_msg = bot.send_message(chat_id, "⏳ جارِ معالجة طلبك...")
        context = ""
        if user_state == 'book_chat':
            book_id = user_data.get('selected_book_id')
            book_name = user_data.get('selected_book_name')
            if not book_id:
                bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
                bot.send_message(chat_id, "حدث خطأ، لم يتم تحديد كتاب.")
                return
            context = get_book_content(book_id, book_name)
            if "خطأ:" in context:
                bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
                bot.send_message(chat_id, context)
                return
        
        # --- تعديل رئيسي هنا: تمرير بيانات المستخدم للدالة ---
        response = send_to_gemini(message.from_user, message.text, user_data.get("chat_history", []), context)
        
        bot.delete_message(chat_id, processing_msg.message_id)
        send_long_message(chat_id, response, parse_mode="Markdown")
        
        if "حدثت مشكلة" not in response and "خطأ" not in response:
            log_details = (f"❓ *السؤال:*\n{message.text}\n\n" f"🤖 *الرد:*\n{response}")
            log_interaction(message.from_user, f"محادثة جديدة ({user_state})", log_details)
        
        user_data.setdefault("chat_history", []).append({"role": "user", "parts": [{"text": message.text}]})
        user_data["chat_history"].append({"role": "model", "parts": [{"text": response}]})
        user_data["chat_history"] = user_data["chat_history"][-10:] 
        save_users(users)
    else:
        show_main_menu(chat_id)

# يجب نسخ باقي الدوال ومعالجات الأزرار كما هي...
# (show_main_menu, show_book_list, handle_start, handle_callback_query, send_help_message)

# ... (الكود الكامل لباقي الدوال)
