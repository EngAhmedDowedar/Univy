import os
import telebot
import json
import requests
import time
from threading import Lock
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import io
import fitz  # PyMuPDF
import logging
from datetime import datetime, timedelta
import sys

# ---------------------- إعداد التسجيل (Logging) ----------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ---------------------- إعدادات البوت ----------------------
class BotConfig:
    def __init__(self):
        # إعدادات Telegram
        self.BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '7739465299:AAGOANXaygnCyjmInyAfpfOYoepE2W8_m1M')
        self.LOG_BOT_TOKEN = os.getenv('LOG_BOT_TOKEN', '8141683551:AAELKx91_D5coF3X5Amnv_d44REWh3gkDxc')
        self.LOG_CHAT_ID = os.getenv('LOG_CHAT_ID', '2029139293')
        self.ADMINS = [2029139293]  # قائمة المشرفين
        
        # إعدادات Gemini API
        self.API_KEY = os.getenv('GEMINI_API_KEY', 'AIzaSyBGgDeRu83fMID-rCFDQJRDywhqCO1cRPE')
        self.MODEL = 'gemini-1.5-flash'
        self.BASE_URL = f'https://generativelanguage.googleapis.com/v1beta/models/{self.MODEL}:generateContent?key={self.API_KEY}'
        
        # إعدادات Google Drive
        self.SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
        self.SERVICE_ACCOUNT_FILE = 'credentials.json'
        self.DRIVE_FOLDER_ID = '1767thuB9M0Zj9t1n1-lTsoFAhV68XF9r'
        
        # إعدادات الاشتراك الإجباري
        self.YOUTUBE_CHANNEL_URL = 'https://www.youtube.com/@DowedarTech'
        self.TELEGRAM_CHANNEL_ID = '@dowedar_tech'
        
        # إعدادات الذاكرة المؤقتة
        self.CACHE_EXPIRY = timedelta(hours=1)
        
        # التحقق من المتغيرات الأساسية
        if not all([self.BOT_TOKEN, self.API_KEY]):
            raise ValueError("يجب تعيين متغيرات البيئة المطلوبة (BOT_TOKEN, API_KEY)!")

config = BotConfig()
bot = telebot.TeleBot(config.BOT_TOKEN)

# ---------------------- نظام الذاكرة المؤقتة ----------------------
class CacheManager:
    def __init__(self):
        self.cache = {}
        self.lock = Lock()

    def get(self, key):
        with self.lock:
            item = self.cache.get(key)
            if item and datetime.now() < item['expiry']:
                return item['data']
            return None

    def set(self, key, data, expiry=None):
        with self.lock:
            if expiry is None:
                expiry = datetime.now() + config.CACHE_EXPIRY
            self.cache[key] = {
                'data': data,
                'expiry': expiry
            }

cache_manager = CacheManager()

