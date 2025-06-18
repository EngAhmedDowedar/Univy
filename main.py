import os
import telebot
import json
import requests
import time
from threading import Lock
from itertools import cycle
from dotenv import load_dotenv
import io

# --- المكتبات المطلوبة ---
import google.generativeai as genai
import chromadb
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import fitz  # PyMuPDF

# --- تحميل متغيرات البيئة من ملف .env ---
load_dotenv()

# --- إعدادات البوت والـ API ---
LOG_BOT_TOKEN = os.getenv('LOG_BOT_TOKEN')
LOG_CHAT_ID = os.getenv('LOG_CHAT_ID')
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
API_KEYS_STRING = os.getenv('API_KEYS')
FEEDBACK_BOT_TOKEN = os.getenv('FEEDBACK_BOT_TOKEN')
DEVELOPER_CHAT_ID = os.getenv('DEVELOPER_CHAT_ID') 

# --- التحقق من وجود كل المتغيرات المطلوبة ---
if not all([BOT_TOKEN, LOG_BOT_TOKEN, LOG_CHAT_ID, API_KEYS_STRING, FEEDBACK_BOT_TOKEN, DEVELOPER_CHAT_ID]):
    raise ValueError("أحد متغيرات البيئة المطلوبة غير موجود! تأكد من وجود كل التوكنات والـ IDs.")

API_KEYS = [key.strip() for key in API_KEYS_STRING.split(',')]
api_key_cycler = cycle(API_KEYS)

bot = telebot.TeleBot(BOT_TOKEN)

# --- إعدادات Gemini و RAG ---
try:
    genai.configure(api_key=next(api_key_cycler))
except Exception as e:
    print(f"فشل في إعداد مكتبة Gemini، تأكد من صحة المفاتيح: {e}")

MODEL_GENERATION = 'gemini-1.5-flash'
MODEL_EMBEDDING = 'models/text-embedding-004'

# --- إعداد قاعدة البيانات المتجهة (Vector DB) ---
chroma_client = chromadb.Client()
vector_collection = chroma_client.get_or_create_collection(name="dowedar_rag_collection")

# --- إعدادات Google Drive والاشتراك الإجباري ---
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json'
DRIVE_FOLDER_ID = os.getenv('DRIVE_FOLDER_ID')
YOUTUBE_CHANNEL_URL = os.getenv('YOUTUBE_CHANNEL_URL')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
COOLDOWN_SECONDS = int(os.getenv('COOLDOWN_SECONDS', 15))

# متغيرات عامة
file_lock = Lock()

# --- دوال التعامل مع الملفات (users.json) ---
def load_users():
    try:
        with file_lock:
            with open("users.json", "r", encoding='utf-8') as f:
                return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_users(data):
    with file_lock:
        with open("users.json", "w", encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

# --- دوال Google Drive ---
def get_drive_service():
    try:
        creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"خطأ في إعداد خدمة Google Drive: {e}")
        return None

def list_books():
    service = get_drive_service()
    if not service: return []
    try:
        results = service.files().list(q=f"'{DRIVE_FOLDER_ID}' in parents and trashed=false", fields="files(id, name)").execute()
        return results.get('files', [])
    except Exception as e:
        print(f"خطأ في جلب قائمة الكتب: {e}")
        return []

# --- دوال الـ RAG (البحث الذكي) ---
def chunk_text(text: str, chunk_size=750, chunk_overlap=100) -> list[str]:
    if not text: return []
    words = text.split()
    chunks = []
    current_pos = 0
    while current_pos < len(words):
        end_pos = current_pos + chunk_size
        chunk_words = words[current_pos:end_pos]
        chunks.append(" ".join(chunk_words))
        current_pos += chunk_size - chunk_overlap
    return [c for c in chunks if c.strip()]

