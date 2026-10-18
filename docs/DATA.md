# Данные

## Компании (backend/data/real/profiles.json)

Пять реальных компаний из разных отраслей. Профили составлены командой по открытым источникам
(сайты и отчётность компаний, публикации СМИ из подборки ниже). Это не официальная позиция компаний,
конфиденциальных данных нет.

| id | Компания | Отрасль | Почему интересна для КИБ |
|---|---|---|---|
| `severstal` | ПАО «Северсталь» | Металлургия | экспорт через порты, зависимость от РЖД, спрос строителей |
| `x5` | X5 Group | Продуктовый ритейл | регулирование (маркировка), маржинальность, логистика |
| `sber` | ПАО Сбербанк | Финансы | ставка, ипотека, кредитный риск застройщиков, цифровые активы |
| `pik` | ПИК | Девелопмент | семейная ипотека, продажи новостроек, долг, себестоимость |
| `aeroflot` | ПАО «Аэрофлот» | Авиаперевозки | керосин и демпфер, конкуренты, сеть маршрутов |

Профили специально пересекаются: застройщики — клиенты «Северстали» и заёмщики Сбера, арматура — закупка ПИК.
Поэтому одна новость получает для разных компаний разные оценки и разные выводы.

## Подборка новостей (backend/data/real/news.json)

22 реальные публикации за 11 сентября — 16 октября 2026 года. Каждая открывалась вручную, факты сверены с оригиналом.
В файле хранится заголовок, ссылка, дата и **краткий пересказ фактов командой** — текст статей не копируется.
Если точное время публикации неизвестно, стоит `time_approx: true`.

