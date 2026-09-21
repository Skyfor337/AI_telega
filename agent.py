import json
import os
import re
import time
import html
from io import BytesIO
from urllib.parse import (
    urljoin,
    urlparse,
    parse_qsl,
    urlencode,
    urlunparse,
)

import feedparser
import requests
import trafilatura

from bs4 import BeautifulSoup

from PIL import Image, ImageOps

from pydantic import BaseModel

from google import genai
from google.genai import types


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

GEMINI_MODEL = "gemini-3.5-flash-lite"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL")

TELEGRAM_API_URL = (
    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
)

POSTED_FILE = "posted_urls.txt"

RSS_ARTICLES_PER_SOURCE = 3

MAX_SHORTLIST = 6

MAX_RSS_SUMMARY_LENGTH = 1200

MAX_SELECTION_ARTICLE_LENGTH = 7000

MAX_POST_ARTICLE_LENGTH = 15000

GEMINI_SELECTION_TOKENS = 700

GEMINI_POST_TOKENS = 1200

GEMINI_RETRIES = 2

RSS_TIMEOUT = 25

ARTICLE_TIMEOUT = 35

IMAGE_TIMEOUT = 25

IMAGE_MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024

IMAGE_MIN_WIDTH = 500

IMAGE_MIN_HEIGHT = 300

IMAGE_MIN_AREA = 200000

IMAGE_MAX_RATIO = 3.5

IMAGE_MIN_RATIO = 0.45

TELEGRAM_PHOTO_CAPTION_LIMIT = 1024

TELEGRAM_TEXT_LIMIT = 4096

MAX_IMAGE_CANDIDATES = 40


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,image/avif,"
        "image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}


RSS_SOURCES = {
    "TechCrunch": (
        "https://techcrunch.com/feed/"
    ),
    "The Verge": (
        "https://www.theverge.com/rss/tech/index.xml"
    ),
    "Ars Technica": (
        "https://feeds.arstechnica.com/arstechnica/index"
    ),
    "WIRED AI": (
        "https://www.wired.com/feed/tag/ai/latest/rss"
    ),
    "Hacker News": (
        "https://news.ycombinator.com/rss"
    ),
    "VentureBeat AI": (
        "https://venturebeat.com/category/ai/feed/"
    ),
    "MIT Technology Review": (
        "https://www.technologyreview.com/feed/"
    ),
    "OpenAI": (
        "https://openai.com/news/rss.xml"
    ),
    "ZDNET": (
        "https://www.zdnet.com/news/rss.xml"
    ),
    "TechMeme": (
        "https://www.techmeme.com/feed.xml"
    ),
    "Fast Company": (
        "https://feeds.feedburner.com/fastcompany/headlines"
    ),
    "The Next Web": (
        "https://thenextweb.com/feed"
    ),
    "Android Authority": (
        "https://www.androidauthority.com/feed/"
    ),
    "Hugging Face": (
        "https://huggingface.co/blog/feed.xml"
    ),
    "IEEE Spectrum AI": (
        "https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss"
    ),
    "Habr News": (
        "https://habr.com/ru/rss/news/?fl=ru"
    ),
    "3DNews": (
        "https://3dnews.ru/news/rss/"
    ),
    "iXBT News": (
        "https://www.ixbt.com/export/news.rss"
    ),
}


IMAGE_BAD_KEYWORDS = {
    "logo",
    "logos",
    "icon",
    "icons",
    "favicon",
    "sprite",
    "avatar",
    "author",
    "profile",
    "placeholder",
    "default-image",
    "default_image",
    "defaultimage",
    "masthead",
    "wordmark",
    "badge",
    "tracking",
    "pixel",
    "emoji",
    "social-icon",
    "app-icon",
    "menu-icon",
    "search-icon",
    "play-button",
}


IMAGE_SOURCE_BONUS = {
    "rss_media": 65,
    "rss_thumbnail": 55,
    "rss_enclosure": 52,
    "og_image": 60,
    "og_image_secure": 58,
    "twitter_image": 48,
    "jsonld_image": 57,
    "image_src_link": 50,
    "article_image": 38,
    "generic_image": 20,
}


client = genai.Client(
    api_key=GEMINI_API_KEY
)


class ShortlistResult(BaseModel):
    indices: list[int]


class SelectionResult(BaseModel):
    selected_index: int
    reason: str


class PostResult(BaseModel):
    title: str
    post: str


SHORTLIST_SCHEMA = {
    "type": "object",
    "properties": {
        "indices": {
            "type": "array",
            "items": {
                "type": "integer",
            },
            "minItems": 1,
            "maxItems": MAX_SHORTLIST,
        },
    },
    "required": [
        "indices",
    ],
}


SELECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "selected_index": {
            "type": "integer",
        },
        "reason": {
            "type": "string",
        },
    },
    "required": [
        "selected_index",
        "reason",
    ],
}


POST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
        },
        "post": {
            "type": "string",
        },
    },
    "required": [
        "title",
        "post",
    ],
}


def normalize_url(url):
    if not url:
        return ""

    url = url.strip()

    try:
        parsed = urlparse(url)

        filtered_query = []

        for key, value in parse_qsl(
            parsed.query,
            keep_blank_values=True,
        ):
            lowered = key.lower()

            if lowered.startswith("utm_"):
                continue

            if lowered in {
                "fbclid",
                "gclid",
                "ref",
                "source",
                "campaign",
            }:
                continue

            filtered_query.append(
                (key, value)
            )

        normalized = urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path.rstrip("/"),
                parsed.params,
                urlencode(filtered_query),
                "",
            )
        )

        return normalized

    except Exception:
        return url


def clean_text(text):
    if not text:
        return ""

    text = BeautifulSoup(
        str(text),
        "html.parser",
    ).get_text(
        " ",
        strip=True,
    )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip()


def clean_multiline_text(text):
    if not text:
        return ""

    text = BeautifulSoup(
        str(text),
        "html.parser",
    ).get_text(
        "\n",
        strip=True,
    )

    lines = []

    for line in text.splitlines():
        line = re.sub(
            r"\s+",
            " ",
            line,
        ).strip()

        if line:
            lines.append(line)

    return "\n\n".join(lines)


