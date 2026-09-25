# agent.py

import os
import re
import json
import feedparser
import requests
from bs4 import BeautifulSoup
import trafilatura
from google.genai import client as genai
from pydantic import BaseModel

# Configuration and global variables
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-3.5-flash-lite"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@test_for_my_project")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

POSTED_FILE = "posted_urls.txt"
RSS_ARTICLES_PER_SOURCE = 3
MAX_SHORTLIST = 6

RSS_SOURCES = {
    "TechCrunch": "https://techcrunch.com/feed/",
    "The Verge": "https://www.theverge.com/rss/index.xml",
    "Habr News": "https://habr.com/ru/rss/news/?fl=ru",
    "3DNews": "https://3dnews.ru/news/rss/",
    "iXBT News": "https://www.ixbt.com/export/news.rss",
    # Добавьте другие RSS-ленты по необходимости
}

# Load posted URLs to avoid reposting
def load_posted_urls(file=POSTED_FILE):
    if not os.path.exists(file):
        return []
    with open(file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    return lines

# Save a new URL, keeping only the latest 500 entries
def save_posted_url(url, file=POSTED_FILE):
    posted = load_posted_urls(file)
    if url in posted:
        return
    posted.append(url)
    # keep only last 500
    if len(posted) > 500:
        posted = posted[-500:]
    with open(file, "w", encoding="utf-8") as f:
        for u in posted:
            f.write(u + "\n")

# Define output schema for shortlist
class ShortlistResult(BaseModel):
    indices: list[int]

# Define GenAI client
genai_client = genai.Client()
# Note: Ensure that GEMINI_API_KEY is set in environment for authentication

def fetch_news():
    news = []
    for source_name, rss_url in RSS_SOURCES.items():
        try:
            feed = feedparser.parse(rss_url)
        except Exception:
            continue
        if not feed or "entries" not in feed:
            continue
        for entry in feed.entries[:RSS_ARTICLES_PER_SOURCE]:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            summary = entry.get("summary", "") or entry.get("description", "")
            summary = re.sub(r"<[^>]+>", "", summary or "")
            summary = summary.strip()
            if title and link:
                news.append({
                    "source": source_name,
                    "title": title,
                    "url": link,
                    "summary": summary,
                })
    return news

# Shortlist news using Gemini
def shortlist_news(candidates):
    blocks = []
    for idx, item in enumerate(candidates, start=1):
        blocks.append(f"NEWS {idx}\nTitle: {item['title']}\nSummary: {item['summary'][:200]}\n")
    news_list_str = "\n".join(blocks)
    from prompts import SHORTLIST_PROMPT
    prompt = SHORTLIST_PROMPT.format(MAX_SHORTLIST=MAX_SHORTLIST, news=news_list_str)
    response = genai_client.chat(model=GEMINI_MODEL, prompt=prompt, temperature=0.2)
    text = response.text or response.content
    try:
        data = json.loads(text)
        result = ShortlistResult.parse_obj(data)
        indices = result.indices
    except Exception:
        found = re.findall(r"\d+", text)
        indices = [int(x) for x in found]
    indices = [i for i in indices if 1 <= i <= len(candidates)]
    return sorted(set([i - 1 for i in indices]), key=lambda x: x)

# Select best news using Gemini
def select_best_news(candidates):
    blocks = []
    for idx, item in enumerate(candidates):
        blocks.append(f"{idx}. {item['title']}")
    candidates_list = "\n".join(blocks)
    from prompts import SELECTION_PROMPT
    prompt = SELECTION_PROMPT.format(candidates=candidates_list)
    response = genai_client.chat(model=GEMINI_MODEL, prompt=prompt, temperature=0.2)
    text = response.text or response.content
    try:
        match = re.search(r"(\d+)", text)
        if match:
            choice = int(match.group(1))
        else:
            choice = 0
    except Exception:
        choice = 0
    if choice < 0 or choice >= len(candidates):
        choice = 0
    return choice

# Generate Telegram post text using Gemini
def generate_telegram_post(article):
    from prompts import POST_PROMPT
    prompt = POST_PROMPT.format(title=article["title"], content=article["summary"])
    response = genai_client.chat(model=GEMINI_MODEL, prompt=prompt, temperature=0.3)
    text = response.text or response.content
    text = re.sub(r"Источник\s*:\s*https?://\S+", "", text)
    text = text.strip()
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text

# Placeholder for image search (to be implemented as needed)
def search_image_for_article(article):
    return None

def post_to_telegram(text, image_url=None):
    payload = {
        "chat_id": TELEGRAM_CHANNEL,
        "parse_mode": "HTML"
    }
    if image_url:
        payload["photo"] = image_url
        payload["caption"] = text
        url = f"{TELEGRAM_API_URL}/sendPhoto"
    else:
        payload["text"] = text
        url = f"{TELEGRAM_API_URL}/sendMessage"
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print("[TG ERROR]", e)

def main():
    all_news = fetch_news()
    posted = load_posted_urls()
    new_news = [item for item in all_news if item["url"] not in posted]
    if not new_news:
        print("[INFO] No new news articles found.")
        return

    shortlist_indices = shortlist_news(new_news)
    shortlisted = [new_news[i] for i in shortlist_indices]
    if not shortlisted:
        print("[INFO] No shortlist candidates after filtering.")
        return

    best_idx = select_best_news(shortlisted)
    article = shortlisted[best_idx]
    print(f"[INFO] Selected article: {article['title']}")

    post_text = generate_telegram_post(article)

    source_line = f"Источник: {article['source']}"
    original_link = f'<a href="{article["url"]}">Оригинал</a>'
    final_message = f"{post_text}\n\n{source_line}\n{original_link}"

    image_url = search_image_for_article(article)
    post_to_telegram(final_message, image_url=image_url)

    save_posted_url(article["url"])

if __name__ == "__main__":
    main()
