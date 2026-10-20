"""Роли пользователя: сервис создаётся для людей, а не для юрлиц (кейс, слайд 5) — у разных ЛПР разные акценты.

Роль не меняет факты и позицию банка, а расставляет акценты: какие риски и возможности показать первыми, какие
действия относятся к этому человеку, на что обратить внимание. Роль приходит из входа через Альфа-Бизнес
(entry.py) или выбирается в интерфейсе.
"""

ROLES = {
    "owner": {"label": "Собственник", "focus": "стоимость бизнеса, стратегия, крупные риски и возможности",
              "areas": ["strategic", "market", "financial"],
              "owners": ["развити", "собственник", "совет директоров", "инвестпроект", "риск"],
              "channels": ["competitor_trouble", "competitor_growth", "export_niche", "support", "clients_capex"]},
    "ceo": {"label": "Генеральный директор", "focus": "операции, клиенты и поставщики, конкуренты",
            "areas": ["operational", "strategic", "market"],
            "owners": ["генеральн", "коммерческ", "продаж", "производств", "закуп", "экспорт", "качеств", "тендер",
                       "коммуникац", "развити"],
            "channels": ["supply_disruption", "demand_down", "demand_up", "clients_demand", "competitor_trouble",
                         "export_disruption"]},
    "cfo": {"label": "Финансовый директор", "focus": "долг и ставка, маржа, бюджет, инвестпроекты",
            "areas": ["financial", "market"],
            "owners": ["финансов", "инвестпроект", "риск", "казначейств"],
            "channels": ["rate_up", "rate_hold", "rate_down", "input_cost_up", "input_cost_down", "output_price_down"]},
    "accountant": {"label": "Главный бухгалтер", "focus": "регулирование, отчётность, налоги и сроки",
                   "areas": ["regulatory", "financial"],
                   "owners": ["бухгалтер", "юрист", "юридическ", "отчётн", "налог", "комплаенс", "качеств"],
                   "channels": ["regulation", "localization", "support"]},
    "treasury": {"label": "Руководитель казначейства", "focus": "ликвидность, ставки, курс, депозиты, платежи",
                 "areas": ["financial", "market"],
                 "owners": ["казначейств", "alm", "финансовый директор"],
                 "channels": ["rate_up", "rate_hold", "rate_down", "rate_deposits", "fx_import", "fx_export"]},
}
DEFAULT = "cfo"


def get(key):
    return ROLES.get(key or "") and {"key": key, **ROLES[key]}


def owner_matches(role, owner):
    o = (owner or "").lower()
    return any(k in o for k in role["owners"])


def area_rank(role, area):
    return role["areas"].index(area) if area in role["areas"] else len(role["areas"])


def catalog():
    return [{"key": k, "label": v["label"], "focus": v["focus"]} for k, v in ROLES.items()]