def truncate_text(text, max_length):
    if not text:
        return ""

    text = text.strip()

    if len(text) <= max_length:
        return text

    truncated = text[:max_length]

    last_space = truncated.rfind(" ")

    if last_space > max_length * 0.75:
        truncated = truncated[:last_space]

    return truncated.rstrip() + "..."


def load_posted_urls():
    try:
        with open(
            POSTED_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            return {
                normalize_url(line)
                for line in file
                if normalize_url(line)
            }

    except FileNotFoundError:
        return set()

    except Exception as error:
        print(
            f"[STATE] Could not read "
            f"{POSTED_FILE}: {error}"
        )
        return set()


def save_posted_url(url):
    normalized = normalize_url(url)

    if not normalized:
        return

    try:
        with open(
            POSTED_FILE,
            "a",
            encoding="utf-8",
        ) as file:
            file.write(
                normalized + "\n"
            )

    except Exception as error:
        print(
            f"[STATE] Could not save URL: {error}"
        )


def get_entry_datetime(entry):
    for field in (
        "published_parsed",
        "updated_parsed",
        "created_parsed",
    ):
        parsed = entry.get(field)

        if parsed:
            try:
                return time.mktime(parsed)
            except Exception:
                pass

    return 0


def get_rss_text(entry):
    values = []

    summary = entry.get(
        "summary",
        "",
    )

    if summary:
        values.append(summary)

    description = entry.get(
        "description",
        "",
    )

    if description:
        values.append(description)

    content = entry.get(
        "content",
        [],
    )

    if content:
        for item in content:
            if isinstance(item, dict):
                value = item.get(
                    "value",
                    "",
                )

                if value:
                    values.append(value)

    for value in values:
        cleaned = clean_text(value)

        if cleaned:
            return truncate_text(
                cleaned,
                MAX_RSS_SUMMARY_LENGTH,
            )

    return ""


def extract_rss_image_candidates(entry):
    candidates = []

    media_content = entry.get(
        "media_content"
    )

    if media_content:
        for media in media_content:
            if not isinstance(
                media,
                dict,
            ):
                continue

            url = (
                media.get("url")
                or media.get("href")
            )

            if url:
                candidates.append(
                    {
                        "url": url,
                        "source": "rss_media",
                        "alt": "",
                    }
                )

    media_thumbnail = entry.get(
        "media_thumbnail"
    )

    if media_thumbnail:
        for media in media_thumbnail:
            if not isinstance(
                media,
                dict,
            ):
                continue

            url = (
                media.get("url")
                or media.get("href")
            )

            if url:
                candidates.append(
                    {
                        "url": url,
                        "source": "rss_thumbnail",
                        "alt": "",
                    }
                )

    enclosures = entry.get(
        "enclosures"
    )

    if enclosures:
        for enclosure in enclosures:
            if not isinstance(
                enclosure,
                dict,
            ):
                continue

            url = (
                enclosure.get("href")
                or enclosure.get("url")
            )

            mime_type = enclosure.get(
                "type",
                "",
            )

            if not url:
                continue

            if mime_type.startswith(
                "image/"
            ):
                candidates.append(
                    {
                        "url": url,
                        "source": "rss_enclosure",
                        "alt": "",
                    }
                )

    return candidates


def create_news_item(
    source_name,
    entry,
):
    title = clean_text(
        entry.get(
            "title",
            "Untitled",
        )
    )

    url = entry.get(
        "link",
        "",
    )

    url = normalize_url(url)

    if not title or not url:
        return None

    summary = get_rss_text(entry)

    return {
        "source": source_name,
        "title": title,
        "url": url,
        "summary": summary,
        "rss_entry": entry,
        "published_timestamp": (
            get_entry_datetime(entry)
        ),
    }


def get_news_from_rss():
    news = []

    seen_urls = set()

    for source_name, rss_url in RSS_SOURCES.items():
        try:
            response = requests.get(
                rss_url,
                timeout=RSS_TIMEOUT,
                headers=BROWSER_HEADERS,
                allow_redirects=True,
            )

            response.raise_for_status()

            feed = feedparser.parse(
                response.content
            )

            entries = list(
                feed.entries
            )

            entries.sort(
                key=get_entry_datetime,
                reverse=True,
            )

            added = 0

            for entry in entries:
                if added >= RSS_ARTICLES_PER_SOURCE:
                    break

                item = create_news_item(
                    source_name,
                    entry,
                )

                if not item:
                    continue

                normalized_url = item["url"]

                if normalized_url in seen_urls:
                    continue

                seen_urls.add(
                    normalized_url
                )

                news.append(item)

                added += 1

            print(
                f"[RSS] {source_name}: "
                f"{added} article(s)"
            )

        except requests.exceptions.HTTPError as error:
            print(
                f"[RSS] {source_name}: "
                f"HTTP error: {error}"
            )

        except requests.exceptions.Timeout:
            print(
                f"[RSS] {source_name}: "
                f"timeout"
            )

        except Exception as error:
            print(
                f"[RSS] {source_name}: "
                f"{error}"
            )

    return news


def filter_unposted_news(
    news,
    posted_urls,
):
    fresh = []

    for item in news:
        url = item["url"]

        if url in posted_urls:
            print(
                f"[SKIP] Already posted: "
                f"{item['title']}"
            )
            continue

        fresh.append(item)

    return fresh

def build_shortlist_prompt(news):
    blocks = []

    for index, item in enumerate(
        news,
        start=1,
    ):
        blocks.append(
            (
                f"NEWS {index}\n"
                f"Source: {item['source']}\n"
                f"Title: {item['title']}\n"
                f"URL: {item['url']}\n"
                f"Summary: "
                f"{truncate_text(item['summary'], 900)}\n"
            )
        )

    joined = "\n".join(blocks)

    prompt = f"""
You are the first-stage editor of a popular Russian Telegram
channel about AI, technology, gadgets and the modern digital
world.

You are given a large list of recent RSS stories.

Your task is to select up to {MAX_SHORTLIST} stories that
deserve a deeper review.

The channel is NOT a technical engineering channel and NOT
a developer-only news channel.

The target audience is broad. Readers may be interested
in technology and AI but may have no technical background.

The main question is:

"Would a normal technology-interested person want to open
this story and tell a friend about it?"

Prioritize stories that are:

- about major technology companies such as OpenAI, Google,
  Microsoft, Apple, NVIDIA, Meta, Amazon, Samsung, Xiaomi
  and similar companies
- about new AI models, AI assistants, ChatGPT, Gemini,
  Claude, DeepSeek and other widely known AI products
- about major product launches
- about new features in popular services
- about technologies that ordinary users can actually use
- about smartphones, computers, laptops, smart glasses,
  robots, cars, gadgets and consumer technology
- about surprising or unusual technological capabilities
- about major technological breakthroughs that can be
  explained simply
- about important changes that may affect how people use
  technology
- about major acquisitions or partnerships when they have
  clear technological significance
- about interesting and unusual technology stories
- about news with a strong "wow" or curiosity factor
- about stories that can be explained clearly in a short
  Telegram post

A story does NOT need to be technically complex to be valuable.

Broad audience appeal and real-world impact are more
important than technical depth.

A non-expert reader should be able to understand why the
story matters without specialized knowledge.

PRIORITY ORDER:

1. Major news from important technology companies.
2. Major AI model or AI product releases.
3. New capabilities that ordinary users can understand.
4. Major consumer technology and gadgets.
5. Robots, autonomous vehicles and other visible technologies.
6. Important changes to popular technology services.
7. Surprising technological discoveries or breakthroughs.
8. Interesting research with clear practical impact.
9. Developer or engineering news only when it has broad
   relevance.

LOW PRIORITY:

- narrow developer tools
- small framework updates
- minor benchmark improvements
- narrow programming news
- academic papers without obvious practical impact
- routine funding announcements
- routine corporate announcements
- conference announcements without an important announcement
- highly specialized engineering details
- technical infrastructure changes that ordinary users
  will not notice
- small startup news without broader technological significance
- generic business news
- opinion articles
- editorials
- tutorials
- how-to articles
- product reviews unless they contain an important
  newsworthy discovery

REJECT stories that are:

- mostly opinions
- mostly speculation
- clickbait without a meaningful technological event
- repetitive versions of another candidate
- extremely narrow or difficult to understand
- purely financial or corporate without meaningful
  technology impact
- old news presented as new
- stories where the actual technological event is unclear

IMPORTANT:

Do NOT automatically prefer technically sophisticated stories.

A simple story about a new ChatGPT feature used by millions
of people can be much more valuable than a technically
impressive but extremely narrow machine-learning research
result.

Prefer concrete events over abstract analysis.

Prefer "something happened" over "someone discussed something".

Prefer stories with a clear subject, a clear event and a clear
reason why readers should care.

The final selection should feel like a feed from a large
popular technology channel, not a feed for software engineers
or AI researchers.

Use ONLY the information visible in the provided RSS data.

Do not invent facts.

Return ONLY JSON matching the requested response schema.

Return the indices of the best {MAX_SHORTLIST} candidates,
or fewer if fewer than {MAX_SHORTLIST} stories are genuinely
interesting.

NEWS:

{joined}
"""

    return prompt



def build_selection_prompt(
    candidates,
):
    blocks = []

    for index, item in enumerate(
        candidates,
        start=1,
    ):
        article_text = item.get(
            "text",
            "",
        )

        if not article_text:
            article_text = item.get(
                "summary",
                "",
            )

        article_text = truncate_text(
            article_text,
            MAX_SELECTION_ARTICLE_LENGTH,
        )

        blocks.append(
            (
                f"NEWS {index}\n"
                f"Source: {item['source']}\n"
                f"Title: {item['title']}\n"
                f"URL: {item['url']}\n"
                f"Text:\n"
                f"{article_text}\n"
            )
        )

    joined = "\n".join(blocks)

    prompt = f"""
You are the final editor of a popular Russian Telegram channel about AI, technology and the modern digital world.

You must choose exactly ONE news story from the provided candidates.

The channel targets a broad audience interested in technology, AI, gadgets and major technology companies.

The reader does not need to be a programmer or engineer.

Choose the story that has the strongest combination of:

1. Broad audience appeal
2. Real-world impact
3. Clear and understandable news event
4. Novelty and timeliness
5. Importance of the company, product or technology involved
6. "Wow" or curiosity factor
7. Potential to be explained clearly in a short Telegram post
8. Source quality and reliability
9. Technical substance only as a secondary factor

The most technically complex story is NOT automatically the best story.

A major new AI feature, smartphone, robot, gadget or product launch can be more suitable than a highly specialized engineering or research story.

Prefer stories where the reader can immediately understand:

- what happened
- what is new
- why it matters
- who may be affected

Strongly prefer:

- OpenAI / ChatGPT news
- Google / Gemini news
- Microsoft news
- Apple news
- NVIDIA news
- Meta news
- Amazon news
- Samsung news
- Xiaomi and other major consumer technology companies
- major AI model releases
- new AI capabilities
- popular AI products
- smartphones and computers
- robots
- smart glasses
- autonomous vehicles
- major gadgets
- important changes to popular services
- unusual technological achievements
- technologies that may become widely used

Lower priority:

- narrow developer tools
- minor framework updates
- benchmarks
- academic papers without practical impact
- routine funding
- small startups
- highly specialized engineering
- technical infrastructure
- generic corporate announcements
- opinion and analysis

Do NOT choose a story simply because it sounds technically impressive.

Choose the story most likely to make a broad technology audience stop scrolling and read the post.

Return ONLY the zero-based index of the selected candidate.

Example:
3

CANDIDATES:

{joined}
"""

    return prompt


def build_post_prompt(article):
    article_text = truncate_text(
        article.get(
            "text",
            "",
        ),
        MAX_POST_ARTICLE_LENGTH,
    )

    if not article_text:
        article_text = truncate_text(
            article.get(
                "summary",
                "",
            ),
            MAX_POST_ARTICLE_LENGTH,
        )

    prompt = f"""
You are a Russian-language editor for a popular Telegram channel about AI, technology, gadgets and the modern digital world.

Write a short Telegram news post based ONLY on the provided article information.

The audience is broad.

Readers may know very little about technology, AI or programming.

The post must feel like an interesting news story from a popular technology channel, not like a technical article.

FIRST explain what happened.

THEN explain what is new or unusual.

THEN explain why it matters to ordinary users or to the technology industry.

Use technical details only when they help explain the story.

Avoid unnecessary technical terminology.

If a technical term is necessary, explain it in simple Russian.

The post should be interesting even to someone who is not a programmer.

STYLE:

- Russian language
- 2-4 short paragraphs
- approximately 500-800 characters
- maximum 2 emojis
- natural modern Russian
- concise and informative
- no excessive hype
- no clickbait
- no generic introduction
- no "according to experts" unless the source explicitly says so
- no invented facts
- no speculation presented as fact
- do not copy sentences from the source
- paraphrase the information in your own words

The first sentence should immediately tell the reader what happened.

Prefer concrete wording.

BAD:

"Компания представила новую мультимодальную foundation model с улучшенными возможностями обработки различных типов данных."

BETTER:

"Google представила новую версию Gemini, которая стала лучше работать сразу с текстом, изображениями и видео."

The reader should understand the main point without reading the source article.

At the end, add the original source URL on a separate line in this exact format:

Источник: <URL>

Return ONLY the finished Telegram post.

SOURCE:
{article['source']}

ORIGINAL TITLE:
{article['title']}

URL:
{article['url']}

ARTICLE TEXT:

{article_text}
"""

    return prompt


def gemini_request(
    prompt,
    stage,
    schema,
    max_output_tokens,
):
    for attempt in range(
        1,
        GEMINI_RETRIES + 1,
    ):
        try:
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=0.2,
                max_output_tokens=max_output_tokens,
            )

            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=config,
            )

            text = response.text

            if not text:
                print(
                    f"[AI] {stage}: "
                    f"empty response "
                    f"(attempt {attempt})"
                )

                if attempt < GEMINI_RETRIES:
                    time.sleep(2)
                    continue

                return None

            print(
                f"[AI] {stage}: OK"
            )

            return text

        except Exception as error:
            print(
                f"[AI] {stage}: "
                f"error on attempt "
                f"{attempt}: {error}"
            )

            if attempt < GEMINI_RETRIES:
                time.sleep(2)

    return None