| id | Издание | Дата | Публикация |
|---|---|---|---|
| r01 | Коммерсантъ | 05.10 | [«Нечего делать из этих гвоздей»](https://www.kommersant.ru/doc/9005931) |
| r02 | Reuters / The Moscow Times | 02.10 | [Спрос на сталь в России за 8 мес упал на 16% — Северсталь](https://ru.themoscowtimes.com/2026/10/02/spros-na-stal-v-rossii-za-8-mes-26g-upal-na-16-gg-severstal-a207614) |
| r03 | Интерфакс / The Moscow Times | 13.10 | [Металлурги предупредили о риске остановки предприятий из-за проблем с вывозом через Балтику](https://ru.themoscowtimes.com/2026/10/13/metallurgi-predupredili-oriske-ostanovki-predpriyatii-iz-za-problem-svivozom-produktsii-cherez-baltiku-a208523) |
| r04 | Ведомости | 16.10 | [X5 отчиталась о росте выручки на 13% за III квартал](https://vedomosti.ru/investments/news/2026/10/16/1237597-x5-otchitalas-o-roste) |
| r05 | Retail.ru | 16.10 | [Выручка X5 в 3 квартале 2026 года выросла на 13%](https://www.retail.ru/news/vyruchka-x5-v-3-kvartale-2026-goda-vyrosla-na-13--16-oktyabrya-2026-283373/) |
| r06 | Retail.ru | 14.10 | [Контроль за продажей маркированных товаров с 13 октября](https://www.retail.ru/news/kontrol-za-prodazhey-markirovannykh-tovarov-s-13-oktyabrya-2026-goda-pri-kakikh--14-oktyabrya-2026-283307/) |
| r07 | Retail.ru | 15.10 | [Поэкземплярный учёт маркировки растительных масел с 1 ноября](https://www.retail.ru/news/s-1-noyabrya-2026-goda-v-rf-zarabotaet-poekzemplyarnyy-uchet-markirovki-rastitel-15-oktyabrya-2026-283356/) |
| r08 | Фонтанка.ру | 14.10 | [Беспилотники атаковали центр обработки данных Сбера](https://fontanka.ru/2026/10/14/76699439) |
| r09 | Reuters / The Moscow Times | 08.10 | [Греф пообещал «очень хорошие» дивиденды по итогам 2026 года](https://ru.themoscowtimes.com/2026/10/08/gref-poobeschal-ochen-khoroshie-dividendy-aktsioneram-sberbanka-po-itogam-2026-goda-a208109) |
| r10 | Reuters / The Moscow Times | 06.10 | [ЦБР внёс в реестр 5 первых криптодепозитариев, включая Сбер и ВТБ](https://ru.themoscowtimes.com/2026/10/06/tsbr-vnes-v-reestr-5-pervykh-kriptodepozitariev-vklyuchaya-sber-i-vtb-a207940) |
| r11 | Интерфакс | 14.10 | [Акционеры «ПИКа» одобрили делистинг](https://www.interfax.ru/business/1122443) |
| r12 | Ведомости | 13.10 | [Мосбиржа приостановит торги акциями ПИК с 20 октября](https://www.vedomosti.ru/investments/news/2026/10/13/1236778-torgi-aktsiyami-pik) |
| r13 | Интерфакс | 24.09 | [Минфин меняет условия семейной ипотеки с 1 октября](https://www.interfax.ru/business/1118280) |
| r14 | Российская газета | 15.10 | [Продажи жилья упали до минимума](https://rg.ru/2026/10/15/prodazhi-kvartir-v-rossii-mogut-stat-minimalnymi-s-2014-goda.html) |
| r15 | Агентство Бизнес Новостей | 13.10 | [Продажи новостроек в сентябре выросли](https://abn.agency/2026/10/13/prodazhi-novostroek-v-sentyabre-vyrosli-na-fone-ozhidaniya-peremen-v-semejnoj-ipoteke/) |
| r16 | AEX.RU | 12.10 | [«Аэрофлот» за 9 месяцев сократил перевозку пассажиров на 0,6%](https://www.aex.ru/news/2026/10/12/300384/) |
| r17 | Москва 24 | 16.10 | [«Аэрофлот» перейдёт на зимнее расписание с 25 октября](https://www.m24.ru/news/16102026/953395) |
| r18 | Интерфакс | 01.10 | [Цена авиакеросина в формуле демпфера в 2027 г. может вырасти до 71,65 тыс. руб./т](https://www.interfax.ru/business/1119610) |
| r19 | Reuters / The Moscow Times | 06.10 | [Демпфер для авиакеросина вырос в 1,5 раза](https://ru.themoscowtimes.com/2026/10/06/dempfer-dlya-aviakerosina-v-rf-vyros-v-15-raza-v-senavg-raschyot-reyter-a207929) |
| r20 | Сибдепо | 09.10 | [S7 уйдёт, а «Аэрофлот» останется](https://sibdepo.ru/news/s7-ujdyot-a-aeroflot-ostanetsya-v-kuzbasse-izmenitsya-raspisanie-samolyotov.html) |
| r21 | Банк России | 11.09 | [Решение сохранить ключевую ставку 14%](https://www.cbr.ru/press/pr/?file=11092026_133000Key.htm) |
| r22 | Известия (англ.) | 16.10 | [Economists predicted that the key rate would remain at 14%](https://en.iz.ru/en/2185325/2026-10-16/economists-predicted-key-rate-would-remain-14) |

Пары r01/r02, r04/r05 и r11/r12 — одно событие в разных изданиях; система склеивает их в одну карточку
с пометкой «Подтверждено: 2 источника».

Bloomberg и часть других глобальных изданий закрыты пейволом (проверить текст не удалось), поэтому вместо них
использованы первоисточник (Банк России) и Reuters в публикации The Moscow Times.

## Как обновить подборку

1. Найти публикацию, открыть оригинал, выписать факты своими словами (без копирования абзацев).
2. Добавить объект в `backend/data/real/news.json`: `id`, `title`, `summary`, `body`, `source`, `url`,
   `published_at` (ISO с часовым поясом), `reliability`, при необходимости `official`, `time_approx`, `lang`,
   `title_original`.
3. Перезапустить backend или нажать «Обновить ленту → Перезагрузить подборку».
4. `python -m pytest tests/test_real_dataset.py` — проверит ссылки, даты и уникальность.

## Синтетический набор (backend/data/synthetic)

Три вымышленные компании и 22 вымышленных события — на них написаны тесты бизнес-логики, потому что для
синтетики заранее известен «правильный» вывод. Включается `DATASET=synthetic`. В интерфейсе такие события
помечены «Демо», ссылок у них нет.