# ---------------------- نظام إدارة المستخدمين ----------------------
class UserManager:
    def __init__(self):
        self.lock = Lock()
        self.file_path = "users.json"

    def load_users(self):
        with self.lock:
            try:
                with open(self.file_path, "r", encoding='utf-8') as f:
                    return json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                return {}
            except Exception as e:
                logger.error(f"Error loading users: {e}")
                return {}

    def save_users(self, data):
        with self.lock:
            try:
                with open(self.file_path, "w", encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
            except Exception as e:
                logger.error(f"Error saving users: {e}")

    def get_user(self, chat_id):
        users = self.load_users()
        return users.get(str(chat_id)), users

    def update_user(self, chat_id, updates):
        users = self.load_users()
        user = users.setdefault(str(chat_id), {'state': 'main_menu', 'chat_history': []})
        user.update(updates)
        self.save_users(users)

user_manager = UserManager()

# ---------------------- خدمة Google Drive ----------------------
class DriveService:
    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._service = None
        return cls._instance

    @property
    def service(self):
        if self._service is None:
            try:
                creds = service_account.Credentials.from_service_account_file(
                    config.SERVICE_ACCOUNT_FILE, scopes=config.SCOPES)
                self._service = build('drive', 'v3', credentials=creds)
            except Exception as e:
                logger.error(f"Error setting up Drive service: {e}")
        return self._service

    def list_books(self):
        service = self.service
        if not service:
            return []
        
        try:
            results = service.files().list(
                q=f"'{config.DRIVE_FOLDER_ID}' in parents and trashed=false",
                fields="nextPageToken, files(id, name)").execute()
            return results.get('files', [])
        except Exception as e:
            logger.error(f"Error fetching book list: {e}")
            return []

drive_service = DriveService()

# ---------------------- نظام الاشتراك الإجباري ----------------------
def check_membership(user_id):
    try:
        member = bot.get_chat_member(config.TELEGRAM_CHANNEL_ID, user_id)
        return member.status in ['creator', 'administrator', 'member']
    except Exception as e:
        logger.error(f"Error checking membership for user {user_id}: {e}")
        return False

def send_subscription_message(chat_id):
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    btn_youtube = telebot.types.InlineKeyboardButton(
        "اشترك في قناة اليوتيوب 🔴", 
        url=config.YOUTUBE_CHANNEL_URL
    )
    btn_telegram = telebot.types.InlineKeyboardButton(
        "اشترك في قناة التليجرام 🔵", 
        url=f"https://t.me/{config.TELEGRAM_CHANNEL_ID.replace('@', '')}"
    )
    btn_check = telebot.types.InlineKeyboardButton(
        "✅ تحققت من الاشتراك", 
        callback_data="check_subscription"
    )
    markup.add(btn_youtube, btn_telegram, btn_check)
    
    bot.send_message(
        chat_id, 
        "🛑 *عذراً، يجب عليك الاشتراك في القنوات التالية أولاً لاستخدام البوت:*\n\n"
        "هذا يساعدنا على الاستمرار وتقديم المزيد من المحتوى المفيد. شكراً لدعمك! 🙏",
        reply_markup=markup, 
        parse_mode="Markdown"
    )

# ---------------------- واجهات المستخدم المحسنة ----------------------
def delete_previous_message(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

def show_main_menu(chat_id, previous_message_id=None):
    if previous_message_id:
        delete_previous_message(chat_id, previous_message_id)
    
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    btn_general = telebot.types.InlineKeyboardButton("🤖 بحث عام (AI)", callback_data="search_general")
    btn_books = telebot.types.InlineKeyboardButton("📚 بحث في المصادر والكتب", callback_data="search_books")
    btn_help = telebot.types.InlineKeyboardButton("❓ المساعدة والإرشادات", callback_data="help")
    btn_feedback = telebot.types.InlineKeyboardButton("📩 إرسال اقتراح أو مشكلة", callback_data="feedback")
    markup.add(btn_general, btn_books, btn_help, btn_feedback)
    
    bot.send_message(
        chat_id,
        "✅ *مرحباً بك في بوت الذكاء الاصطناعي المجاني!*\n\nاختر من فضلك نوع البحث الذي تريده:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

def show_help_menu(chat_id, previous_message_id=None):
    if previous_message_id:
        delete_previous_message(chat_id, previous_message_id)
    
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
    btn_feedback = telebot.types.InlineKeyboardButton("📩 إرسال اقتراح أو مشكلة", callback_data="feedback")
    btn_back = telebot.types.InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_menu")
    markup.add(btn_feedback, btn_back)
    
    bot.send_message(
        chat_id,
        help_text,
        reply_markup=markup,
        parse_mode="Markdown"
    )

def ask_for_feedback(chat_id, previous_message_id=None):
    if previous_message_id:
        delete_previous_message(chat_id, previous_message_id)
    
    user_manager.update_user(chat_id, {'state': 'awaiting_feedback'})
    
    feedback_msg = """
📝 *إرسال اقتراح أو مشكلة*
يرجى كتابة اقتراحك أو المشكلة التي تواجهها وسيتم إرسالها إلى فريق الدعم.

يمكنك كتابة أي ملاحظات لديك حول:
- مشاكل في التشغيل
- اقتراحات للتطوير
- أي استفسارات أخرى
"""
    
    markup = telebot.types.InlineKeyboardMarkup()
    btn_back = telebot.types.InlineKeyboardButton("🔙 العودة دون إرسال", callback_data="back_to_menu")
    markup.add(btn_back)
    
    bot.send_message(
        chat_id,
        feedback_msg,
        reply_markup=markup,
        parse_mode="Markdown"
    )

def show_search_interface(chat_id, is_book_search=False, book_name=None, previous_message_id=None):
    if previous_message_id:
        delete_previous_message(chat_id, previous_message_id)
    
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    
    if is_book_search and book_name:
        btn_new_chat = telebot.types.InlineKeyboardButton("🆕 بدء محادثة جديدة حول هذا الكتاب", callback_data=f"new_book_chat:{book_name}")
        markup.add(btn_new_chat)
    else:
        btn_new_chat = telebot.types.InlineKeyboardButton("🆕 بدء محادثة جديدة", callback_data="new_general_chat")
        markup.add(btn_new_chat)
    
    btn_back = telebot.types.InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_menu")
    markup.add(btn_back)
    
    if is_book_search:
        text = f"✅ تم تحميل كتاب '{book_name}'. يمكنك الآن طرح أسئلتك حول محتواه.\n\nيمكنك بدء محادثة جديدة أو العودة للقائمة الرئيسية."
    else:
        text = "تم تفعيل وضع البحث العام. تفضل بسؤالك.\n\nيمكنك بدء محادثة جديدة أو العودة للقائمة الرئيسية."
    
    bot.send_message(
        chat_id,
        text,
        reply_markup=markup,
        parse_mode="Markdown"
    )

# ---------------------- معالجة الأوامر الأساسية ----------------------
@bot.message_handler(commands=['start', 'help', 'menu'])
def handle_start(message):
    chat_id = str(message.chat.id)
    if not check_membership(message.from_user.id):
        send_subscription_message(chat_id)
        return
    
    user_manager.update_user(chat_id, {'state': 'main_menu'})
    show_main_menu(chat_id)

@bot.message_handler(commands=['admin'], func=lambda m: m.from_user.id in config.ADMINS)
def handle_admin(message):
    chat_id = message.chat.id
    bot.send_message(chat_id, "مرحباً يا مشرف! 👨‍💼")

# ---------------------- معالجة الأزرار المحسنة ----------------------
@bot.callback_query_handler(func=lambda call: call.data in [
    'check_subscription', 'back_to_menu', 
    'help', 'feedback', 
    'search_general', 'search_books',
    'new_general_chat'
])
def handle_main_callbacks(call):
    chat_id = str(call.message.chat.id)
    
    if call.data == 'check_subscription':
        bot.answer_callback_query(call.id, "جارٍ التحقق...")
        if check_membership(call.from_user.id):
            delete_previous_message(chat_id, call.message.message_id)
            handle_start(call.message)
        else:
            bot.answer_callback_query(call.id, "❌ لم تشترك بعد. يرجى الاشتراك ثم المحاولة مجدداً.")
        return
    
    if call.data == 'back_to_menu':
        delete_previous_message(chat_id, call.message.message_id)
        handle_start(call.message)
        return
    
    if not check_membership(call.from_user.id):
        send_subscription_message(chat_id)
        return
    
    if call.data == 'help':
        show_help_menu(chat_id, call.message.message_id)
    elif call.data == 'feedback':
        ask_for_feedback(chat_id, call.message.message_id)
    elif call.data == 'search_general':
        user_manager.update_user(chat_id, {
            'state': 'general_chat',
            'chat_history': [],
            'selected_book_id': None,
            'selected_book_name': None
        })
        show_search_interface(chat_id, False, None, call.message.message_id)
    elif call.data == 'search_books':
        delete_previous_message(chat_id, call.message.message_id)
        loading_msg = bot.send_message(chat_id, "⏳ جارٍ جلب قائمة الكتب...")
        books = drive_service.list_books()
        if not books:
            bot.edit_message_text("عذرًا، لم أجد كتبًا في المجلد المخصص.", chat_id, loading_msg.message_id)
            return
        
        user_manager.update_user(chat_id, {'available_books': books})
        
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        for book in books:
            markup.add(telebot.types.InlineKeyboardButton(
                book['name'], 
                callback_data=f"book:{book['id']}"
            ))
        btn_back = telebot.types.InlineKeyboardButton("🔙 العودة للقائمة الرئيسية", callback_data="back_to_menu")
        markup.add(btn_back)
        
        bot.edit_message_text(
            "اختر الكتاب الذي تريد البحث فيه:",
            chat_id, 
            loading_msg.message_id, 
            reply_markup=markup
        )
    elif call.data == 'new_general_chat':
        user_manager.update_user(chat_id, {
            'state': 'general_chat',
            'chat_history': []
        })
        bot.answer_callback_query(call.id, "تم بدء محادثة جديدة")
        show_search_interface(chat_id, False, None, call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith(('book:', 'new_book_chat:')))
def handle_book_actions(call):
    chat_id = str(call.message.chat.id)
    
    if call.data.startswith('book:'):
        delete_previous_message(chat_id, call.message.message_id)
        
        try:
            _, book_id = call.data.split(':', 1)
            user, users = user_manager.get_user(chat_id)
            available_books = user.get('available_books', [])
            book_name = next((b['name'] for b in available_books if b['id'] == book_id), None)

            if not book_name:
                bot.send_message(chat_id, "حدث خطأ، لم يتم العثور على الكتاب. حاول مرة أخرى.")
                return

            user_manager.update_user(chat_id, {
                'state': 'book_chat',
                'chat_history': [],
                'selected_book_id': book_id,
                'selected_book_name': book_name,
                'available_books': None
            })
            
            loading_msg = bot.send_message(
                chat_id,
                f"⏳ يتم الآن تحميل ومعالجة كتاب '{book_name}'..."
            )
            
            content = get_book_content(book_id, book_name)
            if "خطأ:" in content:
                bot.edit_message_text(content, chat_id, loading_msg.message_id)
            else:
                show_search_interface(chat_id, True, book_name, loading_msg.message_id)
        except Exception as e:
            logger.error(f"Error in book selection: {e}")
            bot.send_message(chat_id, "حدث خطأ في معالجة اختيارك. يرجى المحاولة لاحقاً.")
    
    elif call.data.startswith('new_book_chat:'):
        delete_previous_message(chat_id, call.message.message_id)
        book_name = call.data.split(':', 1)[1]
        user, users = user_manager.get_user(chat_id)
        book_id = user.get('selected_book_id')
        
        user_manager.update_user(chat_id, {
            'chat_history': []
        })
        
        bot.answer_callback_query(call.id, f"تم بدء محادثة جديدة حول كتاب {book_name}")
        show_search_interface(chat_id, True, book_name)

# ---------------------- نظام البحث والرد ----------------------
def send_to_gemini(prompt, chat_history=None, context=""):
    headers = {'Content-Type': 'application/json'}
    
    final_prompt = prompt
    if context:
        final_prompt = (
            f"أجب على السؤال التالي بناءً على النص المرفق فقط. إذا كانت الإجابة غير موجودة في النص، قل 'الإجابة غير متوفرة في المصدر'.\n\n"
            f"--- النص المرجعي ---\n{context[:15000]}\n--- نهاية النص ---\n\n"
            f"السؤال: {prompt}"
        )

    contents = chat_history or []
    contents.append({"role": "user", "parts": [{"text": final_prompt}]})
    
    data = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 4096
        }
    }

    try:
        response = requests.post(config.BASE_URL, headers=headers, json=data, timeout=90)
        response.raise_for_status()
        result = response.json()
        
        if 'candidates' in result and result['candidates']:
            if 'content' in result['candidates'][0] and 'parts' in result['candidates'][0]['content']:
                return result['candidates'][0]['content']['parts'][0]['text']
        return "لم أتمكن من توليد رد. يرجى المحاولة مرة أخرى."
    except requests.exceptions.Timeout:
        return "تجاوز الوقت المحدد للطلب. يرجى المحاولة مرة أخرى لاحقاً."
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return "حدثت مشكلة في الاتصال بالخادم. يرجى المحاولة لاحقًا."

def get_book_content(file_id, file_name):
    cached = cache_manager.get(f"book_{file_id}")
    if cached:
        logger.info(f"Retrieved book '{file_name}' from cache")
        return cached
    
    service = drive_service.service
    if not service:
        return "خطأ: لا يمكن الاتصال بخدمة Google Drive."
    
    try:
        request = service.files().get_media(fileId=file_id)
        file_io = io.BytesIO()
        downloader = MediaIoBaseDownload(file_io, request)
        
        while True:
            status, done = downloader.next_chunk()
            if done:
                break
        
        file_io.seek(0)
        text = ""
        
        if file_name.lower().endswith('.pdf'):
            with fitz.open(stream=file_io, filetype="pdf") as doc:
                text = "".join(page.get_text() for page in doc)
        elif file_name.lower().endswith('.txt'):
            text = file_io.read().decode('utf-8')
        else:
            return f"خطأ: صيغة الملف '{file_name}' غير مدعومة."
        
        cache_manager.set(f"book_{file_id}", text)
        logger.info(f"Processed and cached book '{file_name}'")
        return text
    except Exception as e:
        logger.error(f"Error processing book '{file_name}': {e}")
        return f"حدث خطأ أثناء محاولة الوصول للكتاب: {file_name}"

def send_feedback_to_logs(message):
    user_info = f"المستخدم: @{message.from_user.username} ({message.from_user.id})"
    feedback_text = f"""
📬 *اقتراح جديد من مستخدم*
{user_info}
📝 *الرسالة:*
{message.text}
"""
    
    try:
        bot.send_message(
            config.LOG_CHAT_ID,
            feedback_text,
            parse_mode="Markdown"
        )
        logger.info(f"New feedback from {message.from_user.id}: {message.text}")
    except Exception as e:
        logger.error(f"Failed to send feedback to logs: {e}")

# ---------------------- معالجة الرسائل ----------------------
@bot.message_handler(func=lambda m: True)
def handle_user_message(message):
    chat_id = str(message.chat.id)
    if not check_membership(message.from_user.id):
        send_subscription_message(chat_id)
        return
    
    user, users = user_manager.get_user(chat_id)
    if not user:
        handle_start(message)
        return
    
    # حالة انتظار الاقتراح
    if user.get('state') == 'awaiting_feedback':
        send_feedback_to_logs(message)
        user_manager.update_user(chat_id, {'state': 'main_menu'})
        bot.send_message(chat_id, "شكراً لك! تم إرسال اقتراحك إلى فريق الدعم.")
        show_main_menu(chat_id)
        return
    
    # باقي معالجة الرسائل العادية
    processing_msg = bot.send_message(chat_id, "⏳ جارِ معالجة طلبك...")
    
    context = ""
    if user.get('state') == 'book_chat':
        book_id = user.get('selected_book_id')
        book_name = user.get('selected_book_name')
        if not book_id:
            bot.edit_message_text(
                "حدث خطأ، لم يتم تحديد كتاب. يرجى العودة للقائمة الرئيسية /start",
                chat_id,
                processing_msg.message_id
            )
            return
        
        context = get_book_content(book_id, book_name)
        if "خطأ:" in context:
            bot.edit_message_text(context, chat_id, processing_msg.message_id)
            return
    
    response = send_to_gemini(
        message.text,
        user.get("chat_history", []),
        context
    )
    
    bot.delete_message(chat_id, processing_msg.message_id)
    bot.send_message(chat_id, response, parse_mode="Markdown")
    
    new_history = user.get("chat_history", [])
    new_history.append({"role": "user", "parts": [{"text": message.text}]})
    new_history.append({"role": "model", "parts": [{"text": response}]})
    
    user_manager.update_user(chat_id, {
        "chat_history": new_history[-10:]  
    })

if __name__ == "__main__":
    logger.info(f"Starting Bot... [ {time.strftime('%Y-%m-%d %H:%M:%S')} ]")
    try:
        bot.infinity_polling()
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        time.sleep(60)
        os.execv(__file__, sys.argv)