def parse_json_response(
    text,
):
    if not text:
        return None

    text = text.strip()

    try:
        return json.loads(text)

    except json.JSONDecodeError:
        pass

    cleaned = re.sub(
        r"^```json\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"^```\s*",
        "",
        cleaned,
    )

    cleaned = re.sub(
        r"\s*```$",
        "",
        cleaned,
    )

    try:
        return json.loads(
            cleaned.strip()
        )

    except json.JSONDecodeError:
        pass

    match = re.search(
        r"\{.*\}",
        text,
        re.DOTALL,
    )

    if match:
        try:
            return json.loads(
                match.group(0)
            )
        except json.JSONDecodeError:
            return None

    return None


def shortlist_news(news):
    if not news:
        return []

    print(
        "[AI] Building shortlist..."
    )

    prompt = build_shortlist_prompt(
        news
    )

    response = gemini_request(
        prompt=prompt,
        stage="Shortlist",
        schema=SHORTLIST_SCHEMA,
        max_output_tokens=400,
    )

    if not response:
        return []

    result = parse_json_response(
        response
    )

    if not result:
        print(
            "[AI] Shortlist: "
            "could not parse response"
        )
        return []

    indices = result.get(
        "indices"
    )

    if not isinstance(
        indices,
        list,
    ):
        print(
            "[AI] Shortlist: "
            "invalid indices"
        )
        return []

    valid_indices = []

    for index in indices:
        if not isinstance(
            index,
            int,
        ):
            continue

        if index < 1:
            continue

        if index > len(news):
            continue

        if index in valid_indices:
            continue

        valid_indices.append(
            index
        )

        if len(valid_indices) >= MAX_SHORTLIST:
            break

    if not valid_indices:
        return []

    selected = [
        news[index - 1]
        for index in valid_indices
    ]

    print(
        f"[AI] Shortlist size: "
        f"{len(selected)}"
    )

    for item in selected:
        print(
            f"[AI] Candidate: "
            f"{item['source']} | "
            f"{item['title']}"
        )

    return selected


