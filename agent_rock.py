import os
import json
import time
import re
from pathlib import Path

import requests
import telebot
from google import genai
from google.genai import types
from prompt_rock import build_rock_prompt


BASE_DIR = Path(__file__).resolve().parent

RECENT_POSTS_FILE = BASE_DIR / "recent_posts_rock.json"
RECENT_POSTS_LIMIT = 10

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL = os.getenv("ROCK_TELEGRAM_CHANNEL")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

if not TELEGRAM_CHANNEL:
    raise RuntimeError("TELEGRAM_CHANNEL is not set")

MODEL_NAME = os.getenv("ROCK_MODEL", "gemini-2.5-flash")

client = genai.Client(api_key=GEMINI_API_KEY)
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)


def load_recent_posts():
    if not RECENT_POSTS_FILE.exists():
        return []

    try:
        data = json.loads(RECENT_POSTS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(data, list):
        return []

    return data[-RECENT_POSTS_LIMIT:]


def save_recent_posts(posts):
    posts = posts[-RECENT_POSTS_LIMIT:]
    RECENT_POSTS_FILE.write_text(
        json.dumps(posts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clean_json_response(text):
    text = text.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    return text.strip()


def generate_rock_episode(recent_posts):
    prompt = build_prompt(recent_posts)

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=1.15,
            max_output_tokens=1200,
            response_mime_type="application/json",
        ),
    )

    text = clean_json_response(response.text)

    try:
        result = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Gemini returned invalid JSON: {text}"
        ) from exc

    if not isinstance(result, dict):
        raise RuntimeError("Gemini response is not an object")

    post = str(result.get("post", "")).strip()
    title = str(result.get("title", "")).strip()
    episode = result.get("episode")

    if not post:
        raise RuntimeError("Gemini returned an empty post")

    if not title:
        title = "Камень"

    if not isinstance(episode, int):
        episode = len(recent_posts) + 1

    return {
        "episode": episode,
        "title": title,
        "post": post,
    }


def build_prompt(recent_posts):
    return build_rock_prompt(recent_posts)


def publish_episode(episode):
    title = episode["title"]
    post = episode["post"]

    message = f"<b>{escape_html(title)}</b>\n\n{escape_html(post)}"

    sent = bot.send_message(
        TELEGRAM_CHANNEL,
        message,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    return sent


def escape_html(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def main():
    print("[ROCK] Starting rock episode generator")

    recent_posts = load_recent_posts()
    print(f"[ROCK] Loaded previous episodes: {len(recent_posts)}")

    episode = generate_rock_episode(recent_posts)

    print(f"[ROCK] Episode: {episode['episode']}")
    print(f"[ROCK] Title: {episode['title']}")
    print(f"[ROCK] Post: {episode['post']}")

    sent = publish_episode(episode)

    record = {
        "episode": episode["episode"],
        "title": episode["title"],
        "post": episode["post"],
        "telegram_message_id": sent.message_id,
        "created_at": int(time.time()),
    }

    recent_posts.append(record)
    save_recent_posts(recent_posts)

    print(
        f"[ROCK] Published successfully. "
        f"Saved {min(len(recent_posts), RECENT_POSTS_LIMIT)} recent episodes."
    )


if __name__ == "__main__":
    main()
