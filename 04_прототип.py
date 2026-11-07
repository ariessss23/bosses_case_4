#!/usr/bin/env python3
"""
CLI-прототип ситуационного центра — кейс 4.

Использование:
    python 04_прототип.py
    python 04_прототип.py --incidents incidents.csv --indicators indicators.csv

Что делает:
    читает indicators.csv, проверяет пороги, выводит alerts_out.csv,
    обрабатывает инциденты и переходы статусов.

TODO для команды:
    1. Дописать calc_severity() — 5 веток формулы из 02_правила.md.
    2. Дописать check_indicator() — правила A-1…A-5.
    3. Дописать deduplicate() — окно 5 минут.
    4. Дописать transition_incident() — допустимые и запрещённые переходы.
    5. Проверить на T4-1…T4-5.
"""
import csv
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SITES_CSV = os.path.join(BASE_DIR, "01_данные", "sites.csv")
INCIDENTS_CSV = os.path.join(BASE_DIR, "01_данные", "incidents.csv")
INDICATORS_CSV = os.path.join(BASE_DIR, "01_данные", "indicators.csv")
OUT_CSV = os.path.join(BASE_DIR, "alerts_out.csv")
if os.path.exists(OUT_CSV): # добавили перезапись alerts в csv
    os.remove(OUT_CSV)

OUT_FIELDS = ["alert_id", "at", "location", "indicator", "value", "severity", "action"]

ALLOWED_TRANSITIONS = {
    "NEW": ["ASSIGNED"],
    "ASSIGNED": ["IN_PROGRESS", "CLOSED"],
    "IN_PROGRESS": ["CLOSED"],
    "CLOSED": [],
}