def fetch_article_page(url):
    response = requests.get(
        url,
        timeout=ARTICLE_TIMEOUT,
        headers=BROWSER_HEADERS,
        allow_redirects=True,
    )

    response.raise_for_status()

    return response.text


def parse_article_html(
    html_text,
):
    if not html_text:
        return None

    try:
        text = trafilatura.extract(
            html_text,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
            favor_recall=False,
        )

        if text:
            text = clean_multiline_text(
                text
            )

            if len(text) >= 400:
                return text

    except Exception as error:
        print(
            f"[PARSE] trafilatura error: "
            f"{error}"
        )

    return None


def parse_article(
    url,
):
    try:
        html_text = fetch_article_page(
            url
        )

        text = parse_article_html(
            html_text
        )

        if text:
            return {
                "text": text,
                "html": html_text,
            }

        print(
            "[PARSE] Article text "
            "was too short"
        )

        return {
            "text": None,
            "html": html_text,
        }

    except requests.exceptions.HTTPError as error:
        print(
            f"[PARSE] HTTP error for "
            f"{url}: {error}"
        )
        return {
            "text": None,
            "html": None,
        }

    except requests.exceptions.Timeout:
        print(
            f"[PARSE] Timeout for "
            f"{url}"
        )
        return {
            "text": None,
            "html": None,
        }

    except Exception as error:
        print(
            f"[PARSE] Error for "
            f"{url}: {error}"
        )
        return {
            "text": None,
            "html": None,
        }


def enrich_candidate(
    article,
):
    parsed = parse_article(
        article["url"]
    )

    article["page_html"] = (
        parsed["html"]
    )

    text = parsed["text"]

    if text:
        article["text"] = text
        return True

    fallback = article.get(
        "summary",
        "",
    )

    if fallback:
        print(
            "[PARSE] Using RSS summary "
            "fallback"
        )

        article["text"] = fallback

        return True

    print(
        "[PARSE] No usable text: "
        f"{article['title']}"
    )

    return False


def build_article_candidates(
    shortlist,
):
    valid = []

    for article in shortlist:
        print(
            f"[PARSE] "
            f"{article['source']} | "
            f"{article['title']}"
        )

        if enrich_candidate(
            article
        ):
            valid.append(article)

    print(
        f"[PARSE] Valid articles: "
        f"{len(valid)}"
    )

    return valid


