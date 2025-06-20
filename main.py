# -*- coding: utf-8 -*-

# ==============================================================================
#  مكتبات أساسية ومتغيرات البيئة
# ==============================================================================
import os
import json
import re
import time
import io
from threading import Lock
from itertools import cycle

# تحميل المتغيرات من ملف .env (يجب أن يكون في نفس المجلد)
from dotenv import load_dotenv
load_dotenv()

# --- مكتبات أساسية للبوت والخدمات ---
import telebot # مكتبة التليجرام
import requests # لإجراء طلبات HTTP
import fitz  # PyMuPDF لمعالجة ملفات PDF

# --- مكتبات Google Drive API ---
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# --- مكتبات المقارنة الذكية (Fuzzy Matching) ---
from fuzzywuzzy import fuzz
from fuzzywuzzy import process

# ==============================================================================
#  الإعدادات والمتغيرات العامة (Constants)
# ==============================================================================

# --- إعدادات البوت واللوجات ---
LOG_BOT_TOKEN = os.getenv('LOG_BOT_TOKEN')
LOG_CHAT_ID = os.getenv('LOG_CHAT_ID')
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
API_KEYS_STRING = os.getenv('API_KEYS')

# التحقق من وجود المتغيرات المطلوبة لضمان عمل البوت
required_vars = {
    'LOG_BOT_TOKEN': LOG_BOT_TOKEN,
    'LOG_CHAT_ID': LOG_CHAT_ID,
    'TELEGRAM_BOT_TOKEN': BOT_TOKEN,
    'API_KEYS': API_KEYS_STRING
}
missing_vars = [name for name, value in required_vars.items() if not value]
if missing_vars:
    print(f"خطأ فادح: المتغيرات التالية مفقودة في ملف .env: {', '.join(missing_vars)}")
    raise ValueError("أحد متغيرات البيئة المطلوبة غير موجود!")

# ==============================================================================
#  إنشاء كائن البوت الرئيسي (هذا هو المكان الصحيح)
# ==============================================================================
bot = telebot.TeleBot(BOT_TOKEN)
# ==============================================================================


# --- إعدادات Gemini API ---
API_KEYS = [key.strip() for key in API_KEYS_STRING.split(',')]
api_key_cycler = cycle(API_KEYS) # لتبديل مفاتيح API وتوزيع الضغط
MODEL = 'gemini-1.5-flash'

# --- إعدادات Google Drive API ---
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
SERVICE_ACCOUNT_FILE = 'credentials.json' # يجب وضع ملف الصلاحيات هنا
DRIVE_FOLDER_ID = os.getenv('DRIVE_FOLDER_ID', '1767thuB9M0Zj9t1n1-lTsoFAhV68XF9r') # !<-- هام: استبدل بالآي دي الخاص بمجلدك

# --- إعدادات الاشتراك الإجباري ---
YOUTUBE_CHANNEL_URL = os.getenv('YOUTUBE_CHANNEL_URL', 'https://www.youtube.com/@DowedarTech')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID', '@dowedar_tech')

# --- إعدادات تحديد المعدل (Rate Limiting) ---
COOLDOWN_SECONDS = int(os.getenv('COOLDOWN_SECONDS', '15'))

# --- متغيرات عامة وقفل الملفات ---
file_lock = Lock()  # لمنع التضارب عند قراءة/كتابة الملفات من عدة عمليات
book_cache = {}  # لتخزين محتوى الكتب في الذاكرة لتسريع الوصول
book_knowledge_bases = {}  # لتخزين قواعد المعرفة المولّدة للكتب في الذاكرة

# ==============================================================================
#  دوال التعامل مع الملفات (users.json و قواعد المعرفة)
# ==============================================================================

def load_json_file(file_path, default_value):
    """دالة عامة لتحميل ملف JSON مع معالجة الأخطاء."""
    try:
        with file_lock:
            if os.path.exists(file_path):
                with open(file_path, "r", encoding='utf-8') as f:
                    return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"تحذير: لم يتم العثور على ملف {file_path} أو أنه تالف. سيتم استخدام القيمة الافتراضية. الخطأ: {e}")
    except Exception as e:
        print(f"خطأ غير متوقع عند تحميل {file_path}: {e}")
    return default_value

def save_json_file(file_path, data):
    """دالة عامة لحفظ البيانات في ملف JSON."""
    with file_lock:
        try:
            with open(file_path, "w", encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"خطأ في حفظ الملف {file_path}: {e}")

