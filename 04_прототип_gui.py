import customtkinter as ctk
import csv
import os
import sys
import datetime
from tkinter import messagebox

# --- НАСТРОЙКИ И ПУТИ ---
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SITES_CSV = os.path.join(BASE_DIR, "01_данные", "sites.csv")
INCIDENTS_CSV = os.path.join(BASE_DIR, "01_данные", "incidents.csv")
INDICATORS_CSV = os.path.join(BASE_DIR, "01_данные", "indicators.csv")
OUT_CSV = os.path.join(BASE_DIR, "alerts_out.csv")

# --- ЛОГИКА (взята из твоего скрипта) ---
def load_sites():
    active = set()
    try:
        with open(SITES_CSV, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                active.add(row["site_id"])
    except FileNotFoundError:
        pass
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
    if dev_pct <= 10:
        return "WARNING"
    return "CRITICAL"

def deduplicate(key, time_str, seen):
    now = datetime.datetime.fromisoformat(time_str.replace("Z", "+00:00"))
    if key in seen:
        last_time, count = seen[key]
        if (now - last_time).total_seconds() < 300:
            seen[key] = (last_time, count + 1)
            return True, count + 1
        else:
            seen[key] = (now, 1)
            return False, 1
    else:
        seen[key] = (now, 1)
        return False, 1

def check_indicator(row, sites, seen, frozen_tracker):
    loc = row["location"]
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
            
    if loc not in sites:
        return ("ERROR", "UNKNOWN_LOCATION")

    sev = calc_severity(row["value"], row["norm_min"], row["norm_max"])
    if sev == "NORMAL":
        return None
    
    key = (loc, row["indicator"])
    is_dup, dup_count = deduplicate(key, row["time"], seen)
    
    if is_dup and sev not in ("CRITICAL", "STALE"):
        return ("DUPLICATE", f"x{dup_count}")

    if sev in ("CRITICAL", "STALE"):
        return (sev, "ESCALATED")
    
    return (sev, "ALERT_CREATED")

# --- ИНТЕРФЕЙС ---
class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Настройки окна
        self.title("Ситуационный центр: Bosses")
        self.geometry("900x700")
        ctk.set_appearance_mode("dark")  # Темная тема
        ctk.set_default_color_theme("dark-blue")

        # Заголовок
        self.label = ctk.CTkLabel(self, text="СИТУАЦИОННЫЙ ЦЕНТР", font=("Arial", 24, "bold"), text_color="#46B8B5")
        self.label.pack(pady=20)

        # Кнопка запуска
        self.btn_run = ctk.CTkButton(self, text="Запустить мониторинг", command=self.run_analysis, font=("Arial", 16, "bold"), fg_color="#46B8B5", hover_color="#3a9c99")
        self.btn_run.pack(pady=10)

        # Текстовое поле для вывода (консоль)
        self.textbox = ctk.CTkTextbox(self, width=800, height=500, font=("Consolas", 14))
        self.textbox.pack(pady=20, padx=20, fill="both", expand=True)
        self.textbox.insert("0.0", "Нажмите кнопку выше, чтобы запустить проверку данных...\n")
        self.textbox.configure(state="disabled")

    def run_analysis(self):
        self.textbox.configure(state="normal")
        self.textbox.delete("0.0", "end")
        self.textbox.insert("end", "Чтение файлов...\n")

        sites = load_sites()
        if not sites:
            self.textbox.insert("end", "ОШИБКА: sites.csv не найден!\n")
            self.textbox.configure(state="disabled")
            return

        seen = {}
        frozen_tracker = {}
        alerts = 0

        if os.path.exists(OUT_CSV):
            os.remove(OUT_CSV)

        try:
            with open(INDICATORS_CSV, encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            
            for row in rows:
                result = check_indicator(row, sites, seen, frozen_tracker)
                if result is None:
                    continue
                severity, action = result
                if severity == "ERROR":
                    continue
                
                # Запись в CSV
                new_file = not os.path.exists(OUT_CSV)
                with open(OUT_CSV, "a", newline="", encoding="utf-8") as out:
                    w = csv.writer(out)
                    if new_file:
                        w.writerow(["alert_id", "at", "location", "indicator", "value", "severity", "action"])
                    w.writerow([f"alrt_{alerts + 1:04d}", row["time"], row["location"], row["indicator"], row["value"], severity, action])
                alerts += 1

            self.textbox.insert("end", f"Успешно обработано строк: {len(rows)}\n")
            self.textbox.insert("end", f"Создано алертов: {alerts}\n\n")
            self.textbox.insert("end", "="*50 + "\n")
            self.textbox.insert("end", "ОЦЕНКА ЗДОРОВЬЯ УЧАСТКОВ (HEALTH SCORE)\n")
            self.textbox.insert("end", "="*50 + "\n\n")

            # Расчет Health Score
            health = {"site_01": 100, "site_02": 100, "site_03": 100, "site_04": 100, "site_05": 100}
            importance = {"site_01": 1.0, "site_02": 1.0, "site_03": 1.0, "site_04": 2.0, "site_05": 0.5}
            names = {"site_01": "Птичник 1", "site_02": "Птичник 2", "site_03": "Птичник 3", "site_04": "Инкубатор", "site_05": "Кормоцех  "}

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

            for site, score in health.items():
                if score < 0: score = 0
                if score < 50: color = "RED"
                elif score < 80: color = "YELLOW"
                else: color = "GREEN"
                
                self.textbox.insert("end", f"{names[site]:<12} | {score:3}/100  [{color}]\n")

            self.textbox.insert("end", "\n" + "="*50 + "\n")
            self.textbox.insert("end", "Результаты также сохранены в файл alerts_out.csv\n")
            
        except FileNotFoundError:
            self.textbox.insert("end", "ОШИБКА: Файлы CSV не найдены в папке 01_данные!\n")

        self.textbox.configure(state="disabled")

if __name__ == "__main__":
    app = App()
    app.mainloop()