def select_best_news(
    candidates,
):
    if not candidates:
        return None

    if len(candidates) == 1:
        print(
            "[AI] Only one valid "
            "candidate"
        )
        return candidates[0]

    print(
        "[AI] Selecting news..."
    )

    prompt = build_selection_prompt(
        candidates
    )

    response = gemini_request(
        prompt=prompt,
        stage="Selection",
        schema=SELECTION_SCHEMA,
        max_output_tokens=700,
    )

    if not response:
        return None

    result = parse_json_response(
        response
    )

    if not result:
        print(
            "[AI] Selection: "
            "could not parse response"
        )
        return None

    selected_index = result.get(
        "selected_index"
    )

    if not isinstance(
        selected_index,
        int,
    ):
        print(
            "[AI] Selection: "
            "invalid selected_index"
        )
        return None

    if not (
        1 <= selected_index <= len(candidates)
    ):
        print(
            "[AI] Selection: "
            "selected_index out of range"
        )
        return None

    selected = candidates[
        selected_index - 1
    ]

    reason = result.get(
        "reason",
        "",
    )

    reason = clean_text(
        reason
    )

    print(
        f"[AI] Selected: "
        f"{selected['source']} | "
        f"{selected['title']}"
    )

    if reason:
        print(
            f"[AI] Reason: {reason}"
        )

    return selected


def generate_telegram_post(
    article,
):
    print(
        "[AI] Writing post..."
    )

    prompt = build_post_prompt(
        article
    )

    response = gemini_request(
        prompt=prompt,
        stage="Post generation",
        schema=POST_SCHEMA,
        max_output_tokens=GEMINI_POST_TOKENS,
    )

    if not response:
        return None

    result = parse_json_response(
        response
    )

    if not result:
        print(
            "[AI] Post generation: "
            "could not parse response"
        )
        return None

    title = clean_text(
        result.get(
            "title",
            "",
        )
    )

    post = clean_multiline_text(
        result.get(
            "post",
            "",
        )
    )

    if not title:
        print(
            "[AI] Post generation: "
            "empty title"
        )
        return None

    if not post:
        print(
            "[AI] Post generation: "
            "empty post"
        )
        return None

    post = post.replace(
        "\r\n",
        "\n",
    )

    return {
        "title": title,
        "post": post,
        "source": article["source"],
        "url": article["url"],
    }


def normalize_image_url(
    image_url,
    page_url,
):
    if not image_url:
        return None

    image_url = image_url.strip()

    if image_url.startswith(
        "data:"
    ):
        return None

    if image_url.startswith(
        "//"
    ):
        image_url = (
            "https:" + image_url
        )

    image_url = urljoin(
        page_url,
        image_url,
    )

    parsed = urlparse(
        image_url
    )

    if parsed.scheme not in {
        "http",
        "https",
    }:
        return None

    return image_url


def get_image_source_priority(
    source,
):
    return IMAGE_SOURCE_BONUS.get(
        source,
        10,
    )


def append_image_candidate(
    candidates,
    seen,
    url,
    source,
    page_url,
    alt="",
):
    normalized = normalize_image_url(
        url,
        page_url,
    )

    if not normalized:
        return

    key = normalize_url(
        normalized
    )

    if not key:
        return

    if key in seen:
        return

    seen.add(key)

    candidates.append(
        {
            "url": normalized,
            "source": source,
            "alt": clean_text(alt),
        }
    )


def extract_srcset_urls(
    value,
):
    if not value:
        return []

    results = []

    parts = value.split(",")

    for part in parts:
        part = part.strip()

        if not part:
            continue

        pieces = part.split()

        if not pieces:
            continue

        url = pieces[0]

        descriptor = 0

        if len(pieces) > 1:
            value_part = pieces[1]

            match = re.match(
                r"(\d+(?:\.\d+)?)(w|x)",
                value_part,
                re.IGNORECASE,
            )

            if match:
                try:
                    descriptor = float(
                        match.group(1)
                    )
                except Exception:
                    descriptor = 0

        results.append(
            (
                url,
                descriptor,
            )
        )

    results.sort(
        key=lambda item: item[1],
        reverse=True,
    )

    return [
        url
        for url, _ in results
    ]


def extract_jsonld_images(
    value,
):
    results = []

    if value is None:
        return results

    if isinstance(
        value,
        str,
    ):
        results.append(value)
        return results

    if isinstance(
        value,
        list,
    ):
        for item in value:
            results.extend(
                extract_jsonld_images(
                    item
                )
            )

        return results

    if isinstance(
        value,
        dict,
    ):
        for key in (
            "image",
            "contentUrl",
            "thumbnailUrl",
        ):
            if key in value:
                results.extend(
                    extract_jsonld_images(
                        value[key]
                    )
                )

        return results

    return results


