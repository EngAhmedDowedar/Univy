<p align="center">
  <a href="https://github.com/EngAhmedDowedar/Univy">
    <!-- يمكنك تصميم لوجو بسيط ووضعه هنا -->
    <h1 align="center">🎓 Univy Bot</h1>
  </a>
</p>

<p align="center">
  مساعدك التعليمي الذكي على تليجرام، مدعوم بقوة Google Gemini.
</p>

<p align="center">
  <a href="https://github.com/EngAhmedDowedar/Univy/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/EngAhmedDowedar/Univy?style=for-the-badge" alt="License">
  </a>
  <a href="https://github.com/EngAhmedDowedar/Univy/stargazers">
    <img src="https://img.shields.io/github/stars/EngAhmedDowedar/Univy?style=for-the-badge&logo=github" alt="Stars">
  </a>
  <a href="https://github.com/EngAhmedDowedar/Univy/network/members">
    <img src="https://img.shields.io/github/forks/EngAhmedDowedar/Univy?style=for-the-badge&logo=github" alt="Forks">
  </a>
  <a href="https://github.com/EngAhmedDowedar/Univy/issues">
    <img src="https://img.shields.io/github/issues/EngAhmedDowedar/Univy?style=for-the-badge" alt="Issues">
  </a>
</p>

> **Univy** هو بوت تليجرام متقدم ومفتوح المصدر، مصمم ليكون شريكاً دراسياً للطلاب والباحثين. يقوم بتحليل الكتب والمستندات، ويبني قاعدة معرفة ذكية، ويجيب على الأسئلة باستخدام أحدث نماذج الذكاء الاصطناعي من جوجل.

---

### ✨ عرض حي

<!-- هام جداً: سجل فيديو قصير للبوت وهو يعمل وحوله إلى GIF وضعه هنا -->
<p align="center">
  <img src="assets/bot_demo.gif" alt="عرض حي للبوت" />
</p>

---

### 🚀 الميزات

| الميزة | الوصف | الحالة |
| :--- | :--- | :---: |
| **تكامل Gemini API** | إجابات ذكية وقوية على الأسئلة العامة. | ✅ |
| **قواعد معرفة تلقائية** | تحليل الكتب (PDFs) وإنشاء قاعدة معرفة (سؤال وجواب) تلقائياً. | ✅ |
| **بحث ذكي محلي** | بحث سريع في قاعدة المعرفة المحلية لتوفير السرعة والتكلفة. | ✅ |
| **تكامل Google Drive** | تحميل الكتب مباشرة من مجلد محدد في Google Drive. | ✅ |
| **نظام اشتراك إجباري** | دعم قنوات الاشتراك الإجباري لتنمية مجتمعك. | ✅ |
| **إدارة الحوار** | الاحتفاظ بسياق المحادثة لتقديم ردود أكثر دقة. | ✅ |

---

### 💻 التقنيات المستخدمة

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google%20Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white)
![Google Drive](https://img.shields.io/badge/Google%20Drive-4285F4?style=for-the-badge&logo=googledrive&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)
![Shell](https://img.shields.io/badge/Shell-4EAA25?style=for-the-badge&logo=GNU-Bash&logoColor=white)

---

### 🛠️ الإعداد والتشغيل

اتبع الخطوات التالية لتشغيل البوت على جهازك.

#### 1. المتطلبات الأساسية
- Python 3.9 أو أحدث.
- حساب تليجرام وحساب جوجل.

#### 2. استنساخ المستودع (Clone)
```bash
git clone [https://github.com/EngAhmedDowedar/Univy.git](https://github.com/EngAhmedDowedar/Univy.git)
cd Univy


3. إنشاء بيئة افتراضية وتثبيت المكتبات

# إنشاء وتفعيل البيئة الافتراضية
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# تثبيت الاعتماديات
pip install -r requirements.txt


4. إعداد الملفات الحساسة

متغيرات البيئة:

# انسخ ملف المثال
cp .env.example .env


ثم افتح ملف .env واملأ جميع المتغيرات المطلوبة.

صلاحيات Google Drive:

اتبع هذا الدليل لإنشاء حساب خدمة (Service Account).

قم بتنزيل ملف الصلاحيات JSON وأعد تسميته إلى credentials.json.

هام: قم بدعوة بريد حساب الخدمة (e.g., ...gserviceaccount.com) إلى مجلد Google Drive الخاص بالكتب وامنحه صلاحية "Viewer".

5. تشغيل البوت

python main.py


والآن، يجب أن يكون بوت Univy جاهزاً للعمل!

🤝 المساهمة

نرحب بجميع المساهمات التي تجعل Univy أفضل. إذا كنت ترغب في المساهمة، يرجى الاطلاع على دليل المساهمة (CONTRIBUTING.md) للبدء.

📄 الرخصة

هذا المشروع مرخص تحت رخصة MIT. انظر ملف LICENSE لمزيد من التفاصيل.
