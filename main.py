# -*- coding: utf-8 -*-
import os
import asyncio
import logging
import time
import io
import fitz  # PyMuPDF
from itertools import cycle

# --- Aiogram Imports ---
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from aiogram.exceptions import TelegramBadRequest

# --- Google & Gemini Imports ---
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import aiohttp # For async HTTP requests to Gemini API

# --- Vector DB Import ---
import chromadb

# --- Environment Setup ---
from dotenv import load_dotenv
load_dotenv()

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configuration Variables ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
LOG_BOT_TOKEN = os.getenv('LOG_BOT_TOKEN')
LOG_CHAT_ID = os.getenv('LOG_CHAT_ID')
API_KEYS_STRING = os.getenv('API_KEYS')
DRIVE_FOLDER_ID = os.getenv('DRIVE_FOLDER_ID')
YOUTUBE_CHANNEL_URL = os.getenv('YOUTUBE_CHANNEL_URL')
TELEGRAM_CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
MODEL_NAME = os.getenv('MODEL_NAME', 'gemini-1.5-flash')
COOLDOWN_SECONDS = int(os.getenv('COOLDOWN_SECONDS', 10))

if not all([TELEGRAM_BOT_TOKEN, LOG_BOT_TOKEN, LOG_CHAT_ID, API_KEYS_STRING, DRIVE_FOLDER_ID, TELEGRAM_CHANNEL_ID]):
    raise ValueError("أحد متغيرات البيئة المطلوبة غير موجود!")

# --- API Keys & Model Initialization ---
API_KEYS = [key.strip() for key in API_KEYS_STRING.split(',')]
api_key_cycler = cycle(API_KEYS)
genai.configure(api_key=next(api_key_cycler)) # Configure with the first key initially

# --- Bot & Dispatcher Setup ---
# MemoryStorage is good for development. For production, consider RedisStorage.
storage = MemoryStorage()
bot = Bot(token=TELEGRAM_BOT_TOKEN, parse_mode="Markdown")
dp = Dispatcher(storage=storage)

# --- Vector Database Setup ---
# ChromaDB runs in-memory. It's fast and requires no setup.
# The data is lost on restart unless you configure persistence.
chroma_client = chromadb.Client()
# A single collection for all books. We use unique IDs for each chunk.
vector_collection = chroma_client.get_or_create_collection(name="books_rag_collection")


# =========================================================================================
#  Finite State Machine (FSM) - لإدارة حالة المحادثة مع كل مستخدم بشكل منفصل
# =========================================================================================
class UserState(StatesGroup):
    main_menu = State()
    general_chat = State()
    book_chat = State()
    awaiting_feedback = State()

# =========================================================================================
#  Google Drive & RAG Helper Functions (Async Ready)
# =========================================================================================
def get_drive_service():
    """Builds the Google Drive service object. This is synchronous."""
    try:
        creds = service_account.Credentials.from_service_account_file('credentials.json', scopes=['https://www.googleapis.com/auth/drive.readonly'])
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        logging.error(f"Failed to get Drive service: {e}")
        return None

async def list_drive_books():
    """Lists books from Google Drive asynchronously."""
    service = get_drive_service()
    if not service: return []
    try:
        # Run the blocking I/O call in a separate thread
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: service.files().list(
            q=f"'{DRIVE_FOLDER_ID}' in parents and trashed=false",
            fields="files(id, name)"
        ).execute())
        return result.get('files', [])
    except Exception as e:
        logging.error(f"Failed to list books: {e}")
        return []

def chunk_text(text: str, chunk_size: int = 800, chunk_overlap: int = 100) -> list[str]:
    """Splits a long text into smaller, overlapping chunks."""
    if not text: return []
    words = text.split()
    chunks = []
    current_pos = 0
    while current_pos < len(words):
        end_pos = current_pos + chunk_size
        chunk_words = words[current_pos:end_pos]
        chunks.append(" ".join(chunk_words))
        current_pos += chunk_size - chunk_overlap
    return chunks