def extract_page_image_candidates(
    html_text,
    page_url,
    article_title,
):
    candidates = []

    seen = set()

    if not html_text:
        return candidates

    soup = BeautifulSoup(
        html_text,
        "html.parser",
    )

    meta_selectors = [
        (
            "meta",
            {
                "property": "og:image",
            },
            "og_image",
        ),
        (
            "meta",
            {
                "property": "og:image:url",
            },
            "og_image",
        ),
        (
            "meta",
            {
                "property": "og:image:secure_url",
            },
            "og_image_secure",
        ),
        (
            "meta",
            {
                "name": "twitter:image",
            },
            "twitter_image",
        ),
        (
            "meta",
            {
                "name": "twitter:image:src",
            },
            "twitter_image",
        ),
    ]

    for tag_name, attrs, source in meta_selectors:
        tags = soup.find_all(
            tag_name,
            attrs=attrs,
        )

        for tag in tags:
            content = tag.get(
                "content"
            )

            append_image_candidate(
                candidates,
                seen,
                content,
                source,
                page_url,
                article_title,
            )

    link_image = soup.find(
        "link",
        rel=lambda value: (
            value
            and "image_src" in value
            if isinstance(
                value,
                list,
            )
            else value == "image_src"
        ),
    )

    if link_image:
        append_image_candidate(
            candidates,
            seen,
            link_image.get("href"),
            "image_src_link",
            page_url,
            article_title,
        )

    jsonld_scripts = soup.find_all(
        "script",
        type="application/ld+json",
    )

    for script in jsonld_scripts:
        raw = script.string

        if not raw:
            raw = script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(
                raw
            )
        except Exception:
            continue

        images = extract_jsonld_images(
            data
        )

        for image_url in images:
            append_image_candidate(
                candidates,
                seen,
                image_url,
                "jsonld_image",
                page_url,
                article_title,
            )

    article_containers = []

    main = soup.find(
        "main"
    )

    if main:
        article_containers.append(
            main
        )

    article_tag = soup.find(
        "article"
    )

    if article_tag:
        article_containers.append(
            article_tag
        )

    for container in article_containers:
        images = container.find_all(
            "img",
            limit=20,
        )

        for image in images:
            alt = image.get(
                "alt",
                "",
            )

            src = (
                image.get("src")
                or image.get("data-src")
                or image.get("data-original")
                or image.get("data-lazy-src")
            )

            if src:
                append_image_candidate(
                    candidates,
                    seen,
                    src,
                    "article_image",
                    page_url,
                    alt,
                )

            srcset_values = [
                image.get("srcset"),
                image.get("data-srcset"),
            ]

            for srcset in srcset_values:
                for srcset_url in (
                    extract_srcset_urls(
                        srcset
                    )
                ):
                    append_image_candidate(
                        candidates,
                        seen,
                        srcset_url,
                        "article_image",
                        page_url,
                        alt,
                    )

    all_images = soup.find_all(
        "img",
        limit=MAX_IMAGE_CANDIDATES,
    )

    for image in all_images:
        alt = image.get(
            "alt",
            "",
        )

        src = (
            image.get("src")
            or image.get("data-src")
            or image.get("data-original")
            or image.get("data-lazy-src")
        )

        if src:
            append_image_candidate(
                candidates,
                seen,
                src,
                "generic_image",
                page_url,
                alt,
            )

        srcset_values = [
            image.get("srcset"),
            image.get("data-srcset"),
        ]

        for srcset in srcset_values:
            for srcset_url in (
                extract_srcset_urls(
                    srcset
                )
            ):
                append_image_candidate(
                    candidates,
                    seen,
                    srcset_url,
                    "generic_image",
                    page_url,
                    alt,
                )

    return candidates


def image_url_looks_bad(
    image_url,
    alt="",
):
    source = (
        f"{image_url} {alt}"
    ).lower()

    for keyword in IMAGE_BAD_KEYWORDS:
        if keyword in source:
            return True

    return False


def title_token_set(
    text,
):
    if not text:
        return set()

    text = text.lower()

    tokens = re.findall(
        r"[a-zA-Zа-яА-Я0-9]{3,}",
        text,
    )

    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "into",
        "your",
        "new",
        "how",
        "why",
        "что",
        "это",
        "как",
        "для",
        "новый",
        "новая",
        "про",
    }

    return {
        token
        for token in tokens
        if token not in stop_words
    }


def calculate_text_overlap(
    title,
    alt,
):
    title_tokens = title_token_set(
        title
    )

    alt_tokens = title_token_set(
        alt
    )

    if not title_tokens:
        return 0

    overlap = (
        title_tokens
        & alt_tokens
    )

    return len(overlap)


def download_image_bytes(
    image_url,
):
    try:
        response = requests.get(
            image_url,
            timeout=IMAGE_TIMEOUT,
            headers={
                **BROWSER_HEADERS,
                "Accept": (
                    "image/avif,image/webp,"
                    "image/apng,image/svg+xml,"
                    "image/*,*/*;q=0.8"
                ),
                "Referer": image_url,
            },
            allow_redirects=True,
            stream=True,
        )

        response.raise_for_status()

        content_type = response.headers.get(
            "Content-Type",
            "",
        ).lower()

        if (
            "image" not in content_type
            and not image_url.lower().endswith(
                (
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".webp",
                    ".gif",
                    ".bmp",
                )
            )
        ):
            return None

        content_length = response.headers.get(
            "Content-Length"
        )

        if content_length:
            try:
                if int(content_length) > (
                    IMAGE_MAX_DOWNLOAD_BYTES
                ):
                    return None
            except ValueError:
                pass

        data = BytesIO()

        downloaded = 0

        for chunk in response.iter_content(
            chunk_size=64 * 1024
        ):
            if not chunk:
                continue

            downloaded += len(chunk)

            if downloaded > IMAGE_MAX_DOWNLOAD_BYTES:
                return None

            data.write(chunk)

        return data.getvalue()

    except Exception:
        return None


def inspect_image_bytes(
    image_bytes,
):
    if not image_bytes:
        return None

    try:
        image = Image.open(
            BytesIO(image_bytes)
        )

        image.load()

        width, height = image.size

        image_format = (
            image.format
            or ""
        ).upper()

        if width < IMAGE_MIN_WIDTH:
            return None

        if height < IMAGE_MIN_HEIGHT:
            return None

        area = width * height

        if area < IMAGE_MIN_AREA:
            return None

        ratio = width / height

        if ratio < IMAGE_MIN_RATIO:
            return None

        if ratio > IMAGE_MAX_RATIO:
            return None

        return {
            "width": width,
            "height": height,
            "area": area,
            "ratio": ratio,
            "format": image_format,
        }

    except Exception:
        return None


def score_image_candidate(
    candidate,
    image_info,
    article_title,
):
    score = get_image_source_priority(
        candidate["source"]
    )

    width = image_info["width"]
    height = image_info["height"]
    area = image_info["area"]
    ratio = image_info["ratio"]

    image_url = candidate["url"]
    alt = candidate.get(
        "alt",
        "",
    )

    if image_url_looks_bad(
        image_url,
        alt,
    ):
        score -= 100

    overlap = calculate_text_overlap(
        article_title,
        alt,
    )

    score += min(
        overlap * 5,
        20,
    )

    if width >= 1200:
        score += 15

    elif width >= 900:
        score += 10

    elif width >= 700:
        score += 5

    if height >= 700:
        score += 5

    if (
        1.2 <= ratio <= 2.3
    ):
        score += 10

    elif (
        0.8 <= ratio <= 1.2
    ):
        score += 4

    elif (
        ratio < 0.6
        or ratio > 3.0
    ):
        score -= 15

    if area >= 2_000_000:
        score += 8

    elif area >= 1_000_000:
        score += 5

    return score