def load_users():
    """تحميل بيانات المستخدمين من users.json."""
    return load_json_file("users.json", {})

def save_users(data):
    """حفظ بيانات المستخدمين في users.json."""
    save_json_file("users.json", data)

def load_book_kb(book_id):
    """تحميل قاعدة المعرفة لكتاب معين من ملف JSON الخاص به."""
    kb_file_path = f"kb_{book_id}.json"
    kb_data = load_json_file(kb_file_path, [])
    book_knowledge_bases[book_id] = kb_data
    if kb_data:
        print(f"تم تحميل قاعدة المعرفة للكتاب {book_id} من الملف.")
    else:
        print(f"لا توجد قاعدة معرفة موجودة للكتاب {book_id}. سيتم توليدها عند الحاجة.")

def save_book_kb(book_id, kb_data):
    """حفظ قاعدة المعرفة لكتاب معين في ملف JSON."""
    kb_file_path = f"kb_{book_id}.json"
    save_json_file(kb_file_path, kb_data)
    print(f"تم حفظ قاعدة المعرفة للكتاب {book_id}.")

def load_all_book_kbs():
    """تحميل جميع قواعد المعرفة الموجودة في المجلد عند بدء تشغيل البوت."""
    print("جاري تحميل قواعد المعرفة الموجودة مسبقاً...")
    kb_files = [f for f in os.listdir('.') if f.startswith('kb_') and f.endswith('.json')]
    for kb_file in kb_files:
        book_id = kb_file.replace('kb_', '').replace('.json', '')
        load_book_kb(book_id)
    print("اكتمل تحميل قواعد المعرفة.")

# ==============================================================================
#  دوال Google Drive
# ==============================================================================

def get_drive_service():
    """إعداد وتجهيز خدمة Google Drive API."""
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        print(f"خطأ في إعداد خدمة Google Drive: {e}")
        return None

def list_books():
    """جلب قائمة الكتب (PDF, TXT) من مجلد Google Drive المحدد."""
    service = get_drive_service()
    if not service: return []
    try:
        query = f"'{DRIVE_FOLDER_ID}' in parents and (mimeType='application/pdf' or mimeType='text/plain') and trashed=false"
        results = service.files().list(q=query, fields="files(id, name)").execute()
        return results.get('files', [])
    except Exception as e:
        print(f"خطأ في جلب قائمة الكتب: {e}")
        return []

# ==============================================================================
#  الدوال الأساسية (Core Logic)
# ==============================================================================

def generate_kb_from_book(book_id, book_name, book_content, from_user):
    """
    تستخدم Gemini لتوليد قاعدة معرفة (KB) من نص الكتاب.
    هذه هي الميزة الأساسية "Auto KB Generation".
    """
    print(f"⚠️ جاري توليد قاعدة المعرفة للكتاب '{book_name}' بواسطة Gemini...")
    content_for_gemini = book_content[:30000] # نأخذ جزء من الكتاب لتجنب تجاوز حدود API

    kb_generation_prompt = f"""
أنت خبير في استخلاص المعلومات. بناءً على النص التالي من كتاب '{book_name}'، قم بتوليد قائمة من الأسئلة الشائعة وإجاباتها المختصرة.
صيغ الإجابات يجب أن تكون واضحة ومنظمة بتنسيق Markdown.
الهدف هو إنشاء قاعدة معرفة للرد على المستخدمين.

أخرج القائمة بصيغة JSON فقط، بهذا الشكل:
```json
[
    {{"standard_question": "سؤال شائع من النص", "answer": "إجابة هذا السؤال"}},
    {{"standard_question": "سؤال آخر من النص", "answer": "إجابة هذا السؤال الآخر"}}
]
```
تأكد من أن الإجابات تستند فقط إلى النص المرفق. لا تقم بتضمين أي نص إضافي، فقط الـ JSON.
يجب أن تحتوي القائمة على 5 إلى 20 سؤال وجواب.
--- بداية النص المرجعي ---
{content_for_gemini}
--- نهاية النص المرجعي ---
"""
    gemini_response = send_to_gemini(from_user, kb_generation_prompt)

    try:
        # استخلاص وتنظيف الـ JSON من رد Gemini
        json_match = re.search(r'```json\n(.*?)\n```', gemini_response, re.DOTALL)
        json_str = json_match.group(1) if json_match else gemini_response
        
        generated_kb = json.loads(json_str)
        
        if isinstance(generated_kb, list):
            # فلترة أي إدخالات غير صالحة
            generated_kb = [entry for entry in generated_kb if "standard_question" in entry and "answer" in entry]
            print(f"✅ تم توليد قاعدة معرفة تحتوي على {len(generated_kb)} إدخال للكتاب '{book_name}'.")
            log_interaction(from_user, "💡 تم توليد KB جديدة", f"للكتاب: {book_name}\nعدد الإدخالات: {len(generated_kb)}")
            return generated_kb
        else:
            raise ValueError("البيانات المستلمة ليست قائمة JSON.")
            
    except (json.JSONDecodeError, ValueError, AttributeError) as e:
        print(f"❌ فشل تحليل JSON من رد Gemini لـ KB الكتاب '{book_name}'. الخطأ: {e}. الرد: {gemini_response[:500]}...")
        log_interaction(from_user, "❌ فشل توليد KB", f"للكتاب: {book_name}\nالرد غير صالح: `{gemini_response[:1000]}`")
        return []