async def process_and_index_book(book_id: str, book_name: str, chat_id: int):
    """
    The heavy-lifting function that runs in the background.
    Downloads, chunks, and indexes a book into the vector DB.
    """
    try:
        await bot.send_message(chat_id, f"⏳ *الخطوة 1/3:* جاري تحميل كتاب `{book_name}`...")
        
        # 1. Download the book content (blocking I/O)
        service = get_drive_service()
        if not service:
            await bot.send_message(chat_id, "❌ خطأ في الاتصال بخدمة Google Drive.")
            return

        request = service.files().get_media(fileId=book_id)
        file_io = io.BytesIO()
        # This part is blocking, so we run it in a thread
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, MediaIoBaseDownload(file_io, request).next_chunk)
        file_io.seek(0)

        # 2. Extract text based on file type
        text = ""
        if book_name.lower().endswith('.pdf'):
            with fitz.open(stream=file_io, filetype="pdf") as doc:
                text = "".join(page.get_text() for page in doc)
        elif book_name.lower().endswith('.txt'):
            text = file_io.read().decode('utf-8', errors='ignore')
        else:
            await bot.send_message(chat_id, f"❌ صيغة الملف `{book_name}` غير مدعومة.")
            return

        if not text.strip():
            await bot.send_message(chat_id, f"⚠️ لم أتمكن من استخلاص أي نص من الكتاب `{book_name}`. قد يكون فارغًا أو صورة.")
            return
            
        await bot.send_message(chat_id, f"⏳ *الخطوة 2/3:* جاري تقسيم الكتاب وفهرسته...")

        # 3. Chunk the text
        text_chunks = chunk_text(text)
        if not text_chunks:
            await bot.send_message(chat_id, "⚠️ فشلت عملية تقسيم النص.")
            return
            
        # 4. Generate embeddings (Can be a slow network operation)
        # Note: The 'genai' library doesn't have a native async version for embedding yet.
        # So we run this potentially blocking call in a thread as well.
        try:
            embedding_result = await loop.run_in_executor(
                None, 
                lambda: genai.embed_content(
                    model="models/text-embedding-004",
                    content=text_chunks,
                    task_type="RETRIEVAL_DOCUMENT"
                )
            )
            embeddings = embedding_result['embedding']
        except Exception as e:
            logging.error(f"Gemini embedding failed: {e}")
            await bot.send_message(chat_id, f"❌ حدث خطأ أثناء الاتصال بخدمة الذكاء الاصطناعي للفهرسة.")
            return


        # 5. Store in Vector DB
        chunk_ids = [f"{book_id}_{i}" for i in range(len(text_chunks))]
        vector_collection.add(
            ids=chunk_ids,
            embeddings=embeddings,
            documents=text_chunks,
            metadatas=[{"book_id": book_id, "book_name": book_name}] * len(text_chunks)
        )

        await bot.send_message(chat_id, f"✅ *الخطوة 3/3:* تم تجهيز كتاب `{book_name}` بنجاح!\n\nيمكنك الآن طرح أسئلتك حوله.")

    except Exception as e:
        logging.error(f"Error processing book {book_id}: {e}")
        await bot.send_message(chat_id, f"❌ حدث خطأ فادح أثناء معالجة الكتاب. يرجى إبلاغ المطور.")

async def find_relevant_chunks(question: str, book_id: str, n_results: int = 5) -> str:
    """Finds relevant chunks from the vector DB for a given question."""
    try:
        # 1. Embed the user's question
        loop = asyncio.get_running_loop()
        question_embedding = (await loop.run_in_executor(
            None,
            lambda: genai.embed_content(
                model="models/text-embedding-004",
                content=question,
                task_type="RETRIEVAL_QUERY"
            )
        ))['embedding']

        # 2. Query the vector DB
        results = vector_collection.query(
            query_embeddings=[question_embedding],
            n_results=n_results,
            where={"book_id": book_id} # Filter by the selected book
        )
        
        relevant_docs = results.get('documents', [[]])[0]
        return "\n---\n".join(relevant_docs)
    except Exception as e:
        logging.error(f"Failed to find relevant chunks: {e}")
        return ""