def get_article_image(
    article,
):
    print(
        "[IMAGE] Searching for "
        "best image..."
    )

    candidates = []

    seen = set()

    rss_candidates = (
        extract_rss_image_candidates(
            article.get(
                "rss_entry",
                {},
            )
        )
    )

    for candidate in rss_candidates:
        append_image_candidate(
            candidates,
            seen,
            candidate["url"],
            candidate["source"],
            article["url"],
            candidate.get(
                "alt",
                "",
            ),
        )

    page_html = article.get(
        "page_html"
    )

    if not page_html:
        try:
            page_html = fetch_article_page(
                article["url"]
            )

            article["page_html"] = (
                page_html
            )

        except Exception as error:
            print(
                f"[IMAGE] Could not "
                f"fetch article page: "
                f"{error}"
            )

    if page_html:
        page_candidates = (
            extract_page_image_candidates(
                page_html,
                article["url"],
                article["title"],
            )
        )

        for candidate in page_candidates:
            append_image_candidate(
                candidates,
                seen,
                candidate["url"],
                candidate["source"],
                article["url"],
                candidate.get(
                    "alt",
                    "",
                ),
            )

    if not candidates:
        print(
            "[IMAGE] No image candidates"
        )
        return None

    candidates = candidates[
        :MAX_IMAGE_CANDIDATES
    ]

    scored = []

    for index, candidate in enumerate(
        candidates,
        start=1,
    ):
        image_bytes = (
            download_image_bytes(
                candidate["url"]
            )
        )

        if not image_bytes:
            continue

        image_info = inspect_image_bytes(
            image_bytes
        )

        if not image_info:
            continue

        score = score_image_candidate(
            candidate,
            image_info,
            article["title"],
        )

        if score < 0:
            continue

        scored.append(
            {
                "url": candidate["url"],
                "source": candidate["source"],
                "alt": candidate.get(
                    "alt",
                    "",
                ),
                "score": score,
                "data": image_bytes,
                **image_info,
            }
        )

    if not scored:
        print(
            "[IMAGE] No usable images"
        )
        return None

    scored.sort(
        key=lambda item: (
            item["score"],
            item["area"],
        ),
        reverse=True,
    )

    best = scored[0]

    print(
        f"[IMAGE] Selected: "
        f"{best['source']} | "
        f"{best['width']}x"
        f"{best['height']} | "
        f"score={best['score']}"
    )

    return best


def prepare_image_for_telegram(
    image_bytes,
):
    try:
        image = Image.open(
            BytesIO(image_bytes)
        )

        image = ImageOps.exif_transpose(
            image
        )

        max_dimension = 2000

        width, height = image.size

        if max(
            width,
            height,
        ) > max_dimension:
            scale = (
                max_dimension
                / max(width, height)
            )

            new_size = (
                max(
                    1,
                    int(width * scale),
                ),
                max(
                    1,
                    int(height * scale),
                ),
            )

            image = image.resize(
                new_size,
                Image.Resampling.LANCZOS,
            )

        if image.mode in {
            "RGBA",
            "LA",
        }:
            background = Image.new(
                "RGB",
                image.size,
                "white",
            )

            alpha = image.getchannel(
                "A"
            )

            background.paste(
                image,
                mask=alpha,
            )

            image = background

        elif image.mode != "RGB":
            image = image.convert(
                "RGB"
            )

        output = BytesIO()

        image.save(
            output,
            format="JPEG",
            quality=90,
            optimize=True,
            progressive=True,
        )

        return output.getvalue()

    except Exception as error:
        print(
            f"[IMAGE] Preparation error: "
            f"{error}"
        )
        return None


def telegram_escape(
    text,
):
    return html.escape(
        str(text),
        quote=False,
    )


def truncate_telegram_post(
    title,
    post,
    source,
    url,
):
    safe_title = telegram_escape(
        title
    )

    safe_post = telegram_escape(
        post
    )

    safe_source = telegram_escape(
        source
    )

    safe_url = html.escape(
        url,
        quote=True,
    )

    ending = (
        f"\n\nИсточник: "
        f"{safe_source}\n"
        f'<a href="{safe_url}">'
        f"Оригинал"
        f"</a>"
    )

    prefix = (
        f"<b>{safe_title}</b>\n\n"
    )

    available = (
        TELEGRAM_PHOTO_CAPTION_LIMIT
        - len(prefix)
        - len(ending)
    )

    if available < 50:
        available = 50

    if len(safe_post) > available:
        safe_post = (
            safe_post[
                :available - 3
            ].rstrip()
            + "..."
        )

        while (
            len(prefix)
            + len(safe_post)
            + len(ending)
            > TELEGRAM_PHOTO_CAPTION_LIMIT
        ):
            safe_post = (
                safe_post[:-4].rstrip()
                + "..."
            )

    caption = (
        prefix
        + safe_post
        + ending
    )

    if len(caption) > (
        TELEGRAM_PHOTO_CAPTION_LIMIT
    ):
        caption = caption[
            :TELEGRAM_PHOTO_CAPTION_LIMIT
        ]

    return caption


def build_text_message(
    title,
    post,
    source,
    url,
):
    safe_title = telegram_escape(
        title
    )

    safe_post = telegram_escape(
        post
    )

    safe_source = telegram_escape(
        source
    )

    safe_url = html.escape(
        url,
        quote=True,
    )

    text = (
        f"<b>{safe_title}</b>\n\n"
        f"{safe_post}\n\n"
        f"Источник: {safe_source}\n"
        f'<a href="{safe_url}">'
        f"Оригинал"
        f"</a>"
    )

    if len(text) > (
        TELEGRAM_TEXT_LIMIT
    ):
        text = text[
            :TELEGRAM_TEXT_LIMIT
        ]

    return text