def index_book(book_id, book_name, message):
    existing = vector_collection.get(where={"book_id": book_id}, limit=1)
    if existing['ids']:
        print(f"الكتاب '{book_name}' مفهرس بالفعل.")
        return "indexed"
    
    bot.edit_message_text(f"⏳ يتم الآن تجهيز وفهرسة كتاب '{book_name}'...\n(قد تستغرق هذه العملية عدة دقائق)", message.chat.id, message.message_id)
    service = get_drive_service()
    if not service: return "خطأ: لا يمكن الاتصال بخدمة Google Drive."
    try:
        request = service.files().get_media(fileId=book_id)
        file_io = io.BytesIO()
        downloader = MediaIoBaseDownload(file_io, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            progress = int(status.progress() * 100)
            bot.edit_message_text(f"⏳ يتم الآن تحميل '{book_name}': {progress}%", message.chat.id, message.message_id)
        
        file_io.seek(0)
        text = ""
        bot.edit_message_text(f"⏳ جارٍ قراءة محتوى '{book_name}'...", message.chat.id, message.message_id)
        if book_name.lower().endswith('.pdf'):
            with fitz.open(stream=file_io, filetype="pdf") as doc: text = "".join(page.get_text() for page in doc)
        elif book_name.lower().endswith('.txt'):
            text = file_io.read().decode('utf-8')
        else: return f"خطأ: صيغة الملف '{book_name}' غير مدعومة."
    except Exception as e:
        return f"حدث خطأ أثناء تحميل الكتاب: {e}"

    text_chunks = chunk_text(text)
    if not text_chunks: return "خطأ: لم يتم العثور على نص في الكتاب."
    
    bot.edit_message_text(f"⏳ تم تقسيم الكتاب إلى {len(text_chunks)} فقرة. جارٍ إنشاء الفهرس الذكي...", message.chat.id, message.message_id)
    try:
        result = genai.embed_content(model=MODEL_EMBEDDING, content=text_chunks, task_type="RETRIEVAL_DOCUMENT")
        embeddings = result['embedding']
    except Exception as e:
        print(f"فشل في توليد البصمات الرقمية: {e}")
        return "خطأ: فشل في الاتصال بالذكاء الاصطناعي للفهرسة."

    chunk_ids = [f"{book_id}_{i}" for i in range(len(text_chunks))]
    metadatas = [{"book_id": book_id, "book_name": book_name}] * len(text_chunks)
    vector_collection.add(ids=chunk_ids, embeddings=embeddings, documents=text_chunks, metadatas=metadatas)
    print(f"تمت فهرسة الكتاب '{book_name}' بنجاح.")
    return "indexed"

def retrieve_relevant_context(question, book_id):
    try:
        question_embedding = genai.embed_content(model=MODEL_EMBEDDING, content=question, task_type="RETRIEVAL_QUERY")['embedding']
        results = vector_collection.query(query_embeddings=[question_embedding], n_results=5, where={"book_id": book_id})
        context = "\n---\n".join(results['documents'][0])
        return context
    except Exception as e:
        print(f"خطأ أثناء البحث عن السياق: {e}")
        return f"خطأ في فهم سؤالك أو البحث عنه: {e}"

# --- دوال البوت الأساسية ودوال المطور ---
def log_interaction(from_user, event_type, details=""):
    try:
        user_info = (f"👤 *المستخدم:*\n- الاسم: {from_user.first_name} {from_user.last_name or ''}\n"
                     f"- اليوزر: @{from_user.username or 'N/A'}\n- الآي دي: `{from_user.id}`")
        log_message = f"📌 *{event_type}*\n\n{user_info}\n\n{details}"
        url = f"https://api.telegram.org/bot{LOG_BOT_TOKEN}/sendMessage"
        params = {'chat_id': LOG_CHAT_ID, 'text': log_message, 'parse_mode': 'Markdown', 'disable_web_page_preview': True}
        requests.post(url, json=params, timeout=10)
    except Exception as e:
        print(f"❌ فشل إرسال اللوج: {e}")

def send_feedback_to_dev(from_user, feedback_text):
    try:
        user_info = (f"👤 *مرسل الاقتراح:*\n"
                     f"- الاسم: {from_user.first_name} {from_user.last_name or ''}\n"
                     f"- اليوزر: @{from_user.username or 'N/A'}\n- الآي دي: `{from_user.id}`")
        feedback_message = (f"📬 *اقتراح/مشكلة جديدة!*\n\n{user_info}\n\n"
                            f"✉️ *نص الرسالة:*\n{feedback_text}")
        url = f"https://api.telegram.org/bot{FEEDBACK_BOT_TOKEN}/sendMessage"
        params = {'chat_id': DEVELOPER_CHAT_ID, 'text': feedback_message, 'parse_mode': 'Markdown'}
        requests.post(url, json=params, timeout=10)
    except Exception as e:
        print(f"❌ فشل إرسال رسالة الاقتراح: {e}")

def send_book_to_dev(from_user, document):
    try:
        file_info = bot.get_file(document.file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
        file_content_response = requests.get(file_url, timeout=60)
        file_content_response.raise_for_status()
        file_content = file_content_response.content
        
        user_info = (f"👤 *مرسل الكتاب:*\n"
                     f"- الاسم: {from_user.first_name} {from_user.last_name or ''}\n"
                     f"- اليوزر: @{from_user.username or 'N/A'}\n- الآي دي: `{from_user.id}`")
        caption = (f"📚 *كتاب جديد مقترح!*\n\n{user_info}\n\n"
                   f"📄 *اسم الملف:* `{document.file_name}`\n"
                   f"💾 *الحجم:* {round(document.file_size / 1024, 2)} KB")
        
        url = f"https://api.telegram.org/bot{FEEDBACK_BOT_TOKEN}/sendDocument"
        files = {'document': (document.file_name, file_content)}
        data = {'chat_id': DEVELOPER_CHAT_ID, 'caption': caption, 'parse_mode': 'Markdown'}
        requests.post(url, data=data, files=files, timeout=60)
    except Exception as e:
        print(f"❌ فشل في إرسال الكتاب للمطور: {e}")
        error_message = f"فشل استلام كتاب من المستخدم {from_user.id} (@{from_user.username}). الخطأ: {e}"
        error_url = f"https://api.telegram.org/bot{FEEDBACK_BOT_TOKEN}/sendMessage"
        params = {'chat_id': DEVELOPER_CHAT_ID, 'text': error_message}
        requests.post(error_url, json=params)

def send_to_gemini(from_user, prompt, chat_history=None, context=""):
    headers = {'Content-Type': 'application/json'}
    final_prompt = prompt
    if context:
        final_prompt = (f"أجب على السؤال التالي بناءً على النص المرفق فقط. إذا كانت الإجابة غير موجودة في النص، قل بوضوح 'الإجابة غير متوفرة في المصدر'.\n\n"
                        f"--- بداية النص المرجعي ---\n{context}\n--- نهاية النص المرجعي ---\n\n"
                        f"السؤال: {prompt}")
    contents = (chat_history or []) + [{"role": "user", "parts": [{"text": final_prompt}]}]
    data = {"contents": contents, "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192}}
    max_retries = 3
    for attempt in range(max_retries):
        try:
            current_api_key = next(api_key_cycler)
            url = f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL_GENERATION}:generateContent?key={current_api_key}'
            response = requests.post(url, headers=headers, json=data, timeout=120)
            if response.status_code == 429:
                time.sleep((2 ** attempt) + 1)
                continue
            response.raise_for_status()
            result = response.json()
            if 'candidates' in result and result['candidates'][0].get('content', {}).get('parts'):
                return result['candidates'][0]['content']['parts'][0]['text']
            return "لم أتمكن من توليد رد. يرجى المحاولة مرة أخرى."
        except requests.exceptions.RequestException as e:
            if attempt >= max_retries - 1: return "حدثت مشكلة في الاتصال بالخادم. يرجى المحاولة لاحقًا."
            time.sleep((2 ** attempt) + 1)
        except Exception as e:
            return f"حدث خطأ غير متوقع: {e}"
    return "لقد واجه الخادم ضغطاً عالياً. يرجى المحاولة مرة أخرى بعد دقيقة."

def send_long_message(chat_id, text, **kwargs):
    MAX_LENGTH = 4096
    if len(text) <= MAX_LENGTH:
        bot.send_message(chat_id, text, **kwargs)
        return
    parts = [text[i:i+MAX_LENGTH] for i in range(0, len(text), MAX_LENGTH)]
    for part in parts:
        if part.strip():
            bot.send_message(chat_id, part, **kwargs)
            time.sleep(1)

def check_membership(user_id):
    try:
        member = bot.get_chat_member(TELEGRAM_CHANNEL_ID, user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception:
        return False

def send_subscription_message(chat_id):
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    btn_youtube = telebot.types.InlineKeyboardButton("اشترك في قناة اليوتيوب 🔴", url=YOUTUBE_CHANNEL_URL)
    btn_telegram = telebot.types.InlineKeyboardButton("اشترك في قناة التليجرام 🔵", url=f"https://t.me/{TELEGRAM_CHANNEL_ID.replace('@', '')}")
    btn_check = telebot.types.InlineKeyboardButton("✅ تحققت من الاشتراك", callback_data="check_subscription")
    markup.add(btn_youtube, btn_telegram, btn_check)
    bot.send_message(chat_id, 
                     "🚫 *عذراً، يجب عليك الاشتراك في القنوات التالية أولاً لاستخدام البوت:*",
                     reply_markup=markup, parse_mode="Markdown")

# --- دوال عرض القوائم والواجهات ---
def send_help_message(chat_id, message_id):
    help_text = """
        🎓 *Univy - مساعدك الجامعي الذكي*

        مرحبًا بك في *Univy*، البوت الذكي المصمم لمساعدتك في دراستك الجامعية باستخدام الذكاء الاصطناعي 🤖📚
        ---
        📌 *تعليمات الاستخدام:*
        ✅ يمكنك استخدام Univy في:
        - البحث داخل كتب المنهج الخاصة بك
        - طرح أسئلة علمية أو دراسية مفيدة فقط
        🚫 ممنوع تمامًا:
        - إرسال أسئلة بلا هدف أو غير مفيدة
        - استخدام البوت في أسئلة تتعلق بالغش أو أي نشاط غير قانوني
        - محاولة إساءة استخدام البوت بأي شكل
        ⚠️ قد يتم حظر المستخدمين المخالفين تلقائيًا
        ---
        ⚙️ *مميزات Univy:*
        - البحث الذكي داخل كتب المنهج (PDF)
        - استخدام واجهة بسيطة وسريعة
        ---
        👨‍💻 *تم تطوير Univy بواسطة:*
        *Eng. Ahmed Dowedar*
        📬 للتواصل أو الاستفسار: [@engahmeddowedar](https://t.me/engahmeddowedar)
        ---
        💡 شكرًا لاستخدامك Univy – نتمنى لك تجربة دراسية أسهل وأكثر ذكاءً!
        """
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("⬅️ العودة إلى القائمة الرئيسية", callback_data="main_menu"))
    try:
        bot.edit_message_text(help_text, chat_id, message_id, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        print(f"Error editing help message: {e}")

# --- [تعديل مقترح] إصلاح دالة القائمة الرئيسية بشكل أفضل ---
def show_main_menu(chat_id, message_id):
    """
    يعرض القائمة الرئيسية. يحاول تعديل رسالة موجودة، 
    وإذا فشل (لأن الرسالة قديمة جداً أو بسبب خطأ من تيليجرام)، 
    فإنه يرسل رسالة جديدة ويحاول حذف القديمة لتنظيف المحادثة.
    """
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    btn_general = telebot.types.InlineKeyboardButton("🤖 بحث عام (AI)", callback_data="search_general")
    btn_books = telebot.types.InlineKeyboardButton("📚 بحث في المصادر", callback_data="search_books")
    btn_help = telebot.types.InlineKeyboardButton("📜 مساعدة وإرشادات", callback_data="show_help")
    btn_feedback = telebot.types.InlineKeyboardButton("📝 اقتراح أو مشكلة", callback_data="send_feedback")
    btn_add_book = telebot.types.InlineKeyboardButton("➕ إضافة كتاب", callback_data="add_book")
    btn_customize = telebot.types.InlineKeyboardButton("✨ تخصيص البوت", callback_data="customize_bot")
    
    markup.add(btn_general, btn_books)
    markup.add(btn_feedback, btn_add_book)
    markup.add(btn_help, btn_customize)
    
    text = "✅ أهلاً بك من جديد!\n\nاختر من فضلك ما تريد فعله:"
    
    try:
        # المحاولة الأولى: تعديل الرسالة الحالية، وهو الأسلوب الأفضل والأسرع
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
    except Exception as e:
        # إذا فشل التعديل، يتم طباعة الخطأ للمتابعة دون إيقاف البوت
        print(f"Error editing message {message_id}, falling back to sending a new one. Error: {e}")
        
        # الخطة البديلة: إرسال رسالة جديدة بالقائمة
        bot.send_message(chat_id, text, reply_markup=markup)
        
        try:
            # ومحاولة حذف الرسالة القديمة التي سببت المشكلة لتنظيف الشات
            bot.delete_message(chat_id, message_id)
        except Exception as e_del:
            # في حال فشل الحذف أيضاً (قد يحدث إذا لم يكن للبوت صلاحية الحذف أو الرسالة قديمة جداً)
            print(f"Also failed to delete the problematic message {message_id}. Error: {e_del}")


def show_book_list(chat_id, message_id):
    text = "⏳ جارٍ جلب قائمة الكتب..."
    try:
        bot.edit_message_text(text, chat_id, message_id)
    except Exception:
        msg = bot.send_message(chat_id, text)
        message_id = msg.message_id

    books = list_books()
    if not books:
        bot.edit_message_text("عذرًا، لم أجد كتبًا في المجلد المخصص حالياً.", chat_id, message_id)
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("⬅️ العودة إلى القائمة الرئيسية", callback_data="main_menu"))
        bot.edit_message_reply_markup(chat_id, message_id, reply_markup=markup)
        return

    users = load_users()
    user_data = users.get(str(chat_id), {})
    user_data['available_books'] = books
    save_users(users)
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    for book in books: markup.add(telebot.types.InlineKeyboardButton(book['name'], callback_data=f"book:{book['id']}"))
    markup.add(telebot.types.InlineKeyboardButton("⬅️ العودة إلى القائمة الرئيسية", callback_data="main_menu"))
    bot.edit_message_text("اختر الكتاب الذي تريد البحث فيه:", chat_id, message_id, reply_markup=markup)

# --- المعالجات الرئيسية (Handlers) ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = str(message.chat.id)
    log_interaction(message.from_user, "بدء استخدام البوت", "/start")
    if check_membership(message.from_user.id):
        users = load_users()
        user_data = users.get(chat_id, {})
        user_data['state'] = 'main_menu'
        if 'chat_history' not in user_data:
            user_data['chat_history'] = []
            log_interaction(message.from_user, "تسجيل مستخدم جديد")
        save_users({**users, chat_id: user_data})
        # استخدام نمط "إرسال ثم تعديل" لعرض القائمة الرئيسية بسلاسة
        msg_for_menu = bot.send_message(chat_id, "أهلاً بك! جارٍ تحميل القائمة...", reply_markup=telebot.types.ReplyKeyboardRemove())
        show_main_menu(chat_id, msg_for_menu.message_id)
    else:
        send_subscription_message(message.chat.id)

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    chat_id = str(call.message.chat.id)
    action = call.data
    log_interaction(call.from_user, "ضغط زر", f"`{action}`")
    
    bot.answer_callback_query(call.id)

    if action == 'check_subscription':
        if check_membership(call.from_user.id):
            bot.delete_message(chat_id, call.message.message_id)
            mock_message = telebot.types.Message(message_id=0, from_user=call.from_user, date=int(time.time()), chat=call.message.chat, content_type='text', options={}, json_string='')
            handle_start(mock_message)
        else:
            bot.answer_callback_query(call.id, "❌ لم تشترك بعد.", show_alert=True)
        return
        
    if not check_membership(call.from_user.id):
        send_subscription_message(chat_id)
        return
        
    users = load_users()
    user_data = users.get(chat_id, {})
    
    if action == 'main_menu': 
        show_main_menu(chat_id, call.message.message_id)
    elif action == 'show_help': 
        send_help_message(chat_id, call.message.message_id)
    elif action == 'customize_bot':
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("⬅️ العودة إلى القائمة الرئيسية", callback_data="main_menu"))
        text = "⚙️ هذه الميزة قيد التطوير وستتوفر قريباً..."
        bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=markup)
    else:
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        reply_markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
        
        if action == 'send_feedback':
            user_data['state'] = 'awaiting_feedback'
            reply_markup.add(telebot.types.KeyboardButton("❌ إلغاء"))
            bot.send_message(chat_id, "اكتب الآن اقتراحك أو وصف المشكلة:", reply_markup=reply_markup)
        elif action == 'add_book':
            user_data['state'] = 'awaiting_book_file'
            reply_markup.add(telebot.types.KeyboardButton("❌ إلغاء"))
            bot.send_message(chat_id, "يرجى إرسال الكتاب الآن بصيغة PDF أو TXT.", reply_markup=reply_markup)
        elif action == "search_general":
            user_data['state'] = 'general_chat'
            user_data['chat_history'] = []
            reply_markup.add(telebot.types.KeyboardButton("⬅️ العودة إلى القائمة الرئيسية"))
            bot.send_message(chat_id, "تم تفعيل وضع البحث العام. تفضل بسؤالك.", reply_markup=reply_markup)
        elif action == "search_books":
            user_data['state'] = 'Browse_books'
            show_book_list(chat_id, call.message.message_id)
        elif action.startswith("book:"):
            try:
                _, book_id = action.split(':', 1)
                available_books = user_data.get('available_books', [])
                book_name = next((b['name'] for b in available_books if b['id'] == book_id), "غير معروف")
                
                msg = bot.send_message(chat_id, "...", reply_markup=telebot.types.ReplyKeyboardRemove())
                bot.delete_message(chat_id, msg.message_id)
                
                indexing_msg = bot.send_message(chat_id, f"⏳ جارٍ التحضير لفهرسة '{book_name}'...")
                result = index_book(book_id, book_name, indexing_msg)
                
                if result == "indexed":
                    user_data.update({'state': 'book_chat', 'selected_book_id': book_id, 'selected_book_name': book_name})
                    user_data.pop('available_books', None)
                    reply_markup.add(telebot.types.KeyboardButton("⬅️ العودة إلى قائمة الكتب"))
                    bot.edit_message_text(f"✅ تم تجهيز كتاب '{book_name}' بنجاح.\nيمكنك الآن طرح أسئلتك حوله.", chat_id, indexing_msg.message_id)
                    bot.send_message(chat_id, "استخدم الكيبورد في الأسفل للعودة للقائمة الرئيسية عند الانتهاء.", reply_markup=reply_markup)
                else:
                    bot.edit_message_text(f"حدث خطأ أثناء تجهيز الكتاب: {result}", chat_id, indexing_msg.message_id)
                    show_main_menu(chat_id, indexing_msg.message_id)
            except Exception as e:
                bot.send_message(chat_id, f"حدث خطأ في معالجة اختيارك: {e}")
                show_main_menu(chat_id, call.message.message_id)
        save_users({**users, chat_id: user_data})