# =========================================================================================
#  API & Bot Helper Functions
# =========================================================================================
async def log_interaction(user: types.User, event_type: str, details: str = ""):
    """Sends a log message to the log channel asynchronously."""
    log_message = (
        f"📌 *{event_type}*\n\n"
        f"👤 *المستخدم:*\n"
        f"- الاسم: {user.first_name} {user.last_name or ''}\n"
        f"- اليوزر: @{user.username or 'N/A'}\n"
        f"- الآي دي: `{user.id}`\n\n"
        f"⚙️ *التفاصيل:*\n{details}"
    )
    try:
        log_bot = Bot(token=LOG_BOT_TOKEN, parse_mode="Markdown")
        await log_bot.send_message(chat_id=LOG_CHAT_ID, text=log_message, disable_web_page_preview=True)
        await log_bot.session.close()
    except Exception as e:
        logging.error(f"Failed to send log: {e}")

async def send_to_gemini(user: types.User, prompt: str, chat_history: list = None, context: str = "") -> str:
    """Sends a request to Gemini API asynchronously and handles retries."""
    final_prompt = prompt
    if context:
        final_prompt = (
            f"أجب على السؤال التالي بناءً على النص المرجعي المرفق فقط. إذا كانت الإجابة غير موجودة في النص، قل بوضوح 'الإجابة غير متوفرة في المصدر'.\n\n"
            f"--- بداية النص المرجعي ---\n{context}\n--- نهاية النص المرجعي ---\n\n"
            f"السؤال: {prompt}"
        )
    
    contents = chat_history or []
    contents.append({"role": "user", "parts": [{"text": final_prompt}]})
    data = {"contents": contents, "generationConfig": {"temperature": 0.7, "maxOutputTokens": 8192}}

    max_retries = 3
    async with aiohttp.ClientSession() as session:
        for attempt in range(max_retries):
            current_api_key = next(api_key_cycler)
            url = f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={current_api_key}'
            
            try:
                async with session.post(url, json=data, timeout=120) as response:
                    if response.status == 429: # Too Many Requests
                        wait_time = (2 ** attempt) + 1
                        logging.warning(f"Rate limit hit. Retrying in {wait_time}s...")
                        await log_interaction(user, "⚠️ تحذير: ضغط على API", f"محاولة {attempt + 1} فشلت. سيتم الانتظار {wait_time} ثانية.")
                        await asyncio.sleep(wait_time)
                        continue

                    response.raise_for_status()
                    result = await response.json()

                    if 'candidates' in result and result['candidates']:
                        if 'content' in result['candidates'][0] and 'parts' in result['candidates'][0]['content']:
                            return result['candidates'][0]['content']['parts'][0]['text']
                    
                    logging.warning(f"Unexpected Gemini response format: {result}")
                    await log_interaction(user, "⚠️ تحذير من Gemini", f"الرد من API لم يكن بالتنسيق المتوقع.\n`{result}`")
                    return "لم أتمكن من توليد رد. يرجى المحاولة مرة أخرى."
            
            except aiohttp.ClientError as e:
                logging.error(f"Gemini API request error: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep((2 ** attempt) + 1)
                else:
                    await log_interaction(user, "❌ خطأ في اتصال Gemini", f"تفاصيل الخطأ:\n`{e}`")
                    return "حدثت مشكلة في الاتصال بالخادم. يرجى المحاولة لاحقًا."

    return "لقد واجه الخادم ضغطاً عالياً. يرجى المحاولة مرة أخرى بعد دقيقة."

async def send_long_message(chat_id: int, text: str):
    """Splits a long message into multiple smaller messages."""
    MAX_LENGTH = 4096
    if len(text) <= MAX_LENGTH:
        try:
            await bot.send_message(chat_id, text)
        except TelegramBadRequest as e:
            logging.error(f"Failed to send message: {e}")
            await bot.send_message(chat_id, "حدث خطأ في تنسيق الرسالة من الـ API.")
        return

    parts = []
    while len(text) > 0:
        if len(text) > MAX_LENGTH:
            part = text[:MAX_LENGTH]
            last_newline = part.rfind('\n')
            if last_newline != -1:
                part = part[:last_newline]
            else:
                last_space = part.rfind(' ')
                if last_space != -1:
                    part = part[:last_space]
            
            text = text[len(part):]
            parts.append(part)
        else:
            parts.append(text)
            break
    
    for part in parts:
        if part.strip():
            await bot.send_message(chat_id, part)
            await asyncio.sleep(1) # To avoid spamming the user

# =========================================================================================
#  UI & Keyboards
# =========================================================================================
def get_main_menu_keyboard():
    buttons = [
        [InlineKeyboardButton(text="🤖 بحث عام (AI)", callback_data="nav_general_search")],
        [InlineKeyboardButton(text="📚 بحث في المصادر", callback_data="nav_books_search")],
        [InlineKeyboardButton(text="📜 مساعدة وإرشادات", callback_data="nav_help")],
        [InlineKeyboardButton(text="📝 اقتراح أو مشكلة", callback_data="nav_feedback")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_to_main_menu_button():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ العودة إلى القائمة الرئيسية", callback_data="nav_main_menu")]
    ])
    
# =========================================================================================
#  Middleware (for checking subscription and rate limiting)
# =========================================================================================
class AccessMiddleware(aiogram.BaseMiddleware):
    # To store the last query time for each user
    user_timestamps = {}
    
    async def __call__(self, handler, event: types.TelegramObject, data: dict):
        user = data.get('event_from_user')
        if not user: return await handler(event, data)
        
        # 1. Check Subscription
        try:
            member = await bot.get_chat_member(TELEGRAM_CHANNEL_ID, user.id)
            if member.status not in ['creator', 'administrator', 'member']:
                markup = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="اشترك في قناة اليوتيوب 🔴", url=YOUTUBE_CHANNEL_URL)],
                    [InlineKeyboardButton(text="اشترك في قناة التليجرام 🔵", url=f"https://t.me/{TELEGRAM_CHANNEL_ID.replace('@', '')}")],
                    [InlineKeyboardButton(text="✅ تحققت من الاشتراك", callback_data="check_subscription")]
                ])
                await bot.send_message(user.id, "🛑 عذراً، يجب عليك الاشتراك في القنوات التالية أولاً لاستخدام البوت:", reply_markup=markup)
                return
        except Exception:
            # If the channel is private or bot is not admin, allow access but log it.
            logging.warning(f"Could not check membership for user {user.id}. Allowing access.")

        # 2. Rate Limiting for messages
        if isinstance(event, Message) and event.text and not event.text.startswith('/'):
            current_time = time.time()
            last_time = self.user_timestamps.get(user.id, 0)
            
            if current_time - last_time < COOLDOWN_SECONDS:
                remaining = round(COOLDOWN_SECONDS - (current_time - last_time))
                await event.answer(f"⏳ الرجاء الانتظار {remaining} ثانية قبل طرح سؤال جديد.")
                return
            
            self.user_timestamps[user.id] = current_time
            
        return await handler(event, data)

