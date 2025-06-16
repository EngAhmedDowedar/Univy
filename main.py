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

# إعدادات Gemini API
MODEL = 'gemini-1.5-flash'
BASE_URL = f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}'

# إعدادات Google Drive API
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json'
DRIVE_FOLDER_ID = '1767thuB9M0Zj9t1n1-lTsoFAhV68XF9r'

# إعدادات الاشتراك الإجباري
YOUTUBE_CHANNEL_URL = 'https://www.youtube.com/@DowedarTech'
TELEGRAM_CHANNEL_ID = '@dowedar_tech'

# إعدادات تحديد المعدل
COOLDOWN_SECONDS = 25  # فترة الانتظار بين كل سؤال للمستخدم الواحد

# متغيرات عامة
file_lock = Lock()
book_cache = {}

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
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"خطأ في إعداد خدمة Google Drive: {e}")
        return None

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
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.post(BASE_URL, headers=headers, json=data, timeout=120)
            
            if response.status_code == 429:
                wait_time = (2 ** attempt) + 1 
                print(f"واجهنا خطأ 429 (Too Many Requests). سننتظر {wait_time} ثانية ونحاول مجدداً...")
                log_interaction(from_user, "⚠️ تحذير: ضغط على API", f"محاولة {attempt + 1} فشلت. سيتم الانتظار {wait_time} ثانية.")
                time.sleep(wait_time)
                continue

            response.raise_for_status()
            
            result = response.json()
            if 'candidates' in result and result['candidates']:
                if 'content' in result['candidates'][0] and 'parts' in result['candidates'][0]['content']:
                    return result['candidates'][0]['content']['parts'][0]['text']

            log_interaction(from_user, "⚠️ تحذير من Gemini", f"الرد من API لم يكن بالتنسيق المتوقع.\n`{result}`")
            return "لم أتمكن من توليد رد. يرجى المحاولة مرة أخرى."
            
        except requests.exceptions.RequestException as e:
            print(f"خطأ في اتصال Gemini API: {e}")
            log_interaction(from_user, "❌ خطأ في اتصال Gemini", f"تفاصيل الخطأ:\n`{e}`")
            if attempt < max_retries - 1:
                time.sleep((2 ** attempt) + 1)
                continue
            else:
                return "حدثت مشكلة في الاتصال بالخادم بعد عدة محاولات. يرجى المحاولة لاحقًا."
        except Exception as e:
            print(f"خطأ غير متوقع في Gemini: {e}")
            log_interaction(from_user, "❌ خطأ غير متوقع في Gemini", f"تفاصيل الخطأ:\n`{e}`")
            return "حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى."
            
    return "لقد واجه الخادم ضغطاً عالياً. يرجى المحاولة مرة أخرى بعد دقيقة."
        
def send_long_message(chat_id, text, **kwargs):
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

