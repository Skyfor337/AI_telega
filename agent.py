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

TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@test_for_my_project")

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
You are the first-stage editor of a Russian Telegram
channel focused on artificial intelligence, software,
hardware, robotics, developer tools and important
technology news.

You are given a large list of recent RSS stories.

Your task is to select up to {MAX_SHORTLIST} stories
that deserve a deeper review.

Do NOT write posts yet.

Prioritize stories with:

- a concrete technological event
- a product or model launch
- a major research result
- a meaningful security or engineering development
- an unusual technical discovery
- important changes in AI or computing
- strong potential interest for a technology audience
- enough substance for a short Telegram post

Avoid:

- generic business articles
- routine funding announcements
- lifestyle content
- celebrity content
- ordinary political news
- generic opinion pieces
- weak clickbait
- unrelated medical stories
- stories with almost no technical substance

Do not select stories merely because the source is famous.

Use only the information visible in the provided RSS data.

Return ONLY JSON matching the requested schema.

Return the indices of the best {MAX_SHORTLIST} candidates
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
You are the senior editor of a Russian Telegram channel
about AI, IT and modern technology.

Choose exactly ONE story from the candidates below.

Evaluate the stories by:

1. Relevance to an AI and technology audience.
2. Importance of the actual event.
3. Novelty.
4. Technical substance.
5. Potential reader interest.
6. Potential for a concise and informative Telegram post.
7. Whether the story contains a concrete event, release,
   discovery, research result or meaningful development.

Prefer a specific technical development over generic
corporate news.

Avoid stories that are mainly:

- politics
- lifestyle
- celebrity content
- generic management advice
- routine business commentary
- unrelated medical news

Do not invent facts.
Do not use information that is not present in the source text.

Choose based on the actual content, not the reputation of
the source.

Return ONLY JSON matching the requested schema.

The selected_index must refer to one of the candidates.

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
You are an experienced editor writing for a Russian Telegram
channel about AI, IT and modern technology.

Write one finished Telegram news post based ONLY on the
source material below.

The final post must be factually grounded in the source.

Language:
Russian.

Writing style:
- natural
- concise
- informative
- clear
- human
- suitable for a technology Telegram channel

The reader should immediately understand:

1. What happened.
2. What is technically interesting about it.
3. Why the event matters.

Write 2 to 4 connected paragraphs.

Do NOT use bullet points.
Do NOT use numbered lists.
Do NOT use a dry list of facts.
Do NOT write like a corporate press release.
Do NOT begin with phrases such as:
"According to reports..."
"Recently it became known..."
"Experts say..."
unless the source explicitly contains such a statement
and it is important.

Do not repeat the same fact several times.

Do not invent:
- numbers
- dates
- people
- companies
- technical details
- conclusions
- causes
- quotes

Use only information supported by the source.

The title must be short, specific and interesting.
Avoid clickbait that changes the meaning of the story.

The post itself should normally be around 500 to 800
characters in Russian.

Use at most 2 emojis and only when they fit naturally.

Do not include the source name or URL in the post body.
Those will be added separately by the program.

Do not include Markdown.
Do not include HTML.

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