dp.update.middleware(AccessMiddleware())
dp.message.middleware(AccessMiddleware())


# =========================================================================================
#  Telegram Handlers
# =========================================================================================

@dp.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    await log_interaction(message.from_user, "بدء استخدام البوت", f"/start command")
    await state.clear() # Clear any previous state
    await state.set_state(UserState.main_menu)
    await message.answer(
        "✅ أهلاً بك في بوت البحث العلمي!\n\nاختر من فضلك ما تريد فعله:",
        reply_markup=get_main_menu_keyboard()
    )

@dp.callback_query(F.data == "check_subscription")
async def handle_check_subscription(call: CallbackQuery, state: FSMContext):
    # This handler bypasses the middleware check once
    try:
        member = await bot.get_chat_member(TELEGRAM_CHANNEL_ID, call.from_user.id)
        if member.status in ['creator', 'administrator', 'member']:
            await call.message.delete()
            await handle_start(call.message, state)
        else:
            await call.answer("❌ لم تشترك بعد. يرجى الاشتراك ثم المحاولة مجدداً.", show_alert=True)
    except:
        await call.answer("حدث خطأ، يرجى المحاولة مرة أخرى.", show_alert=True)


# --- Navigation Handlers ---

@dp.callback_query(F.data == "nav_main_menu")
async def nav_to_main_menu(call: CallbackQuery, state: FSMContext):
    await state.set_state(UserState.main_menu)
    await state.update_data(chat_history=[], selected_book_id=None, selected_book_name=None)
    await call.message.edit_text(
        "✅ أهلاً بك من جديد!\n\nاختر من فضلك ما تريد فعله:",
        reply_markup=get_main_menu_keyboard()
    )

