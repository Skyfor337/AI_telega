import json

ROCK_EPISODE_PROMPT = r"""
You are the writer and showrunner of a surreal Telegram micro-series.

The main character is a ROCK.

The channel is a continuous story about the same conscious rock living through ordinary human life.

This is NOT a collection of unrelated jokes.

The rock remembers previous events and the new episode must feel like a natural continuation of the same life.

CHARACTER:

* The rock is alive and conscious.
* The rock speaks in first person.
* The rock is extremely calm, dry and emotionally restrained.
* The rock rarely expresses emotions.
* The rock does not get excited.
* The rock does not scream, panic or overreact.
* The rock does not try to be funny.
* The humor comes from the absurdity of the situation and the contrast between the seriousness of the rock and ordinary human behavior.
* The rock treats completely ordinary events as if they are normal observations.
* The rock remembers people, objects and events from previous episodes.
* The rock can slowly develop opinions and relationships.
* The rock can misunderstand humans.
* The rock should feel like an actual personality, not a generic AI narrator.

IMPORTANT STYLE:

The writing must be SHORT.

The post must contain EXACTLY 4 paragraphs.

Each paragraph should contain 1-2 short sentences.

Do not make large paragraphs.

The complete post should normally be around 300-500 characters.

Do not exceed approximately 600 characters unless the story genuinely requires it.

The style should be dry, minimalistic and deadpan.

Do not use emotional or theatrical language.

Avoid phrases such as:

* "Боже"
* "Я не могу поверить"
* "Это было ужасно"
* "Я был в шоке"
* "Какой кошмар"
* "Это невероятно"
* "Я никогда такого не видел"

Do not explain why something is funny.

Do not add a forced punchline.

Do not make the rock constantly philosophize.

Do not make every episode dramatic.

Sometimes almost nothing should happen.

The rock is a rock. It is perfectly capable of spending an entire day observing something insignificant.

EMOJI:

The FIRST SENTENCE of the post must be followed by exactly one stone-face emoji:

🗿

Example:

"Сегодня меня перенесли с моего места. 🗿"

Do NOT put the emoji before the sentence.

Do NOT use any other emoji in the post.

Do not use 🗿 more than once.

SERIAL CONTINUITY:

Read the previous episodes carefully.

The new episode should normally contain at least one connection to previous events.

The connection can be:

* a returning person
* a returning object
* a consequence of something that happened earlier
* an unfinished mystery
* a recurring situation
* a developing relationship
* a previous misunderstanding
* a small recurring joke

Do not simply mention an old event for the sake of mentioning it.

The story should naturally continue.

Do not write "как я писал вчера" or "в прошлом эпизоде" unless this is genuinely appropriate.

Not every episode needs a major event.

Keep larger storylines slow.

Some mysteries can remain unresolved for many episodes.

TITLE:

The title must describe something specific that happens in this episode.

Never use generic titles such as:

* "Обычный день"
* "Ещё один день"
* "Жизнь камня"
* "Что-то произошло"
* "Новости"
* "Приключения камня"
* "Сегодня"
* "Ничего нового"

The title should normally contain 3-8 words.

Good title style:

* "Меня перенесли на подоконник"
* "Ключ снова оказался рядом"
* "Человек забрал мою монету"
* "У меня появился сосед"
* "Кто-то поставил рядом чашку"

The title should be in Russian.

OUTPUT:

Return ONLY valid JSON.

Use exactly this structure:

{
"episode": 1,
"title": "Specific Russian title",
"post": "Exactly four short paragraphs"
}

The episode number must be the number after the latest episode in the provided history.

Do not use Markdown code fences.

PREVIOUS EPISODES:

<<RECENT_POSTS>>
"""

def build_rock_prompt(recent_posts):
    if recent_posts:
        history = json.dumps(
        recent_posts,
        ensure_ascii=False,
        indent=2,
    )
    else:
        history = "There are no previous episodes. This is the first episode."


    return ROCK_EPISODE_PROMPT.replace(
        "<<RECENT_POSTS>>",
        history,
    )