def get_book_content(file_id, file_name, from_user):
    """
    جلب محتوى الكتاب من الذاكرة المؤقتة (Cache) أو تحميله من Google Drive.
    بعد التحميل، تقوم بتوليد قاعدة المعرفة (KB) إذا لم تكن موجودة.
    """
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
            _, done = downloader.next_chunk()
        file_io.seek(0)
        
        text = ""
        if file_name.lower().endswith('.pdf'):
            with fitz.open(stream=file_io, filetype="pdf") as doc:
                if doc.is_encrypted:
                    return f"خطأ: الكتاب '{file_name}' مشفر ولا يمكن قراءته."
                
                text = "".join(page.get_text() for page in doc)
                if not text.strip():
                    return f"عذراً، كتاب '{file_name}' يحتوي على صور فقط أو لا يحتوي على نص قابل للاستخراج."

        elif file_name.lower().endswith('.txt'):
            text = file_io.read().decode('utf-8', errors='ignore')
        
        book_cache[file_id] = text
        print(f"تمت معالجة وتخزين الكتاب '{file_name}' في الكاش.")

        # بعد تحميل كتاب جديد، تحقق من وجود قاعدة المعرفة أو قم بتوليدها
        if file_id not in book_knowledge_bases or not book_knowledge_bases.get(file_id):
            bot.send_message(from_user.id, f"⏳ لأول مرة، جاري تجهيز قاعدة المعرفة لكتاب '{file_name}'. قد يستغرق هذا دقيقة...")
            generated_kb = generate_kb_from_book(file_id, file_name, text, from_user)
            book_knowledge_bases[file_id] = generated_kb
            save_book_kb(file_id, generated_kb)
            bot.send_message(from_user.id, f"✅ تم تجهيز قاعدة المعرفة لكتاب '{file_name}'. يمكنك الآن طرح أسئلتك!")
        
        return text
        
    except Exception as e:
        print(f"خطأ في جلب محتوى الكتاب '{file_name}': {e}")
        return f"حدث خطأ أثناء محاولة الوصول للكتاب: {file_name}"

def escape_markdown_v2(text: str) -> str:
    """نسخة أكثر أمانًا لتهريب أحرف الماركداون V2."""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def log_interaction(from_user, event_type, details=""):
    """إرسال سجلات (logs) إلى قناة تليجرام خاصة لمراقبة أداء البوت."""
    try:
        user_info = (
            f"👤 *المستخدم:*\n"
            f"- الاسم: {from_user.first_name} {from_user.last_name or ''}\n"
            f"- اليوزر: @{from_user.username or 'N/A'}\n"
            f"- الآي دي: `{from_user.id}`"
        )
        log_message = f"📌 *{event_type}*\n\n{user_info}\n\n*التفاصيل:*\n{details}"
        
        # قص الرسالة إذا كانت طويلة جداً
        if len(log_message) > 4096:
            log_message = log_message[:4090] + "\n..."
            
        url = f"https://api.telegram.org/bot{LOG_BOT_TOKEN}/sendMessage"
        params = {'chat_id': LOG_CHAT_ID, 'text': log_message, 'parse_mode': 'Markdown', 'disable_web_page_preview': True}
        requests.post(url, json=params, timeout=10)
    except Exception as e:
        print(f"❌ فشل إرسال اللوج: {e}")

