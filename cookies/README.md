# 🍪 Cookies

Сюда нужно положить файл `instagram.txt` с cookies от Instagram в формате Netscape.

## Как выгрузить cookies

### Вариант 1: Расширение для Chrome / Edge

1. Установи расширение **[Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)**
2. Залогинься на [instagram.com](https://www.instagram.com)
3. Находясь на сайте Instagram, нажми на иконку расширения
4. Нажми **Export** → сохрани файл как `cookies/instagram.txt` в этом проекте

### Вариант 2: Расширение для Firefox

1. Установи **[cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/)**
2. Залогинься на [instagram.com](https://www.instagram.com)
3. Нажми на иконку расширения → **Current Site** → **Export**
4. Сохрани как `cookies/instagram.txt`

### Вариант 3: gallery-dl + браузер (автоматически)

Если gallery-dl и браузер на одной машине, можно вместо файла указать имя браузера.
В `.env` замени путь на имя браузера:

```
COOKIES_FILE=chrome
```

gallery-dl сам вытащит cookies из профиля Chrome/Firefox/Edge.

> ⚠️ **Важно**: cookies протухают со временем. Если Instagram снова начнёт
> редиректить на логин — выгрузи cookies заново.

## Структура

```
cookies/
├── README.md        ← этот файл
└── instagram.txt    ← твой файл с cookies (в .gitignore)
```
