import feedparser
import os
import json
import smtplib
import re
from email.mime.text import MIMEText
from bs4 import BeautifulSoup

# ---------- Argos Translate ----------
import argostranslate.package
import argostranslate.translate

# ---------- 配置 ----------
SENDER_EMAIL = os.getenv("SMTP_USER")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL") or SENDER_EMAIL
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 465))
SMTP_PASS = os.getenv("SMTP_PASS")
RSS_URLS = [url.strip() for url in os.getenv("RSS_URLS", "").split(",") if url.strip()]
EMAIL_SUBJECT_PREFIX = "[RSS订阅更新] "
HISTORY_FILE = "processed.json"

if not all([SENDER_EMAIL, SMTP_SERVER, SMTP_PASS]):
    raise ValueError("请在 Secrets 中配置 SMTP_USER, SMTP_SERVER, SMTP_PASS")

if not RSS_URLS:
    raise ValueError("请在 Variables 中配置 RSS_URLS")

# URL检测
URL_PATTERN = re.compile(
    r"(https?://[^\s]+|www\.[^\s]+)",
    re.IGNORECASE
)

def should_translate(text):
    """
    判断一个文本节点是否需要翻译
    """

    text = text.strip()
    if not text:
        return False
    # 跳过纯URL
    if URL_PATTERN.fullmatch(text):
        return False
    # 跳过包含大量URL的文本
    if URL_PATTERN.search(text):
        return False
    # 跳过太短内容
    if len(text) <= 1:
        return False
    return True


def translate_html_preserve_tags(html_content, from_code="en", to_code="zh"):
    """
    翻译HTML文本内容
    保留:
    - HTML标签
    - 图片链接
    - 超链接
    - URL
    """
    soup = BeautifulSoup(html_content, "html.parser")
    # 不处理这些标签里面的内容
    skip_tags = {
        "script",
        "style",
        "code",
        "pre",
        "img",
        "a"
    }
    for element in soup.find_all(string=True):
        parent = element.parent
        # 父节点属于跳过标签
        if parent and parent.name in skip_tags:
            continue
        text = str(element)
        if not should_translate(text):
            continue
        try:
            translated = argostranslate.translate.translate(
                text,
                from_code,
                to_code
            )
            element.replace_with(translated)
        except Exception as e:
            print("翻译失败:", text[:50], e)
    return str(soup)

# ---------- HTML清理 ----------
def strip_html(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator="\n").strip()

# ---------- 历史记录 ----------
HISTORY_FILE = os.getenv("HISTORY_FILE", "processed.json")

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(history), f, ensure_ascii=False, indent=2)

history = load_history()
print("当前历史记录:", len(history))

from_code = "en"
to_code = "zh"

# Download and install Argos Translate package
argostranslate.package.update_package_index()
available_packages = argostranslate.package.get_available_packages()
package_to_install = next(
    filter(
        lambda x: x.from_code == from_code and x.to_code == to_code, available_packages
    )
)
argostranslate.package.install_from_path(package_to_install.download())

# ---------- 处理 RSS ----------
new_articles = []

for rss_url in RSS_URLS:
    feed = feedparser.parse(rss_url)
    for entry in feed.entries:
        if entry.link in history:
            continue

        title = entry.title
        # 兼容 content / summary / description
        content = getattr(entry, "content", None)
        if content:
            content = content[0].value if isinstance(content, list) else content
        else:
            content = getattr(entry, "summary", None) or getattr(entry, "description", None) or entry.title

        # HTML-aware 翻译
        translated_content = translate_html_preserve_tags(content, from_code, to_code)

        new_articles.append({
            "title": title,
            "link": entry.link,
            "translated": translated_content
        })
        history.add(entry.link)

# ---------- 保存历史 ----------
save_history(history)

# ---------- 发送邮件 ----------
if new_articles:
    email_content = ""
    for art in new_articles:
        email_content += f"标题: {art['title']}<br>链接: {art['link']}<br>内容摘要:{art['translated']}<br><br>{'-'*50}<br><br>"

    msg = MIMEText(email_content, "html", "utf-8")
    msg["Subject"] = EMAIL_SUBJECT_PREFIX + f"{len(new_articles)}篇新文章"
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SENDER_EMAIL, SMTP_PASS)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())

    print(f"邮件发送完成，共 {len(new_articles)} 篇新文章")
else:
    print("没有新文章，无需发送邮件")