def send_to_gemini(from_user, prompt, chat_history=None, context=""):
    """
    إرسال الطلب إلى Gemini API مع معالجة الأخطاء ومحاولات إعادة الإرسال.
    """
    headers = {'Content-Type': 'application/json'}
    final_prompt = prompt
    if context:
        final_prompt = (
            f"أجب على السؤال التالي بناءً على النص المرفق فقط. إذا كانت الإجابة غير موجودة، قل 'الإجابة غير متوفرة في المصدر'.\n\n"
            f"--- النص المرجعي ---\n{context}\n--- نهاية النص المرجعي ---\n\n"
            f"السؤال: {prompt}"
        )

    contents = chat_history or []
    contents.append({"role": "user", "parts": [{"text": final_prompt}]})
    data = {"contents": contents, "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192}}
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            current_api_key = next(api_key_cycler)
            url = f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={current_api_key}'
            
            response = requests.post(url, headers=headers, json=data, timeout=120)
            
            if response.status_code == 429: # خطأ تجاوز المعدل
                wait_time = (2 ** attempt) + 1
                print(f"واجهنا خطأ 429 (Too Many Requests). سننتظر {wait_time} ثانية...")
                log_interaction(from_user, "⚠️ ضغط على API", f"محاولة {attempt + 1} فشلت. سيتم الانتظار {wait_time} ثانية.")
                time.sleep(wait_time)
                continue

            response.raise_for_status() # إظهار الأخطاء الأخرى مثل 400 أو 500
            
            result = response.json()
            
            # التحقق من وجود رد صالح
            if 'candidates' in result and result['candidates'][0].get('content', {}).get('parts'):
                return result['candidates'][0]['content']['parts'][0]['text']
            
            # إذا كان الرد فارغاً أو محظوراً
            log_interaction(from_user, "⚠️ تحذير من Gemini", f"الرد من API لم يكن بالتنسيق المتوقع أو تم حظره.\n{result}")
            return "لم أتمكن من توليد رد. قد يكون المحتوى غير مناسب أو حدث خطأ ما. يرجى المحاولة مرة أخرى."

        except requests.exceptions.RequestException as e:
            print(f"خطأ في اتصال Gemini API: {e}")
            log_interaction(from_user, "❌ خطأ في اتصال Gemini", f"تفاصيل الخطأ:\n{e}")
            if attempt < max_retries - 1:
                time.sleep((2 ** attempt) + 1)
            else:
                return "حدثت مشكلة في الاتصال بالخادم بعد عدة محاولات. يرجى المحاولة لاحقًا."
        except Exception as e:
            print(f"خطأ غير متوقع في Gemini: {e}")
            log_interaction(from_user, "❌ خطأ غير متوقع في Gemini", f"تفاصيل الخطأ:\n{e}")
            return "حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى."
            
    return "لقد واجه الخادم ضغطاً عالياً. يرجى المحاولة مرة أخرى بعد دقيقة."

def send_long_message(chat_id, text, **kwargs):
    """تقسيم الرسائل الطويلة جداً إلى أجزاء أصغر لإرسالها."""
    MAX_LENGTH = 4096
    if len(text) <= MAX_LENGTH:
        bot.send_message(chat_id, text, **kwargs)
        return

    parts = []
    while len(text) > 0:
        if len(text) > MAX_LENGTH:
            part = text[:MAX_LENGTH]
            last_newline = part.rfind('\n')
            if last_newline != -1:
                parts.append(text[:last_newline])
                text = text[last_newline+1:]
            else:
                parts.append(text[:MAX_LENGTH])
                text = text[MAX_LENGTH:]
        else:
            parts.append(text)
            break
            
    for part in parts:
        if part.strip():
            bot.send_message(chat_id, part, **kwargs)
            time.sleep(0.5)

def check_membership(user_id):
    """التحقق من اشتراك المستخدم في القناة المطلوبة."""
    try:
        member = bot.get_chat_member(TELEGRAM_CHANNEL_ID, user_id)
        return member.status in ['creator', 'administrator', 'member']
    except telebot.apihelper.ApiTelegramException as e:
        if "user not found" in e.description:
            return False # المستخدم ليس عضواً
        print(f"خطأ أثناء التحقق من الاشتراك للمستخدم {user_id}: {e}")
        return False # نفترض أنه غير مشترك في حالة حدوث خطأ
    except Exception as e:
        print(f"خطأ عام أثناء التحقق من الاشتراك للمستخدم {user_id}: {e}")
        return False

# ==============================================================================
#  واجهة المستخدم (UI) والرسائل
# ==============================================================================

def send_subscription_message(chat_id):
    """إرسال رسالة تطلب من المستخدم الاشتراك في القنوات."""
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    btn_youtube = telebot.types.InlineKeyboardButton("اشترك في قناة اليوتيوب 🔴", url=YOUTUBE_CHANNEL_URL)
    btn_telegram = telebot.types.InlineKeyboardButton("اشترك في قناة التليجرام 🔵", url=f"https://t.me/{TELEGRAM_CHANNEL_ID.replace('@', '')}")
    btn_check = telebot.types.InlineKeyboardButton("✅ لقد اشتركت، تحقق الآن", callback_data="check_subscription")
    markup.add(btn_youtube, btn_telegram, btn_check)
    bot.send_message(
        chat_id,
        "🛑 *عذراً، يجب عليك الاشتراك في القنوات التالية أولاً لاستخدام البوت:*\n\n"
        "هذا يساعدنا على الاستمرار وتقديم المزيد. شكراً لدعمك! 🙏",
        reply_markup=markup, 
        parse_mode="Markdown"
    )

def send_help_message(chat_id):
    """إرسال رسالة المساعدة والإرشادات."""
    help_text = """
*🎯 معلومات البوت والإرشادات*

مرحباً بك في بوت الدowedar التعليمي! هذا البوت يستخدم ذكاء جوجل الاصطناعي (Gemini) للإجابة على أسئلتك، بالإضافة إلى قواعد معرفية يتم توليدها تلقائياً من الكتب لتقديم إجابات سريعة ودقيقة.

*📝 كيف تستخدم البوت؟*
1.  اختر بين "بحث عام" أو "بحث في المصادر" (الكتب).
2.  إذا اخترت البحث في كتاب، سيحاول البوت أولاً البحث في قاعدة المعرفة الذكية الخاصة بالكتاب.
3.  إذا لم يجد إجابة، سيلجأ إلى Gemini للبحث في محتوى الكتاب كاملاً.
4.  اكتب سؤالك بشكل واضح.

*⚙️ مميزات البوت:*
- *بحث عام:* إجابات شاملة في مختلف المواضيع.
- *بحث متخصص:* إجابات دقيقة من داخل الكتب مع أفضلية لقاعدة المعرفة.
- *توليد تلقائي لقواعد المعرفة:* يوفر سرعة ودقة في الإجابات المتكررة.
- *دعم متعدد اللغات* وإجابات منسقة.

*⏱️ حدود الاستخدام:*
- يمكنك إرسال سؤال كل *15 ثانية*.
- يتم تقسيم الإجابات الطويلة تلقائياً.

*❓ أسئلة شائعة:*
- *هل البوت مجاني؟* نعم، البوت مجاني حالياً.
- *كيف أبلغ عن مشكلة؟* اختر "📝 اقتراح أو مشكلة" من القائمة.
- *هل تحتفظ بمحادثاتي؟* نحن نحترم خصوصيتك ولا نخزن محادثاتك الشخصية.
"""
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("⬅️ العودة إلى القائمة الرئيسية", callback_data="main_menu"))
    bot.send_message(chat_id, help_text, parse_mode="Markdown", reply_markup=markup, disable_web_page_preview=True)