def check_membership(user_id):
    try:
        member = bot.get_chat_member(TELEGRAM_CHANNEL_ID, user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception as e:
        print(f"خطأ أثناء التحقق من الاشتراك للمستخدم {user_id}: {e}")
        return False

def send_subscription_message(chat_id):
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    btn_youtube = telebot.types.InlineKeyboardButton("اشترك في قناة اليوتيوب 🔴", url=YOUTUBE_CHANNEL_URL)
    btn_telegram = telebot.types.InlineKeyboardButton("اشترك في قناة التليجرام 🔵", url=f"https://t.me/{TELEGRAM_CHANNEL_ID.replace('@', '')}")
    btn_check = telebot.types.InlineKeyboardButton("✅ تحققت من الاشتراك", callback_data="check_subscription")
    markup.add(btn_youtube, btn_telegram, btn_check)
    bot.send_message(chat_id, 
                     "🛑 *عذراً، يجب عليك الاشتراك في القنوات التالية أولاً لاستخدام البوت:*\n\n"
                     "هذا يساعدنا على الاستمرار وتقديم المزيد من المحتوى المفيد. شكراً لدعمك! 🙏",
                     reply_markup=markup, parse_mode="Markdown")

# --- معالجات رسائل التليجرام (Handlers) ---
def send_help_message(chat_id):
    help_text = """
🎯 *معلومات البوت والإرشادات*

🛠 *تم التطوير بواسطة:*
Eng. Ahmed Dowedar
📧 للتواصل: @engahmeddowedar

🤖 *ما هو هذا البوت؟*
- بوت ذكاء اصطناعي متقدم يعمل بنظام Gemini من Google
- صمم خصيصاً لخدمة البحث العلمي والمعرفي
- يدعم البحث العام والبحث في الكتب والمصادر
- يدعم ملفات PDF وTXT بكفاءة عالية

📌 *سياسة الاستخدام:*
1. ممنوع استخدام البوت للأسئلة الشخصية عن المطور
2. يخصص البوت للأسئلة العلمية والعملية فقط
3. الأسئلة غير المفيدة سيتم تجاهلها
4. التواصل الرسمي فقط عبر المعرف @engahmeddowedar

📚 *كيفية الاستخدام الأمثل:*
1. اختر نوع البحث (عام أو في الكتب)
2. اكتب سؤالك العلمي/المعرفي بشكل واضح
3. استخدم موارد البوت بتركيز على المواضيع المفيدة

⚙️ *ميزات البوت:*
- تقنيات متقدمة في البحث العلمي
- فهم عميق للأسئلة الأكاديمية
- دعم المحادثات المتعلقة بالبحث فقط
- واجهة مخصصة للاستخدام الجاد

🛠 *للاستفادة القصوى:*
- ركز أسئلتك على المواضيع العلمية والعملية
- تجنب الأسئلة الشخصية أو غير الهادفة
- للتواصل المهني فقط عبر المعرف أعلاه
- استخدم ميزة البحث في الكتب للاستفادة القصوى
"""
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("⬅️ العودة إلى القائمة الرئيسية", callback_data="main_menu"))
    bot.send_message(chat_id, help_text, parse_mode="Markdown", reply_markup=markup)

def show_main_menu(chat_id, message_id=None):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    btn_general = telebot.types.InlineKeyboardButton("🤖 بحث عام (AI)", callback_data="search_general")
    btn_books = telebot.types.InlineKeyboardButton("📚 بحث في المصادر", callback_data="search_books")
    btn_help = telebot.types.InlineKeyboardButton("📜 مساعدة وإرشادات", callback_data="show_help")
    btn_feedback = telebot.types.InlineKeyboardButton("📝 اقتراح أو مشكلة", callback_data="send_feedback")
    markup.add(btn_general, btn_books, btn_help, btn_feedback)
    text = "✅ أهلاً بك من جديد!\n\nاختر من فضلك ما تريد فعله:"
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
        except Exception as e:
            print(f"Failed to edit message: {e}")
            bot.send_message(chat_id, text, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)

def show_book_list(chat_id, message_id=None):
    text = "⏳ جارٍ جلب قائمة الكتب..."
    try:
        if message_id:
            bot.edit_message_text(text, chat_id, message_id)
        else:
            msg = bot.send_message(chat_id, text)
            message_id = msg.message_id
    except Exception as e:
        print(f"Error showing book list (initial): {e}")
        msg = bot.send_message(chat_id, text)
        message_id = msg.message_id
    books = list_books()
    if not books:
        bot.edit_message_text("عذرًا، لم أجد كتبًا في المجلد المخصص.", chat_id, message_id)
        return
    users = load_users()
    user_data = users.get(str(chat_id), {})
    user_data['available_books'] = books
    save_users(users)
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    for book in books:
        markup.add(telebot.types.InlineKeyboardButton(book['name'], callback_data=f"book:{book['id']}"))
    markup.add(telebot.types.InlineKeyboardButton("⬅️ العودة إلى القائمة الرئيسية", callback_data="main_menu"))
    bot.edit_message_text("اختر الكتاب الذي تريد البحث فيه:", chat_id, message_id, reply_markup=markup)

