import feedparser
import os
import json
import smtplib
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
EMAIL_SUBJECT_PREFIX = "[RSS更新] "
HISTORY_FILE = "processed.json"

if not all([SENDER_EMAIL, SMTP_SERVER, SMTP_PASS]):
    raise ValueError("请在 Secrets 中配置 SMTP_USER, SMTP_SERVER, SMTP_PASS")

if not RSS_URLS:
    raise ValueError("请在 Variables 中配置 RSS_URLS")

def translate_html_preserve_tags(html_content, from_code="en", to_code="zh"):
    """
    翻译 HTML 中的文本内容，但保留 HTML 标签
    """
    soup = BeautifulSoup(html_content, "html.parser")

    # 遍历所有文本节点
    for element in soup.find_all(text=True):
        # 去掉只包含空白字符的节点
        if element.strip():
            translated_text = argostranslate.translate.translate(element, from_code, to_code)
            element.replace_with(translated_text)

    return str(soup)

# ---------- HTML清理 ----------
def strip_html(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator="\n").strip()

# ---------- 历史记录 ----------
if os.path.exists(HISTORY_FILE):
    history = set(json.load(open(HISTORY_FILE, "r", encoding="utf-8")))
else:
    history = set()

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
json.dump(list(history), open(HISTORY_FILE, "w", encoding="utf-8"))

# ---------- 发送邮件 ----------
if new_articles:
    email_content = ""
    for art in new_articles:
        email_content += f"标题: {art['title']}\n链接: {art['link']}\n内容摘要:\n{art['translated']}\n\n{'-'*50}\n\n"

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