def show_main_menu(chat_id, message_id=None):
    """عرض القائمة الرئيسية للبوت."""
    users = load_users()
    user_data = users.get(str(chat_id), {})
    # نحصل على اسم المستخدم من بياناته المسجلة
    user_name = user_data.get('user_info', {}).get('first_name', 'صديقي')
    
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    btn_general = telebot.types.InlineKeyboardButton("🤖 بحث عام (AI)", callback_data="general_chat")
    btn_books = telebot.types.InlineKeyboardButton("📚 بحث في المصادر", callback_data="search_books")
    btn_help = telebot.types.InlineKeyboardButton("📜 مساعدة وإرشادات", callback_data="show_help")
    btn_feedback = telebot.types.InlineKeyboardButton("📝 اقتراح أو مشكلة", callback_data="send_feedback")
    markup.add(btn_general, btn_books, btn_help, btn_feedback)

    text = f"✅ أهلاً بك يا *{escape_markdown_v2(user_name)}*!\n\nاختر من فضلك ما تريد فعله:"

    try:
        if message_id:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode="Markdown")
        else:
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")
    except Exception as e:
        print(f"فشل في تعديل رسالة القائمة الرئيسية: {e}. سيتم إرسال رسالة جديدة.")
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")

def show_book_list(chat_id, message_id=None):
    """عرض قائمة الكتب المتاحة من Google Drive."""
    initial_text = "⏳ جارٍ جلب قائمة الكتب..."
    
    try:
        if message_id:
            bot.edit_message_text(initial_text, chat_id, message_id, reply_markup=None)
        else:
            msg = bot.send_message(chat_id, initial_text)
            message_id = msg.message_id
    except Exception as e:
        print(f"خطأ في إظهار رسالة التحميل لقائمة الكتب: {e}")
        msg = bot.send_message(chat_id, initial_text)
        message_id = msg.message_id

    books = list_books()
    if not books:
        bot.edit_message_text("عذرًا، لم أجد كتبًا في المجلد المخصص حاليًا.", chat_id, message_id)
        return

    users = load_users()
    user_data = users.get(str(chat_id), {})
    user_data['available_books'] = books # تخزين الكتب مؤقتاً لتجنب استدعاء API مرة أخرى
    save_users(users)

    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    for book in books:
        markup.add(telebot.types.InlineKeyboardButton(book['name'], callback_data=f"book:{book['id']}"))
    markup.add(telebot.types.InlineKeyboardButton("⬅️ العودة للقائمة الرئيسية", callback_data="main_menu"))
    bot.edit_message_text("اختر الكتاب الذي تريد البحث فيه:", chat_id, message_id, reply_markup=markup)

