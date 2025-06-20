# 🤖 بوت Univy - مساعدك التعليمي الذكي

![Python](https://img.shields.io/badge/Python-3.9%2B-blue?style=for-the-badge&logo=python)
![License](https://img.shields.io/github/license/EngAhmedDowedar/Ai-bot?style=for-the-badge)
![GitHub issues](https://img.shields.io/github/issues/EngAhmedDowedar/Ai-bot?style=for-the-badge)
![GitHub forks](https://img.shields.io/github/forks/EngAhmedDowedar/Ai-bot?style=for-the-badge&logo=github)
![GitHub stars](https://img.shields.io/github/stars/EngAhmedDowedar/Ai-bot?style=for-the-badge&logo=github)

**Univy** هو بوت تليجرام متقدم يستخدم قوة Google Gemini API لتقديم إجابات ذكية، مع قدرة فريدة على إنشاء قواعد معرفة تلقائية من الكتب والمستندات للرد السريع والدقيق.

---

### ✨ لمحة سريعة (عرض حي)

---

### 🚀 الميزات الرئيسية

* **🧠 تكامل مع Gemini API:** إجابات ذكية وقوية على الأسئلة العامة.
* **📚 قواعد معرفة تلقائية (Auto-KB):** يقوم البوت بتحليل الكتب (PDFs) لأول مرة وإنشاء قاعدة معرفة (سؤال وجواب) تلقائياً.
* **⚡️ بحث ذكي محلي:** يستخدم مقارنة النصوص (Fuzzy Matching) للبحث في قاعدة المعرفة المحلية قبل اللجوء إلى Gemini، مما يوفر سرعة وتكلفة.
* **☁️ تكامل مع Google Drive:** القدرة على سرد وتحميل الكتب مباشرة من مجلد محدد في Google Drive.
* **🔐 نظام اشتراك إجباري:** يمكن ضبط البوت ليعمل فقط للمشتركين في قنوات تليجرام ويوتيوب محددة.
* **⚙️ قابلية للتخصيص:** يمكن التحكم في كل الإعدادات بسهولة عبر متغيرات البيئة (`.env`).
* **💬 إدارة الحوار:** يتذكر آخر 5 محاورات مع المستخدم لتقديم ردود ذات سياق.

---

### 🔧 الإعداد والتشغيل

اتبع الخطوات التالية لتشغيل البوت على جهازك.

**1. استنساخ المستودع (Clone):**
```bash
git clone [https://github.com/EngAhmedDowedar/Ai-bot.git](https://github.com/EngAhmedDowedar/Ai-bot.git)
cd Ai-bot
```

**2. إنشاء بيئة افتراضية (Recommended):**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

**3. تثبيت المكتبات:**
```bash
pip install -r requirements.txt
```

**4. إعداد متغيرات البيئة:**
   - قم بنسخ ملف `.env.example` إلى `.env`. في أنظمة ويندوز استخدم `copy` وفي أنظمة لينكس/ماك استخدم `cp`.
     ```bash
     # Windows
     copy .env.example .env
     # Linux / macOS
     cp .env.example .env
     ```
   - افتح ملف `.env` الجديد واملأ جميع المتغيرات المطلوبة.

**5. إعداد صلاحيات Google Drive:**
   - اتبع [هذا الدليل](https://developers.google.com/workspace/guides/create-credentials#create_credentials_for_a_service_account) لإنشاء حساب خدمة (Service Account).
   - قم بتنزيل ملف الصلاحيات بصيغة JSON.
   - أعد تسميته إلى `credentials.json` وضعه في المجلد الرئيسي للمشروع.
   - **هام جداً:** لا تنسَ دعوة بريد حساب الخدمة (Service Account's email) إلى مجلد Google Drive الخاص بالكتب ومنحه صلاحية "Viewer".

**6. تشغيل البوت:**
```bash
python main.py
```

---

### 🛠️ كيفية المساهمة

نرحب بجميع المساهمات! سواء كانت إصلاح أخطاء، أو إضافة ميزات جديدة، أو تحسين التوثيق. يمكنك البدء عن طريق فتح "Issue" جديد لمناقشة التغييرات التي تقترحها.

---

### 📄 الرخصة

هذا المشروع مرخص تحت رخصة MIT. انظر ملف [LICENSE](LICENSE) لمزيد من التفاصيل.

---

### 💬 تواصل

صُنع بحب ❤️ بواسطة **م/ أحمد دويدار (Eng. Ahmed Dowedar)**.

[![GitHub](https://img.shields.io/badge/GitHub-Profile-black?style=for-the-badge&logo=github)](https://github.com/EngAhmedDowedar)