@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = str(message.chat.id)
    log_interaction(message.from_user, "بدء استخدام البوت", f"المستخدم ضغط /start")
    remove_markup = telebot.types.ReplyKeyboardRemove()
    try:
        temp_msg = bot.send_message(chat_id, "...", reply_markup=remove_markup, disable_notification=True)
        bot.delete_message(chat_id, temp_msg.message_id)
    except Exception as e:
        print(f"Could not remove reply keyboard: {e}")
    if check_membership(message.from_user.id):
        users = load_users()
        if chat_id not in users:
            users[chat_id] = {"state": "main_menu", "chat_history": []}
            print(f"مستخدم جديد تم تسجيله: {chat_id}")
            log_interaction(message.from_user, "تسجيل مستخدم جديد")
        users[chat_id]['state'] = 'main_menu'
        save_users(users)
        show_main_menu(chat_id)
    else:
        send_subscription_message(chat_id)
        log_interaction(message.from_user, "فشل التحقق من الاشتراك", "تم إرسال رسالة الاشتراك.")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    chat_id = str(call.message.chat.id)
    action = call.data
    log_interaction(call.from_user, "ضغط زر", f"البيانات: `{action}`")
    bot.answer_callback_query(call.id)
    if action == 'check_subscription':
        if check_membership(call.from_user.id):
            bot.delete_message(chat_id, call.message.message_id)
            handle_start(call.message) 
        else:
            bot.answer_callback_query(call.id, "❌ لم تشترك بعد. يرجى الاشتراك ثم المحاولة مجدداً.", show_alert=True)
        return
    if not check_membership(call.from_user.id):
        send_subscription_message(chat_id)
        return
    users = load_users()
    if chat_id not in users:
        handle_start(call.message)
        return
    user_data = users[chat_id]
    if action == 'main_menu':
        show_main_menu(chat_id, call.message.message_id)
        return
    if action == 'show_help':
        bot.delete_message(chat_id, call.message.message_id)
        send_help_message(chat_id)
        return
    if action == 'send_feedback':
        user_data['state'] = 'awaiting_feedback'
        save_users(users)
        bot.edit_message_text("من فضلك، اكتب الآن اقتراحك أو وصف المشكلة التي تواجهك وسأقوم بإرسالها للمطور.", chat_id, call.message.message_id, reply_markup=telebot.types.ReplyKeyboardRemove())
        return
    if action == "search_general":
        user_data['state'] = 'general_chat'
        user_data['chat_history'] = []
        save_users(users)
        bot.edit_message_text("تم تفعيل وضع البحث العام. تفضل بسؤالك.", chat_id, call.message.message_id, reply_markup=telebot.types.ReplyKeyboardRemove())
    elif action == "search_books":
        show_book_list(chat_id, call.message.message_id)
    elif action.startswith("book:"):
        try:
            _, book_id = action.split(':', 1)
            available_books = user_data.get('available_books', [])
            book_name = next((b['name'] for b in available_books if b['id'] == book_id), None)
            if not book_name:
                bot.edit_message_text("حدث خطأ، لم يتم العثور على الكتاب. حاول مرة أخرى.", chat_id, call.message.message_id)
                return
            user_data['state'] = 'book_chat'
            user_data['chat_history'] = []
            user_data['selected_book_id'] = book_id
            user_data['selected_book_name'] = book_name
            user_data.pop('available_books', None)
            save_users(users)
            bot.delete_message(chat_id, call.message.message_id)
            loading_msg = bot.send_message(chat_id, f"⏳ يتم الآن تحميل ومعالجة كتاب '{book_name}'...")
            content = get_book_content(book_id, book_name)
            bot.delete_message(chat_id, loading_msg.message_id)
            reply_markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
            reply_markup.add(telebot.types.KeyboardButton("⬅️ العودة إلى قائمة الكتب"))
            if "خطأ:" in content:
                bot.send_message(chat_id, content)
            else:
                bot.send_message(chat_id, f"✅ تم تحميل كتاب '{book_name}'.\nيمكنك الآن طرح أسئلتك حول محتواه.", reply_markup=reply_markup)
        except Exception as e:
            bot.send_message(chat_id, f"حدث خطأ في معالجة اختيارك: {e}")

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
        bot.send_message(chat_id, "جاري العودة لقائمة الكتب...", reply_markup=remove_markup, disable_notification=True)
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

if __name__ == "__main__":
    print(f"Starting Gemini Bot (v1.5 - Stable)... [ Shirbin - {time.strftime('%Y-%m-%d %H:%M:%S')} ]")
    bot.infinity_polling()