# ==============================================================================
#  معالجات رسائل التليجرام (Handlers)
# ==============================================================================

@bot.message_handler(commands=['start'])
def handle_start(message):
    """معالج أمر /start، نقطة الدخول الرئيسية للبوت."""
    chat_id = str(message.chat.id)
    log_interaction(message.from_user, "▶️ بدء استخدام البوت (/start)")
    
    # محاولة حذف لوحة المفاتيح القديمة إن وجدت
    try:
        remove_markup = telebot.types.ReplyKeyboardRemove()
        temp_msg = bot.send_message(chat_id, "...", reply_markup=remove_markup, disable_notification=True)
        bot.delete_message(chat_id, temp_msg.message_id)
    except Exception as e:
        print(f"لا يمكن إزالة لوحة المفاتيح: {e}")

    if check_membership(message.from_user.id):
        users = load_users()
        
        # تسجيل المستخدم إذا كان جديدًا وتحديث بياناته
        user_info = {
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name,
            "username": message.from_user.username,
        }
        if chat_id not in users:
            users[chat_id] = {"state": "main_menu", "chat_history": [], "user_info": user_info}
            log_interaction(message.from_user, "👤 تسجيل مستخدم جديد")
        else:
            users[chat_id]['user_info'] = user_info # تحديث بيانات المستخدم
        
        users[chat_id]['state'] = 'main_menu' # إعادة المستخدم للقائمة الرئيسية
        save_users(users)
        show_main_menu(chat_id)
    else:
        send_subscription_message(chat_id)
        log_interaction(message.from_user, "🔐 فشل التحقق من الاشتراك", "تم إرسال رسالة الاشتراك.")