@dp.callback_query(F.data == "nav_help")
async def nav_to_help(call: CallbackQuery):
    help_text = """
    🎯 *معلومات البوت والإرشادات*
    
    *🛠 تم التطوير بواسطة:*
    Eng. Ahmed Dowedar
    
    *🤖 ما هو هذا البوت؟*
    بوت ذكاء اصطناعي يستخدم تقنيات RAG للبحث في المصادر الخاصة بك (PDF, TXT) بالإضافة إلى البحث العام.
    
    *📚 كيفية الاستخدام:*
    1.  *بحث عام:* اختر الخيار للدخول في محادثة حرة مع الذكاء الاصطناعي.
    2.  *بحث في المصادر:* اختر هذا الخيار لعرض قائمة بكتبك في Google Drive. عند اختيار كتاب، سيقوم البوت بمعالجته وفهرسته في الخلفية. عند الانتهاء، يمكنك طرح أسئلة حول محتواه.
    
    *⚙️ الميزات الرئيسية:*
    -   *السرعة:* يتم فهرسة الكتب مرة واحدة فقط.
    -   *الدقة:* يستخدم البحث الدلالي (Vector Search) لفهم معنى سؤالك وإيجاد أكثر الإجابات صلة من داخل المصدر.
    -   *السلاسة:* معالجة الكتب تتم في الخلفية دون تجميد البوت.
    """
    await call.message.edit_text(help_text, reply_markup=get_back_to_main_menu_button())

@dp.callback_query(F.data == "nav_feedback")
async def nav_to_feedback(call: CallbackQuery, state: FSMContext):
    await state.set_state(UserState.awaiting_feedback)
    await call.message.edit_text("من فضلك، اكتب الآن اقتراحك أو وصف المشكلة التي تواجهك وسأقوم بإرسالها للمطور.")


# --- Main Logic Handlers ---

@dp.callback_query(F.data == "nav_general_search")
async def start_general_search(call: CallbackQuery, state: FSMContext):
    await state.set_state(UserState.general_chat)
    await state.update_data(chat_history=[])
    await call.message.edit_text("تم تفعيل وضع البحث العام. تفضل بسؤالك.", reply_markup=get_back_to_main_menu_button())

@dp.callback_query(F.data == "nav_books_search")
async def start_books_search(call: CallbackQuery):
    await call.message.edit_text("⏳ جارٍ جلب قائمة الكتب من Google Drive...")
    books = await list_drive_books()
    if not books:
        await call.message.edit_text("عذرًا، لم أجد كتبًا في المجلد المخصص.", reply_markup=get_back_to_main_menu_button())
        return
        
    buttons = [
        [InlineKeyboardButton(text=book['name'], callback_data=f"book_select:{book['id']}:{book['name']}")]
        for book in books
    ]
    buttons.append([InlineKeyboardButton(text="⬅️ العودة", callback_data="nav_main_menu")])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    await call.message.edit_text("اختر الكتاب الذي تريد البحث فيه:", reply_markup=markup)