def telegram_request(
    method,
    data=None,
    files=None,
):
    url = (
        f"{TELEGRAM_API_URL}/"
        f"{method}"
    )

    try:
        response = requests.post(
            url,
            data=data,
            files=files,
            timeout=60,
        )

        try:
            result = response.json()

        except ValueError:
            print(
                f"[TG] Invalid Telegram "
                f"response: "
                f"{response.text[:1000]}"
            )
            return None

        if not result.get(
            "ok",
            False,
        ):
            print(
                f"[TG] Error "
                f"{result.get('error_code')}: "
                f"{result.get('description')}"
            )
            return None

        return result

    except requests.exceptions.Timeout:
        print(
            "[TG] Request timeout"
        )
        return None

    except requests.exceptions.RequestException as error:
        print(
            f"[TG] Connection error: "
            f"{error}"
        )
        return None

    except Exception as error:
        print(
            f"[TG] Unexpected error: "
            f"{error}"
        )
        return None


def test_telegram_bot():
    url = (
        f"{TELEGRAM_API_URL}/getMe"
    )

    try:
        response = requests.get(
            url,
            timeout=20,
        )

        result = response.json()

        if result.get(
            "ok",
            False,
        ):
            bot = result.get(
                "result",
                {},
            )

            print(
                f"[TG] Bot OK: "
                f"@{bot.get('username')}"
            )

            return True

        print(
            f"[TG] Bot test failed: "
            f"{result}"
        )

        return False

    except Exception as error:
        print(
            f"[TG] Bot test error: "
            f"{error}"
        )
        return False


def publish_to_telegram(
    post,
    image_info=None,
):
    title = post["title"]
    text = post["post"]
    source = post["source"]
    url = post["url"]

    caption = (
        truncate_telegram_post(
            title,
            text,
            source,
            url,
        )
    )

    if image_info:
        image_data = (
            prepare_image_for_telegram(
                image_info["data"]
            )
        )

        if image_data:
            print(
                "[TG] Publishing "
                "photo post..."
            )

            files = {
                "photo": (
                    "news.jpg",
                    BytesIO(
                        image_data
                    ),
                    "image/jpeg",
                )
            }

            data = {
                "chat_id": TELEGRAM_CHANNEL,
                "caption": caption,
                "parse_mode": "HTML",
            }

            result = telegram_request(
                "sendPhoto",
                data=data,
                files=files,
            )

            if result:
                print(
                    "[TG] Published "
                    "photo successfully"
                )
                return True

            print(
                "[TG] Photo publication "
                "failed"
            )

    print(
        "[TG] Publishing "
        "text post..."
    )

    message = build_text_message(
        title,
        text,
        source,
        url,
    )

    result = telegram_request(
        "sendMessage",
        data={
            "chat_id": TELEGRAM_CHANNEL,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        },
    )

    if result:
        print(
            "[TG] Published text "
            "successfully"
        )
        return True

    print(
        "[TG] Text publication failed"
    )

    return False


def validate_configuration():
    errors = []

    if not GEMINI_API_KEY:
        errors.append(
            "GEMINI_API_KEY is empty"
        )

    if (
        GEMINI_API_KEY
        == "PASTE_GEMINI_API_KEY_HERE"
    ):
        errors.append(
            "GEMINI_API_KEY was not set"
        )

    if not TELEGRAM_BOT_TOKEN:
        errors.append(
            "TELEGRAM_BOT_TOKEN is empty"
        )

    if (
        TELEGRAM_BOT_TOKEN
        == "PASTE_TELEGRAM_BOT_TOKEN_HERE"
    ):
        errors.append(
            "TELEGRAM_BOT_TOKEN "
            "was not set"
        )

    if not TELEGRAM_CHANNEL:
        errors.append(
            "TELEGRAM_CHANNEL is empty"
        )

    if (
        TELEGRAM_CHANNEL
        == "@PASTE_CHANNEL_USERNAME_HERE"
    ):
        errors.append(
            "TELEGRAM_CHANNEL "
            "was not set"
        )

    if errors:
        print(
            "[CONFIG] Configuration "
            "errors:"
        )

        for error in errors:
            print(
                f"[CONFIG] {error}"
            )

        return False

    return True


def print_selected_post(
    post,
):
    print()
    print(
        "[TG POST]"
    )
    print(
        post["title"]
    )
    print()
    print(
        post["post"]
    )
    print()
    print(
        f"Источник: "
        f"{post['source']}"
    )
    print(
        post["url"]
    )
    print()


def main():
    print(
        "[START] News agent"
    )

    if not validate_configuration():
        return

    if not test_telegram_bot():
        print(
            "[ERROR] Telegram bot "
            "is unavailable"
        )
        return

    posted_urls = (
        load_posted_urls()
    )

    rss_news = get_news_from_rss()

    print(
        f"[RSS] Total fresh "
        f"RSS candidates: "
        f"{len(rss_news)}"
    )

    if not rss_news:
        print(
            "[DONE] No RSS articles"
        )
        return

    fresh_news = filter_unposted_news(
        rss_news,
        posted_urls,
    )

    print(
        f"[RSS] Unposted candidates: "
        f"{len(fresh_news)}"
    )

    if not fresh_news:
        print(
            "[DONE] Nothing new "
            "to publish"
        )
        return

    shortlist = shortlist_news(
        fresh_news
    )

    if not shortlist:
        print(
            "[ERROR] AI shortlist "
            "failed"
        )
        return

    valid_articles = (
        build_article_candidates(
            shortlist
        )
    )

    if not valid_articles:
        print(
            "[ERROR] No valid "
            "articles after parsing"
        )
        return

    selected_article = (
        select_best_news(
            valid_articles
        )
    )

    if not selected_article:
        print(
            "[ERROR] News selection "
            "failed"
        )
        return

    post = generate_telegram_post(
        selected_article
    )

    if not post:
        print(
            "[ERROR] Post generation "
            "failed"
        )
        return

    image_info = get_article_image(
        selected_article
    )

    if image_info:
        print(
            f"[IMAGE] Ready for Telegram: "
            f"{image_info['width']}x"
            f"{image_info['height']}"
        )

    else:
        print(
            "[IMAGE] No suitable image "
            "found"
        )

    print_selected_post(
        post
    )

    published = (
        publish_to_telegram(
            post,
            image_info,
        )
    )

    if not published:
        print(
            "[ERROR] Publication failed"
        )
        return

    save_posted_url(
        selected_article["url"]
    )

    print(
        "[DONE] Article published"
    )


if __name__ == "__main__":
    main()