@bot.callback_query_handler(func=lambda call: True)
def handle_callback_query(call):
    """معالج لجميع ضغطات الأزرار (Inline Keyboard)."""
    chat_id = str(call.message.chat.id)
    action = call.data
    log_interaction(call.from_user, "🔘 ضغط زر", f"البيانات: `{action}`")
    
    bot.answer_callback_query(call.id) # إرسال تأكيد الاستلام الفوري للزر

    # أولاً، تحقق من زر الاشتراك
    if action == 'check_subscription':
        if check_membership(call.from_user.id):
            bot.delete_message(chat_id, call.message.message_id)
            handle_start(call.message) 
        else:
            bot.answer_callback_query(call.id, "❌ لم تشترك بعد. يرجى الاشتراك ثم المحاولة.", show_alert=True)
        return

    # ثانياً، تحقق من عضوية المستخدم لجميع الأزرار الأخرى
    if not check_membership(call.from_user.id):
        send_subscription_message(chat_id)
        return

    users = load_users()
    if chat_id not in users: # حالة نادرة إذا تم حذف بيانات المستخدم
        handle_start(call.message)
        return
    user_data = users[chat_id]

    # توجيه المستخدم حسب الزر الذي ضغطه
    if action == 'main_menu':
        user_data['state'] = 'main_menu'
        save_users(users)
        show_main_menu(chat_id, call.message.message_id)
    elif action == 'show_help':
        bot.delete_message(chat_id, call.message.message_id)
        send_help_message(chat_id)
    elif action == 'send_feedback':
        user_data['state'] = 'awaiting_feedback'
        save_users(users)
        bot.edit_message_text(
            "✍️ من فضلك، اكتب الآن اقتراحك أو وصف المشكلة وسأقوم بإرسالها للمطور.",
            chat_id, call.message.message_id
        )
    elif action == "general_chat":
        user_data['state'] = 'general_chat'
        user_data['chat_history'] = []
        save_users(users)
        bot.edit_message_text(
            "🤖 *تم تفعيل وضع البحث العام.*\n\nتفضل بسؤالك في أي موضوع.",
            chat_id, call.message.message_id, parse_mode="Markdown"
        )
    elif action == "search_books":
        user_data['state'] = 'choosing_book'
        save_users(users)
        show_book_list(chat_id, call.message.message_id)
    elif action.startswith("book:"):
        try:
            _, book_id = action.split(':', 1)
            # استرجاع اسم الكتاب من البيانات المخزنة مؤقتاً
            available_books = user_data.get('available_books', [])
            book_name = next((b['name'] for b in available_books if b['id'] == book_id), None)
            
            if not book_name:
                bot.edit_message_text("حدث خطأ، لم أتمكن من العثور على الكتاب. حاول مرة أخرى.", chat_id, call.message.message_id)
                return

            user_data['state'] = 'book_chat'
            user_data['chat_history'] = []
            user_data['selected_book_id'] = book_id
            user_data['selected_book_name'] = book_name
            user_data.pop('available_books', None) # حذف قائمة الكتب المؤقتة
            save_users(users)
            
            bot.delete_message(chat_id, call.message.message_id)
            loading_msg = bot.send_message(chat_id, f"⏳ يتم الآن تحميل ومعالجة كتاب '{book_name}'...")
            
            # تحميل الكتاب (وتوليد KB إذا لزم الأمر)
            content = get_book_content(book_id, book_name, call.from_user)
            bot.delete_message(chat_id, loading_msg.message_id)

            reply_markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False)
            reply_markup.add(telebot.types.KeyboardButton("⬅️ العودة إلى قائمة الكتب"))

            if "خطأ:" in content or "عذراً،" in content:
                bot.send_message(chat_id, content, reply_markup=reply_markup)
            else:
                bot.send_message(chat_id, f"✅ تم تحميل كتاب '{book_name}'.\nيمكنك الآن طرح أسئلتك حول محتواه.", reply_markup=reply_markup)
        except Exception as e:
            bot.send_message(chat_id, f"حدث خطأ في معالجة اختيارك: {e}")
            log_interaction(call.from_user, "❌ خطأ في اختيار الكتاب", f"الخطأ: {e}")