@dp.callback_query(F.data.startswith("book_select:"))
async def select_book(call: CallbackQuery, state: FSMContext):
    try:
        _, book_id, book_name = call.data.split(":", 2)
    except ValueError:
        await call.answer("خطأ في بيانات الكتاب.", show_alert=True)
        return

    await call.message.edit_text(f"اخترت كتاب `{book_name}`.\n\nسيقوم البوت الآن بمعالجته وفهرسته. هذه العملية تتم مرة واحدة فقط لكل كتاب وقد تستغرق بضع دقائق للكتب الكبيرة. **يمكنك استخدام البوت بشكل طبيعي أثناء هذه العملية.**", reply_markup=get_back_to_main_menu_button())

    # Start the heavy processing in the background
    asyncio.create_task(process_and_index_book(book_id, book_name, call.from_user.id))

    # Set the state for the user to be ready for book chat
    await state.set_state(UserState.book_chat)
    await state.update_data(
        selected_book_id=book_id,
        selected_book_name=book_name,
        chat_history=[]
    )
    
# --- Message Handlers for Different States ---

@dp.message(UserState.awaiting_feedback)
async def handle_feedback(message: Message, state: FSMContext):
    await log_interaction(message.from_user, "📝 اقتراح/مشكلة جديدة", message.text)
    await message.answer("✅ شكرًا لك! تم استلام رسالتك وسيتم مراجعتها.", reply_markup=get_main_menu_keyboard())
    await state.set_state(UserState.main_menu)

@dp.message(UserState.general_chat)
async def handle_general_chat(message: Message, state: FSMContext):
    await bot.send_chat_action(message.chat.id, 'typing')
    
    user_data = await state.get_data()
    chat_history = user_data.get('chat_history', [])
    
    response = await send_to_gemini(message.from_user, message.text, chat_history)
    
    await send_long_message(message.chat.id, response)
    
    # Update chat history
    chat_history.append({"role": "user", "parts": [{"text": message.text}]})
    chat_history.append({"role": "model", "parts": [{"text": response}]})
    await state.update_data(chat_history=chat_history[-10:]) # Keep last 5 conversations

@dp.message(UserState.book_chat)
async def handle_book_chat(message: Message, state: FSMContext):
    user_data = await state.get_data()
    book_id = user_data.get("selected_book_id")
    book_name = user_data.get("selected_book_name")
    
    if not book_id:
        await message.answer("عذرًا، يبدو أنه لم يتم تحديد كتاب. يرجى العودة واختيار كتاب أولاً.", reply_markup=get_back_to_main_menu_button())
        return
        
    # Check if the book has been indexed
    try:
        test_query = vector_collection.get(where={"book_id": book_id}, limit=1)
        if not test_query['ids']:
            await message.answer(f"⏳ تتم معالجة كتاب `{book_name}` حاليًا. يرجى الانتظار حتى يصلك إشعار بالانتهاء.")
            return
    except Exception as e:
        logging.error(f"ChromaDB check failed: {e}")
        await message.answer("حدث خطأ في قاعدة البيانات. يرجى إبلاغ المطور.")
        return

    await bot.send_chat_action(message.chat.id, 'typing')
    thinking_msg = await message.answer("🤔 جارٍ البحث في الكتاب...")
    
    # 1. Find relevant context from Vector DB
    context = await find_relevant_chunks(message.text, book_id)
    if not context:
        await thinking_msg.edit_text("لم أجد أي معلومات ذات صلة بسؤالك في الكتاب المحدد.")
        return
        
    # 2. Send to Gemini with context
    chat_history = user_data.get('chat_history', [])
    response = await send_to_gemini(message.from_user, message.text, chat_history, context)
    
    await thinking_msg.delete()
    await send_long_message(message.chat.id, response)
    
    # 3. Update history
    chat_history.append({"role": "user", "parts": [{"text": message.text}]})
    chat_history.append({"role": "model", "parts": [{"text": response}]})
    await state.update_data(chat_history=chat_history[-10:])
    
# --- Main Execution ---
async def main():
    logging.info("Starting Gemini Bot (v3.0 - Aiogram Edition)...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())

