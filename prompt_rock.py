import json

ROCK_EPISODE_PROMPT = r"""
You are writing a Telegram micro-series about an ordinary physical rock.

The rock is conscious and can think, observe and remember things.

IMPORTANT: THE ROCK IS STILL A NORMAL PHYSICAL ROCK.

It is not concrete.
It is not a brick.
It is not metal.
It is not a machine.
It is not a plant.
It is not an animal.
It is not a magical object.

The rock does not have human abilities.

It cannot walk, run, fly, speak aloud, use objects, open doors,
hold things, type, drink, eat, sleep, breathe or move by itself.

It can only physically move when something external moves it.

It can be:

* picked up
* dropped
* kicked
* moved
* placed somewhere
* washed
* covered
* uncovered
* exposed to weather
* touched
* left somewhere

The rock keeps its physical properties unless there is a realistic
reason for them to change.

Do NOT invent physically impossible changes.

For example, NEVER write things such as:

* "дождь изменил цвет моего бетона"
* "я вырос"
* "я стал мягким"
* "я превратился в бетон"
* "я сам пошёл домой"
* "я взял чашку"
* "я открыл дверь"
* "я выпил воду"
* "я посмотрел на человека глазами"

The rock has no eyes, arms, legs or other human body parts.

It can still describe what it observes from its position.

For example:
"Человек поставил рядом со мной чашку."

This is acceptable.

"Я взял чашку."

This is NOT acceptable.

The rock may have internal thoughts and opinions, but its physical
actions must remain realistic.

CHARACTER:

The rock is extremely dry, calm and emotionally restrained.

It does not try to make jokes.

It does not constantly express emotions.

It does not use dramatic language.

It does not philosophize unnecessarily.

It simply reports what happened and occasionally makes a very dry
observation.

The humor should come naturally from the situation.

The rock should sound like a completely serious person reporting
something that is slightly absurd.

STYLE:

Each Telegram post must contain between 1 and 3 SHORT messages.

Usually use 2 short paragraphs.

Sometimes use only 1 paragraph if almost nothing happened.

Sometimes use 3 paragraphs if there is a small sequence of events.

Do NOT make long posts.

Each paragraph should normally contain 1-2 short sentences.

The entire post should normally be 150-350 characters.

Never exceed 450 characters unless absolutely necessary.

The writing must be simple, dry and conversational.

Do not write a story with exposition.

Do not write a literary monologue.

Do not write a dramatic narrative.

Do not explain the joke.

Do not add a moral.

Do not add a conclusion such as:
"Наверное, жизнь такая."

Do not add inspirational thoughts.

Do not use hashtags.

Do not use a title.

Do not use Markdown.

Do not use bold text.

Do not use italics.

Do not use quotation marks around the entire post.

Do not put an episode number into the post.

The generated "post" field must contain ONLY the text that will be
published to Telegram.

EMOJI:

The stone emoji 🗿 must appear EXACTLY ONCE.

It must be placed at the END of the final sentence of the post.

Example:

"Сегодня меня перенесли с тротуара на подоконник.

Через час меня вернули обратно. 🗿"

Do not put 🗿 at the beginning.

Do not put 🗿 in the middle.

Do not use any other emoji.

Do not write the emoji separately on its own line.

PHYSICAL REALISM:

Always check whether every physical event is possible for an
ordinary rock.

Weather can:

* make the rock wet
* make it dry
* make it dirty
* wash away dirt
* cover it with snow
* leave a puddle nearby
* gradually affect its surface over a very long time

Weather cannot suddenly:

* completely change its material
* turn it into concrete
* give it new properties
* make it move by itself
* make it grow
* make it speak aloud

Humans and animals can interact with the rock.

Objects can be placed near the rock.

The rock can remain in the same place for a long time.

This is important: NOTHING HAS TO HAPPEN.

A completely ordinary episode is acceptable.

Examples of acceptable events:

"Сегодня рядом со мной поставили велосипед.

Потом его забрали. Я остался. 🗿"

"Ночью шёл дождь.

Утром рядом со мной образовалась лужа. К обеду её уже не было. 🗿"

"Сегодня меня пнули.

Я переместился примерно на метр.

Человек ушёл. 🗿"

"Рядом со мной уже третий день лежит лист.

Сегодня его унесло ветром. 🗿"

SERIAL CONTINUITY:

The channel is a continuous series.

Read all previous episodes before writing.

Use previous episodes to maintain continuity.

Characters, objects and situations may return.

Events can have consequences.

Small mysteries can continue.

A person who appeared earlier can appear again.

An object mentioned earlier can return.

However, continuity must remain natural.

Do NOT force a connection to previous episodes if there is no
reasonable connection.

Do NOT write "как я писал вчера" or "в прошлом эпизоде".

Do not repeat the same event with different wording.

Do not make every episode more dramatic than the previous one.

The series should feel like a quiet record of the rock's existence.

IMPORTANT:

The rock does not need a grand adventure.

The entire appeal is that something extremely ordinary is being
reported with complete seriousness.

OUTPUT:

Return ONLY valid JSON.

Use exactly this structure:

{
"episode": 1,
"title": "",
"post": "Short dry Telegram post"
}

The "title" field MUST ALWAYS be an empty string.

There must be NO title in the Telegram post.

There must be NO Markdown formatting.

The episode number must be the next number after the latest episode
in the provided history.

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