@bot.message_handler(content_types=['document'])
def handle_document(message):
    chat_id = str(message.chat.id)
    users = load_users()
    user_data = users.get(chat_id)

    if user_data and user_data.get('state') == 'awaiting_book_file':
        document = message.document
        if not (document.file_name.lower().endswith('.pdf') or document.file_name.lower().endswith('.txt')):
            bot.reply_to(message, "❌ صيغة الملف غير مدعومة. يرجى إرسال ملف PDF أو TXT فقط.")
            return

        bot.reply_to(message, "✅ تم استلام الملف. جارٍ إرساله للمراجعة...")
        send_book_to_dev(message.from_user, document)
        user_data['state'] = 'main_menu'
        save_users(users)
        bot.send_message(chat_id, "شكرًا لمساهمتك! سيتم مراجعة الكتاب وإضافته في أقرب وقت. 🙏")
        msg_for_menu = bot.send_message(chat_id, "جاري العودة...", reply_markup=telebot.types.ReplyKeyboardRemove())
        show_main_menu(chat_id, msg_for_menu.message_id)

@bot.message_handler(func=lambda m: True)
def handle_user_message(message):
    chat_id = str(message.chat.id)
    if not check_membership(message.from_user.id):
        send_subscription_message(chat_id)
        return
    
    users = load_users()
    user_data = users.get(chat_id)
    if not user_data:
        handle_start(message)
        return
        
    if message.text in ["⬅️ العودة إلى القائمة الرئيسية", "❌ إلغاء", "⬅️ العودة إلى قائمة الكتب"]:
        log_interaction(message.from_user, "العودة للقائمة الرئيسية / إلغاء")
        user_data['state'] = 'main_menu'
        save_users(users)
        msg_for_menu = bot.send_message(chat_id, "جاري العودة للقائمة الرئيسية...", reply_markup=telebot.types.ReplyKeyboardRemove())
        show_main_menu(chat_id, msg_for_menu.message_id)
        return

    user_state = user_data.get('state')
    
    if user_state == 'awaiting_feedback':
        send_feedback_to_dev(message.from_user, message.text)
        bot.send_message(chat_id, "✅ شكرًا لك! تم استلام رسالتك بنجاح وجارِ مراجعتها.")
        user_data['state'] = 'main_menu'
        save_users(users)
        msg_for_menu = bot.send_message(chat_id, "جاري العودة...", reply_markup=telebot.types.ReplyKeyboardRemove())
        show_main_menu(chat_id, msg_for_menu.message_id)
        return

    if user_state in ['general_chat', 'book_chat']:
        current_time = time.time()
        last_query_time = user_data.get('last_query_time', 0)
        if current_time - last_query_time < COOLDOWN_SECONDS:
            remaining_time = round(COOLDOWN_SECONDS - (current_time - last_query_time))
            bot.send_message(chat_id, f"⏳ الرجاء الانتظار {remaining_time} ثانية.")
            return
        user_data['last_query_time'] = current_time
        
        processing_msg = bot.send_message(chat_id, "⏳ جارِ معالجة طلبك...")
        context = ""
        
        if user_state == 'book_chat':
            book_id = user_data.get('selected_book_id')
            if not book_id:
                bot.edit_message_text("حدث خطأ، لم يتم تحديد كتاب.", chat_id, processing_msg.message_id)
                return
            context = retrieve_relevant_context(message.text, book_id)
            if "خطأ:" in context or not context:
                bot.edit_message_text(context or "لم أجد معلومات ذات صلة بسؤالك.", chat_id, processing_msg.message_id)
                return
                
        response = send_to_gemini(message.from_user, message.text, user_data.get("chat_history", []), context)
        bot.delete_message(chat_id, processing_msg.message_id)
        send_long_message(chat_id, response, parse_mode="Markdown")
        
        if "حدثت مشكلة" not in response and "خطأ" not in response:
            chat_history = user_data.get("chat_history", [])
            chat_history.append({"role": "user", "parts": [{"text": message.text}]})
            chat_history.append({"role": "model", "parts": [{"text": response}]})
            user_data["chat_history"] = chat_history[-10:]
        save_users(users)
    else:
        if user_data.get('state') == 'awaiting_book_file':
             bot.send_message(chat_id, "يرجى إرسال ملف الكتاب وليس رسالة نصية. أو اضغط على زر '❌ إلغاء' للعودة.")
        else:
            msg_for_menu = bot.send_message(chat_id, "...")
            bot.delete_message(chat_id, msg_for_menu.message_id)
            # Send a new message to show the menu on, preventing edit errors.
            new_msg_for_menu = bot.send_message(chat_id, "يبدو أنك لست في وضع محادثة. سأعرض لك القائمة.")
            show_main_menu(chat_id, new_msg_for_menu.message_id)

if __name__ == "__main__":
    print(f"Starting Univy Bot - Final Version... [ Shirbin - {time.strftime('%Y-%m-%d %H:%M:%S')} ]")
    bot.infinity_polling()