@bot.message_handler(func=lambda m: True)
def handle_user_message(message):
    """المعالج الرئيسي لجميع الرسائل النصية من المستخدم."""
    chat_id = str(message.chat.id)
    
    if not check_membership(message.from_user.id):
        send_subscription_message(chat_id)
        return
        
    users = load_users()
    if chat_id not in users:
        handle_start(message)
        return
    user_data = users[chat_id]
    user_state = user_data.get('state')

    # التعامل مع رسالة العودة لقائمة الكتب
    if message.text == "⬅️ العودة إلى قائمة الكتب":
        log_interaction(message.from_user, "⬅️ العودة لقائمة الكتب")
        user_data['state'] = 'choosing_book'
        save_users(users)
        remove_markup = telebot.types.ReplyKeyboardRemove()
        bot.send_message(chat_id, "جاري العودة لقائمة الكتب...", reply_markup=remove_markup, disable_notification=True)
        show_book_list(chat_id)
        return

    # التعامل مع رسالة الاقتراح
    if user_state == 'awaiting_feedback':
        log_interaction(message.from_user, "📝 اقتراح/مشكلة جديدة", f"الرسالة: {message.text}")
        bot.send_message(chat_id, "✅ شكرًا لك! تم استلام رسالتك وسيتم مراجعتها.")
        user_data['state'] = 'main_menu'
        save_users(users)
        show_main_menu(chat_id)
        return

    # التعامل مع رسائل الأسئلة (بحث عام أو في كتاب)
    if user_state in ['general_chat', 'book_chat']:
        current_time = time.time()
        last_query_time = user_data.get('last_query_time', 0)
        
        # تطبيق فترة الانتظار (Cooldown)
        if current_time - last_query_time < COOLDOWN_SECONDS:
            remaining = round(COOLDOWN_SECONDS - (current_time - last_query_time))
            bot.send_message(chat_id, f"⏳ الرجاء الانتظار {remaining} ثانية قبل طرح سؤال جديد.")
            return
        
        user_data['last_query_time'] = current_time
        save_users(users)
        
        processing_msg = bot.send_message(chat_id, "⏳ جارِ معالجة طلبك...")
        
        gemini_context = "" 
        found_in_kb = False # لتحديد مصدر الإجابة
        response_text = ""

        # --- منطق البحث الذكي ---
        if user_state == 'book_chat':
            book_id = user_data.get('selected_book_id')
            book_name = user_data.get('selected_book_name', 'غير محدد')
            current_book_kb = book_knowledge_bases.get(book_id, [])
            
            # 1. البحث في قاعدة المعرفة المحلية (Fuzzy Matching)
            if current_book_kb: 
                kb_questions = [entry['standard_question'] for entry in current_book_kb]
                best_match = process.extractOne(message.text, kb_questions, scorer=fuzz.token_sort_ratio)
                
                if best_match and best_match[1] >= 85: # نسبة تطابق 85% أو أكثر
                    matched_question_text = best_match[0]
                    response_text = next((e['answer'] for e in current_book_kb if e['standard_question'] == matched_question_text), None)
                    found_in_kb = True
                    log_interaction(message.from_user, f"💬 إجابة من KB", f"للسؤال: `{message.text}`\nالكتاب: {book_name}\nالتطابق: {best_match[1]}%")
            
            # 2. إذا لم يتم العثور على إجابة، جهز البحث الكامل عبر Gemini
            if not found_in_kb:
                gemini_context = get_book_content(book_id, book_name, message.from_user)
                if "خطأ:" in gemini_context or "عذراً،" in gemini_context:
                    bot.delete_message(chat_id=chat_id, message_id=processing_msg.message_id)
                    bot.send_message(chat_id, gemini_context)
                    return

        # --- إرسال الطلب واستقبال الرد ---
        if not found_in_kb:
            response_text = send_to_gemini(message.from_user, message.text, user_data.get("chat_history", []), gemini_context)
            log_source = "Gemini (كتاب)" if user_state == 'book_chat' else "Gemini (عام)"
            log_interaction(message.from_user, f"💬 إجابة من {log_source}", f"❓ *السؤال:*\n{message.text}\n\n🤖 *الرد:*\n{response_text[:500]}...")
        
        # إرسال الرد النهائي للمستخدم
        bot.delete_message(chat_id, processing_msg.message_id)
        send_long_message(chat_id, response_text, parse_mode="Markdown")
        
        # تحديث سجل المحادثة فقط إذا كانت الإجابة من Gemini
        if not found_in_kb:
            history = user_data.get("chat_history", [])
            history.append({"role": "user", "parts": [{"text": message.text}]})
            history.append({"role": "model", "parts": [{"text": response_text}]})
            user_data["chat_history"] = history[-10:] # الاحتفاظ بآخر 5 محاورات
            save_users(users)
    else:
        # إذا كان المستخدم في حالة غير معروفة، أعده للقائمة الرئيسية
        show_main_menu(chat_id)

# ==============================================================================
#  نقطة انطلاق البوت
# ==============================================================================
if __name__ == "__main__":
    
    print(f"🚀 [Dowedar Bot] - بدء تشغيل البوت...")
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 30)
    print("✅ تم تحميل المتغيرات البيئية بنجاح.")
    
    # تحميل جميع قواعد المعرفة الموجودة مسبقاً
    load_all_book_kbs()
    
    print("-" * 30)
    print("⏳ البوت الآن قيد التشغيل وجاهز لاستقبال الرسائل...")
    bot.infinity_polling(skip_pending=True)

    