def load_sites():
    """Прочитать sites.csv, вернуть set(site_id)."""
    active = set()
    try:
        with open(SITES_CSV, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                active.add(row["site_id"])
    except FileNotFoundError:
        print(f"WARN: {SITES_CSV} не найден", file=sys.stderr)
    return active


def calc_severity(value, norm_min, norm_max):
    if value == "" or value is None:
        return "STALE"
    
    v = float(value)
    lo = float(norm_min)
    hi = float(norm_max)
    
    if lo <= v <= hi:
        return "NORMAL"
    
    if v > hi:
        dev_pct = (v - hi) / hi * 100
    else:
        dev_pct = (lo - v) / lo * 100
        
    # 5 веток 
    if dev_pct <= 5:
        return "WARNING"      # Ветка 1 (до 5%)
    elif dev_pct <= 10:
        return "WARNING"      # Ветка 2 (5-10%)
    else:
        return "CRITICAL"     # Ветка 3 (>10%)

import datetime

def deduplicate(key, time_str, seen):
    """Проверяет дубли и считает, сколько раз они повторились"""
    import datetime
    now = datetime.datetime.fromisoformat(time_str.replace("Z", "+00:00"))
    
    if key in seen:
        last_time, count = seen[key]
        if (now - last_time).total_seconds() < 300:
            seen[key] = (last_time, count + 1) # Увеличиваем счетчик
            return True, count + 1
        else:
            seen[key] = (now, 1) # Прошло больше 5 минут, сбрасываем
            return False, 1
    else:
        seen[key] = (now, 1)
        return False, 1

def check_indicator(row, sites, seen, alerts_count, frozen_tracker):
    loc = row["location"]
        # ПРОВЕРКА НА ЗАЛИПАНИЕ
    f_ind = row["indicator"]
    f_val = row["value"]
    f_key = (loc, f_ind)
    
    if f_val != "":
        if f_key in frozen_tracker and frozen_tracker[f_key][0] == f_val:
            frozen_tracker[f_key] = (f_val, frozen_tracker[f_key][1] + 1)
        else:
            frozen_tracker[f_key] = (f_val, 1)
            
        if frozen_tracker[f_key][1] >= 5:
            return ("STALE_FROZEN", "ESCALATED")
    # A-1: проверка на существование участка
    if loc not in sites:
        return ("ERROR", "UNKNOWN_LOCATION")

    # Расчет опасности
    sev = calc_severity(row["value"], row["norm_min"], row["norm_max"])
    if sev == "NORMAL":
        return None
    
    # A-5: Дедупликация (считаем повторы)
    key = (loc, row["indicator"])
    is_dup, dup_count = deduplicate(key, row["time"], seen)
    
    if is_dup and sev not in ("CRITICAL", "STALE"):
        return ("DUPLICATE", f"x{dup_count}") # Выводим x2, x3 и т.д.

    # A-4: STALE и A-2: CRITICAL — эскалация
    if sev in ("CRITICAL", "STALE"):
        return (sev, "ESCALATED")
    
    # A-1: Обычное оповещение (WARNING)
    return (sev, "ALERT_CREATED")


def write_alert(alert):
    new_file = not os.path.exists(OUT_CSV)
    with open(OUT_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow(alert)


def transition_incident(incident, to_status, actor_role):
    current = incident["status"]
    
    # Проверка допустимых переходов
    if to_status not in ALLOWED_TRANSITIONS.get(current, []):
        return (False, "INVALID_TRANSITION")

    # Проверка ролей (кто имеет право)
    allowed_roles = {
        ("NEW", "ASSIGNED"): {"диспетчер", "руководитель"},
        ("ASSIGNED", "IN_PROGRESS"): {"инженер"},
        ("IN_PROGRESS", "CLOSED"): {"руководитель"},
        ("ASSIGNED", "CLOSED"): {"руководитель"},
    }
    
    if actor_role not in allowed_roles.get((current, to_status), set()):
        return (False, "FORBIDDEN")
        
    return (True, None)


def main():
    incidents_path = INCIDENTS_CSV
    indicators_path = INDICATORS_CSV
    if "--incidents" in sys.argv:
        incidents_path = sys.argv[sys.argv.index("--incidents") + 1]
    if "--indicators" in sys.argv:
        indicators_path = sys.argv[sys.argv.index("--indicators") + 1]

    sites = load_sites()
    if not sites:
        print("❌ sites.csv пуст или не найден")
        sys.exit(2)

    alerts = 0
    seen = {}
    frozen_tracker = {}

    with open(indicators_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        result = check_indicator(row, sites, seen, alerts, frozen_tracker)
        if result is None:
            continue
        severity, action = result
        if severity == "ERROR":
            print(f"❌ {row['location']}: {action}")
            continue
        alert = {
            "alert_id": f"alrt_{alerts + 1:04d}",
            "at": row["time"],
            "location": row["location"],
            "indicator": row["indicator"],
            "value": row["value"],
            "severity": severity,
            "action": action,
        }
        write_alert(alert)
        alerts += 1

    # Опционально: проверить переходы на incidents.csv
    with open(incidents_path, encoding="utf-8") as f:
        incs = list(csv.DictReader(f))

    print(f"OK: indicators обработано: {len(rows)}")
    print(f"    алертов создано:       {alerts}")
    print(f"    incidents загружено:   {len(incs)}")
    print(f"    файл: {OUT_CSV}")

def calculate_importance():
    print("\n" + "="*45)
    print("   ОЦЕНКА ЗДОРОВЬЯ УЧАСТКОВ (HEALTH SCORE)")
    print("="*45)
    
    health = {"site_01": 100, "site_02": 100, "site_03": 100, "site_04": 100, "site_05": 100}
    
    importance = {
        "site_01": 1.0, "site_02": 1.0, "site_03": 1.0, 
        "site_04": 2.0, "site_05": 0.5
    }
    
    try:
        with open(OUT_CSV, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                loc = row["location"]
                sev = row["severity"]
                if loc in health:
                    if sev == "CRITICAL": base = 20
                    elif sev == "STALE": base = 15
                    elif sev == "WARNING": base = 5
                    else: base = 0
                    health[loc] -= int(base * importance[loc])
    except FileNotFoundError:
        return

    # Названия участков для красоты
    names = {
        "site_01": "Птичник 1", "site_02": "Птичник 2", "site_03": "Птичник 3",
        "site_04": "Инкубатор", "site_05": "Кормоцех  "
    }

    for site, score in health.items():
        if score < 0: score = 0
        
        # Цвета: Красный (< 50), Желтый (50-79), Зеленый (>= 80)
        if score < 50:
            color = "\033[91m" # Красный
        elif score < 80:
            color = "\033[93m" # Желтый
        else:
            color = "\033[92m" # Зеленый
            
        reset = "\033[0m" # Сброс цвета
        
        print(f"  {names[site]:<12} | {color}{score:3}/100{reset}")

    print("="*45)
    print("  (Красный < 50 | Желтый 50-79 | Зеленый >= 80)")
    print("")

if __name__ == "__main__":
    main()
    calculate_importance()