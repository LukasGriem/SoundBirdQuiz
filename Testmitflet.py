import flet as ft
import json
import os
import random
import asyncio
import aiohttp
import vlc
import threading
import pandas as pd
import urllib.request
import io
import base64
from PIL import Image
import requests
import http.server
import socketserver
import threading
from functools import partial
import csv
import sqlite3
import seaborn as sns
import matplotlib.pyplot as plt
import numpy as np
from bs4 import BeautifulSoup  # HTML-Tags entfernen
import shutil



def start_local_http_server(directory="bird_cache", port=8000):
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=directory)
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"HTTP Server läuft auf http://localhost:{port}")
        httpd.serve_forever()

server_thread = threading.Thread(target=start_local_http_server, daemon=True)
server_thread.start()


def init_db():
    """Erstellt die SQLite-Datenbank und die Tabelle mit session_id, falls sie noch nicht existiert."""
    db_path = os.path.join(os.getenv("LOCALAPPDATA"), "SoundBirdQuiz", "game_results.db") #Müsste eigentlich hier gespeichert sein: C:\Users\USERNAME\AppData\Local\SoundBirdQuiz\game_results.db
    os.makedirs(os.path.dirname(db_path), exist_ok=True)  # Falls Ordner nicht existiert, erstelle ihn

    conn = sqlite3.connect(db_path)  # Datenbank im Benutzerverzeichnis speichern. Davor war es ("game_results.db") 
    cursor = conn.cursor()

    # Erstelle die Tabelle mit session_id, falls sie nicht existiert
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,  -- NEU: Session-ID hinzufügen
            correct_species TEXT,
            selected_species TEXT,
            is_correct INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # **Falls die Spalte session_id fehlt, füge sie nachträglich hinzu**
    try:
        cursor.execute("ALTER TABLE results ADD COLUMN session_id INTEGER")
    except sqlite3.OperationalError:
        pass  # Falls die Spalte schon existiert, ignoriere den Fehler

    conn.commit()
    conn.close()


# Datenbank beim Start initialisieren
init_db()

#Funktion zum Löschen der Ergebnisse
def delete_all_results():
    db_path = os.path.join(os.getenv("LOCALAPPDATA"), "SoundBirdQuiz", "game_results.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM results")
    conn.commit()
    conn.close()
    print("[INFO] Alle Einträge wurden gelöscht.")

# CSV einmal global laden (z.B. beim Programmstart)
species_df = pd.read_csv("Europ_Species_3.csv", encoding="utf-8-sig")  # Passe ggf. den Delimiter an

# Erstelle ein Dictionary für die Umbenennung:
latin_to_german = dict(zip(species_df["Wissenschaftlich"], species_df["Deutsch"]))


def get_last_session_id():
    """Holt die höchste gespeicherte session_id aus der SQLite-Datenbank."""
    conn = sqlite3.connect("game_results.db")
    cursor = conn.cursor()

    cursor.execute("SELECT MAX(session_id) FROM results")  # Höchste session_id abrufen
    last_session_id = cursor.fetchone()[0]  # Wert extrahieren

    conn.close()
    return last_session_id if last_session_id is not None else 0  # Falls leer, starte mit 0


def lookup_species(species_input, species_df):
    """
    Sucht in species_df (CSV mit Spalten 'Deutsch', 'Wissenschaftlich', 'Englisch')
    nach einem Eintrag, der dem normalisierten species_input entspricht.
    Gibt ein Dictionary zurück oder None, falls kein Eintrag gefunden wird.
    """

    species_input_norm = species_input.strip().lower().replace("+", " ").encode("utf-8").decode("utf-8")

    print(f"[DEBUG] Suche nach normalisierter Art: {species_input_norm}")

    for idx, row in species_df.iterrows():
        for col in ["Deutsch", "Wissenschaftlich", "Englisch"]:
            val = str(row[col]).strip().lower().replace("+", " ").encode("utf-8").decode("utf-8")

            if val == species_input_norm:
                return {
                    "Deutsch": row["Deutsch"],
                    "Wissenschaftlich": row["Wissenschaftlich"],
                    "Englisch": row["Englisch"],
                    "display_language": col
                }

    print(f"[WARN] Art '{species_input}' wurde nicht gefunden!")
    return None


def convert_species_list(species_str):
    """
    Wandelt eine komma-getrennte Liste von Arten in ein Mapping um.
    """
    print(f"[DEBUG] Eingehender species_str: {species_str}")

    species_inputs = [s.strip() for s in species_str.split(",") if s.strip()]

    print("[DEBUG] Getrennte Einträge:", species_inputs)

    mapping_dict = {}
    for input_name in species_inputs:
        print(f"[DEBUG] Suche nach: {input_name}")  # Debug für jedes Item
        mapping = lookup_species(input_name, species_df)

        if mapping:
            scientific = mapping["Wissenschaftlich"].strip().lower()
            display_name = mapping[mapping["display_language"]].strip()
            mapping_dict[scientific] = display_name
            print(f"[DEBUG] Treffer: {scientific} → {display_name}")
        else:
            print(f"[WARN] Art '{input_name}' nicht in der CSV gefunden.")

    return mapping_dict


def fetch_and_display_sonogram(sonogram_url, image_control: ft.Image):
    try:
        # Falls die URL gültig ist, direkt zuweisen:
        image_control.src = sonogram_url
    except Exception as e:
        print(f"Error fetching sonogram: {e}")

# Globales Cache-Dictionary
api_cache = {}

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
HEADERS = {
    "User-Agent": "BirdQuizBot/1.0 (Python Script for Bird Sound Quiz)"
}


#Ab hier def nicht mehr in test_df drin!!!
def cache_bird_images(species_list):
    """
    Lädt und speichert Wikipedia-Bilder für die angegebenen Arten.
    """
    os.makedirs("bird_cache", exist_ok=True)

    for species in species_list:
        safe_name = species.replace("+", "_").replace(" ", "_").lower()
        cache_dir = os.path.join("bird_cache", safe_name)
        metadata_file = os.path.join(cache_dir, "metadata.json")
        image_file = os.path.join(cache_dir, "image_0.jpg")

        # Überspringen, wenn bereits gecached
        if os.path.exists(metadata_file):
            print(f"[INFO] Bilder für '{species}' sind bereits gecached.")
            continue

        # Existierenden Ordner löschen und neu anlegen
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
        os.makedirs(cache_dir, exist_ok=True)

        # Wikipedia nach dem passenden Artikel durchsuchen
        search_params = {
            "action": "query",
            "list": "search",
            "srsearch": f"{species} +bird -chimp -ape -Pan",
            "format": "json"
        }
        try:
            resp = requests.get(WIKIPEDIA_API, headers=HEADERS, params=search_params)
            data = resp.json()
        except Exception as e:
            print(f"[ERROR] Suche nach '{species}': {e}")
            continue

        search_results = data.get("query", {}).get("search", [])
        if not search_results:
            print(f"[WARN] Kein Wikipedia-Artikel für '{species}' gefunden.")
            continue

        page_title = search_results[0]["title"]

        # Bild abrufen (pageimages)
        image_params = {
            "action": "query",
            "prop": "pageimages",
            "titles": page_title,
            "piprop": "thumbnail|name",
            "pithumbsize": 800,
            "format": "json"
        }
        try:
            img_resp = requests.get(WIKIPEDIA_API, headers=HEADERS, params=image_params)
            img_data = img_resp.json()
        except Exception as e:
            print(f"[ERROR] pageimages für '{page_title}': {e}")
            continue

        pages = img_data.get("query", {}).get("pages", {})
        thumbnail_url = None
        file_name = None
        for _, page_info in pages.items():
            thumb = page_info.get("thumbnail")
            page_img_name = page_info.get("pageimage")
            if thumb and page_img_name:
                thumbnail_url = thumb.get("source")
                file_name = "File:" + page_img_name
                break

        if not thumbnail_url:
            print(f"[WARN] Kein Thumbnail für '{page_title}' gefunden.")
            continue

        # Bild herunterladen
        try:
            r = requests.get(thumbnail_url, headers=HEADERS)
            if r.status_code != 200:
                print(f"[ERROR] Download des Bildes von {thumbnail_url} fehlgeschlagen, Code={r.status_code}")
                continue

            with open(image_file, "wb") as f:
                f.write(r.content)
        except Exception as e:
            print(f"[ERROR] Thumbnail für '{species}' herunterladen: {e}")
            continue

        # Lizenz- und Autor-Informationen abrufen
        license_params = {
            "action": "query",
            "titles": file_name,  # Hier wird der Bild-Dateiname genutzt
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "format": "json"
        }

        try:
            license_resp = requests.get(WIKIPEDIA_API, headers=HEADERS, params=license_params)
            license_data = license_resp.json()

            pages = license_data.get("query", {}).get("pages", {})
            image_info = next(iter(pages.values()), {}).get("imageinfo", [{}])[0]

            author = image_info.get("extmetadata", {}).get("Artist", {}).get("value", "Unbekannt")
            license = image_info.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "Unbekannt")
            photo_author = BeautifulSoup(author, "html.parser").text
        except Exception as e:
            print(f"[ERROR] Lizenzinformationen für '{species}' abrufen: {e}")
            photo_author = "Unbekannt"
            license = "Unbekannt"

        # Metadaten speichern
        file_metadata = [{
            "filename": os.path.basename(image_file),
            "license": license,
            "author": photo_author
        }]
        try:
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(file_metadata, f, ensure_ascii=False, indent=2)
            print(f"[OK] Bild und Metadaten für '{species}' in {image_file} gespeichert.")
        except Exception as e:
            print(f"[ERROR] metadata.json für '{species}' schreiben: {e}")

def delete_entire_image_cache():
    cache_dir = "bird_cache"
    if os.path.exists(cache_dir):
        try:
            shutil.rmtree(cache_dir)
            print("[INFO] Gesamter Bilder-Cache erfolgreich gelöscht.")
        except Exception as e:
            print(f"[ERROR] Fehler beim Löschen des Bild-Caches: {e}")
    else:
        print("[INFO] Kein Cache-Ordner vorhanden – nichts zu löschen.")



def load_bird_image(species: str) -> str:
    """
    Gibt die URL des gecachten Vogelbildes für die gegebene Art zurück.
    Voraussetzung: Ein lokaler HTTP-Server liefert den "bird_cache"-Ordner aus.
    """
    safe_name = species.replace("+", "_").replace(" ", "_").lower()
    # Annahme: HTTP-Server läuft auf localhost:8000
    return f"http://localhost:8000/{safe_name}/image_0.jpg"

def load_image_metadata(species: str) -> dict:
    safe_name = species.replace("+", "_").replace(" ", "_").lower()
    metadata_file = os.path.join("bird_cache", safe_name, "metadata.json")
    if os.path.exists(metadata_file):
        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) > 0:
                return data[0]  # Metadaten des ersten Bildes zurückgeben
        except Exception as e:
            print(f"[ERROR] Fehler beim Laden der Metadaten für '{species}': {e}")
    return {"license": "Unbekannt", "author": "Unbekannt"}  # Fallback



def plot_final_stats_matrix(matrix, save_path="matrix_plot.png"):
    """
    Plots the final_stats_matrix as a heatmap with:
    - Diagonal values colored from white to green (higher values = darker green)
    - Off-diagonal values colored from white to red (higher values = darker red)
    - Dark theme: black background, white text
    - No title (as requested)
    - X-axis stays on top
    - Saves as PNG for GUI integration
    """
    # 🛠 Fix für Matplotlib GUI-Problem
    plt.switch_backend("Agg")

    # 🟢 Shape-Check für die Matrix
    if matrix.empty:
        print("[WARN] Die Confusion Matrix ist leer!")
        return

    print(f"[DEBUG] Matrix Shape: {matrix.shape}")  # Debug-Output

    # Korrekte Masken erzeugen
    n = matrix.shape[0]  # Anzahl der Klassen
    diag_mask = np.eye(n, dtype=bool)  # Diagonale Maske
    off_diag_mask = ~diag_mask  # Alles außer der Diagonale

    # Definiere die Colormaps
    cmap_off_diag = sns.light_palette("#5cb85c", as_cmap=True)
    cmap_diag = sns.light_palette("#f0ad4e", as_cmap=True)

    # Normalisiere Werte (0 = weiß)
    max_value = matrix.values.max()
    norm = plt.Normalize(vmin=0, vmax=max_value)

    # Erstelle die Figur und Achsen
    fig, ax = plt.subplots(figsize=(10, 8))
    fig.patch.set_facecolor('black')  # Hintergrundfarbe der Figur
    ax.set_facecolor('black')  # Hintergrundfarbe der Achse

    # X-Achse oben halten
    ax.xaxis.tick_top()
    ax.xaxis.set_label_position("top")

    # Heatmap für Off-Diagonal-Werte (keine Gitterlinien)
    sns.heatmap(matrix, mask=off_diag_mask, cmap=cmap_off_diag, annot=True,
                cbar=False, linewidths=0, ax=ax, norm=norm, square=True)

    # Overlay für die Diagonal-Werte (keine Gitterlinien)
    sns.heatmap(matrix, mask=diag_mask, cmap=cmap_diag, annot=True,
                cbar=False, linewidths=0, ax=ax, norm=norm, square=True)

    # Achsen-Labels in Weiß
    ax.set_xlabel("Your Prediction", fontsize=18, labelpad=10, color='white')
    ax.set_ylabel("Correct Species", fontsize=18, labelpad=10, color='white')

    # Tick-Labels in Weiß
    ax.tick_params(colors='white')
    plt.xticks(rotation=45, ha='left', fontsize=11, color='white')
    plt.yticks(rotation=0, fontsize=11, color='white')

    # Layout anpassen und speichern
    plt.subplots_adjust(left=0.2, right=0.9, top=0.85, bottom=0.15)
    plt.tight_layout(pad=2)

    plt.savefig(save_path, transparent=True, dpi=300)
    print(f"[DEBUG] Confusion Matrix gespeichert: {save_path}")

def plot_cumulative_accuracy():
    """Erstellt ein Liniendiagramm der kumulierten Korrektheit über alle Sessions."""
    conn = sqlite3.connect("game_results.db")
    query = """
        SELECT session_id, 
               AVG(is_correct) * 100 AS accuracy,
               COUNT(*) AS total_count
        FROM results
        GROUP BY session_id
        HAVING total_count >= 10  -- 🔹 Filter: Nur Sessions mit mindestens 10 Audios
        ORDER BY session_id
    """
    df = pd.read_sql_query(query, conn)
    conn.close()

    plt.figure(figsize=(10, 6))
    plt.plot(df["session_id"], df["accuracy"], marker="o", linestyle="-", color="green")
    plt.xlabel("Session")
    plt.ylabel("Durchschnittliche Korrektheit (%)")
    plt.title("Kumulierte Korrektheit über Sessions")
    plt.ylim(0, 100)
    plt.grid(True)
    plt.savefig("cumulative_accuracy.png", transparent=False, dpi=300)


def get_top3_text():
    """
    Erstellt einen Text mit den Top 3 am besten & schlechtesten erkannten Arten.
    Format:
    - "Die 3 am besten erkannten Arten sind: Blaumeise (90%, 10 Aufnahmen), ..."
    - "Die 3 am schlechtesten erkannten Arten sind: Kohlmeise (40%, 8 Aufnahmen), ..."
    """

    # 🔹 Lade die Daten aus der SQLite-Datenbank
    conn = sqlite3.connect("game_results.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT correct_species, 
               SUM(is_correct) * 100.0 / COUNT(*) AS accuracy,
               COUNT(*) AS total_count
        FROM results
        GROUP BY correct_species
        HAVING total_count >= 10  -- 🔹 Filter: Nur Arten mit mind. 10 Audios
        ORDER BY accuracy ASC
    """)
    data = cursor.fetchall()
    conn.close()

    if len(data) < 3:
        return ft.Text("[WARN] Nicht genug Daten für Top 3 Analyse!", color="red")

    # 🔹 Extrahiere die 3 schwierigsten und 3 einfachsten Arten
    top_3_hardest = data[:3]  # Niedrigste Erkennungsrate
    top_3_easiest = data[-3:]  # Höchste Erkennungsrate

    # 🔹 Artennamen übersetzen (falls notwendig)
    top_3_hardest = [
        (lookup_species(name, species_df)["Deutsch"] if lookup_species(name, species_df) else name, f"{accuracy:.0f}%", total_count)
        for name, accuracy, total_count in top_3_hardest
    ]
    top_3_easiest = [
        (lookup_species(name, species_df)["Deutsch"] if lookup_species(name, species_df) else name, f"{accuracy:.0f}%", total_count)
        for name, accuracy, total_count in top_3_easiest
    ]

    # 🔹 Formatierten Text erstellen
    hardest_text = ", ".join([f"{name} ({acc}, {count} Aufnahmen)" for name, acc, count in top_3_hardest])
    easiest_text = ", ".join([f"{name} ({acc}, {count} Aufnahmen)" for name, acc, count in top_3_easiest])

    return ft.Column(
        controls=[
            ft.Text(f"Die drei am besten erkannten Arten sind: {easiest_text}.", color="white"),
            ft.Text(f"Die drei am schlechtesten erkannten Arten sind: {hardest_text}.", color="white"),
        ]
    )




class MainMenu(ft.View):
    def __init__(self, page: ft.Page):
        super().__init__(route="/")
        self.page = page
        self.bgcolor = ft.Colors.BLUE_GREY_900

        dlg = ft.AlertDialog(
            title=ft.Text("Informationen zum Sound-BirdQuiz."),
            content=ft.Text("Ein Spaß-Projekt von L. Griem und J. Pieper. "),
            on_dismiss=lambda e: page.add(ft.Text("Non-modal dialog dismissed")),
        )

        #  Funktion zum Zufälligen Auswählen von 10 Arten & Speichern in settings.json
        def shuffle_and_start_quiz(e):
            print("[DEBUG] Quiz starten: Wähle 10 zufällige Arten")

            # **Falls CSV weniger als 10 Zeilen hat, nehme alle**
            num_species = min(10, len(species_df))

            # **Wähle 10 zufällige Arten**
            random_species = species_df.sample(n=num_species)["Deutsch"].tolist()

            # **Speichere die Zufallsarten als kommaseparierte Liste**
            species_list_str = ", ".join(random_species)
            print("[DEBUG] Zufällige Arten:", species_list_str)

            # **Erstelle die neue settings.json Datei**
            settings_data = {
                "species_list": species_list_str,
                "sound_type": "",
                "show_images": True,
                "show_spectrogram": True,
                "Lifestage": "",
                "Geschlecht": ""
            }

            with open("settings.json", "w", encoding="utf-8") as f:
                json.dump(settings_data, f, ensure_ascii=False, indent=4)

            print("[DEBUG] settings.json aktualisiert!")

            # **Game-Fenster öffnen**
            page.go("/game")


        # --- LINKER BEREICH (Text + Buttons) ---
        left_container = ft.Container(
            width=600,  # fixe Breite für die linke Spalte
            bgcolor=ft.Colors.BLUE_GREY_900,
            padding=5,
            content=ft.Column(
                spacing=30,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Text(
                        "WILLKOMMEN",
                        style="headlineLarge",
                        weight=ft.FontWeight.BOLD,
                        color="white"
                    ),
                    ft.Text(
                        "Teste & trainiere deine Vogelstimmenkenntnisse!",
                        style="titleMedium",
                        color="white"
                    ),
                    ft.ElevatedButton(
                        text="Quiz starten mit neuen Einstellungen",
                        icon=ft.Icons.SETTINGS,
                        width=400,
                        height=40,
                        on_click=lambda e: self.page.go("/settings")
                    ),
                    ft.ElevatedButton(
                        text="Quiz starten mit vorherigen Einstellungen",
                        icon="rotate_left",
                        width=400,
                        height=40,
                        on_click=lambda e: self.page.go("/game")
                    ),
                    ft.ElevatedButton(
                        text="Quiz starten mit 10 zufälligen Vogelarten",
                        icon="shuffle",
                        width=400,
                        height=40,
                        on_click=shuffle_and_start_quiz
                    ),
                    ft.Container(height=10 #Placeholder, um Abstand zu bekommen
                    ),
                ],
            )
        )

        # Bilddateien
        image_files = [
            "puffin.jpg", "vogel3.jpg", "vogel4.jpg",
            "vogel6.jpg", "vogel5.jpg", "puffin_iceland.jpg",
            "vogel7.jpg", "vogel8.jpg", "vogel9.jpg"
        ]

        # GridView für die Bilder
        image_grid = ft.GridView(
            expand=True,
            max_extent=250,  # Max. Breite pro Bild, passt sich dynamisch an
            spacing=0,
            run_spacing=0,
            controls=[
                ft.Image(src=img, fit=ft.ImageFit.COVER) for img in image_files
            ]
        )


        # Overlay-Text für das Quiz
        overlay_text = ft.Container(
            alignment=ft.alignment.center,
            content=ft.Text(
                "SOUND\nBIRD\nQUIZ",
                size=150,
                color=ft.Colors.with_opacity(0.7, 'white'),
                text_align=ft.TextAlign.CENTER,
                weight=ft.FontWeight.BOLD
            )
        )

        # Stack für das überlagerte Layout
        right_container = ft.Container(
            expand=True,
            content=ft.Stack(
                expand=True,
                controls=[
                    image_grid,  # Bildergitter
                    overlay_text  # Text darüber
                ]
            )
        )



        # Info-Button + Copyright-Text zusammen in eine Row
        bottom_left_row = ft.Row(
            alignment=ft.MainAxisAlignment.START,  # Links ausrichten
            spacing=5,  # Kleiner Abstand zwischen Icon und Text
            controls=[
                ft.IconButton(
                    icon=ft.Icons.HELP_OUTLINE,
                    icon_color="white",
                    tooltip="Informationen über das Quiz",
                    on_click=lambda e: page.open(dlg)
                ),
                ft.IconButton(
                    icon=ft.Icons.SETTINGS_OUTLINED,
                    icon_color="white",
                    tooltip="Übergeordnete Einstellungen",
                    on_click=lambda e: self.page.go("/overall_setting")
                ),
                ft.Text(
                    "Recordings von XenoCanto.org. © Sound-BirdQuiz 2025",
                    italic=True,
                    size=10,
                    color="white"
                ),
            ]
        )

        # Container für feste Positionierung unten links
        bottom_left_container = ft.Container(
            content=bottom_left_row,
            alignment=ft.alignment.bottom_left,  # Fixiert unten links
            left=10,  # Abstand vom linken Rand
            bottom=10  # Abstand vom unteren Rand
        )

        # --- Das Gesamt-Layout: Links (600px) + Rechts (Rest) ---
        self.controls = [
            ft.Stack(
                expand=True,  # Stack nimmt gesamte Höhe ein
                controls=[
                    ft.Row(  # Haupt-Layout (Linker + Rechter Container)
                        expand=True,
                        controls=[
                            left_container,
                            right_container
                        ]
                    ),
                    bottom_left_container,  # Fügt den festen Info-Bereich unten links hinzu
                ]
            )
        ]


class Settings(ft.View):
    def __init__(self, page: ft.Page):
        super().__init__(route="/settings")
        self.page = page
        self.bgcolor = ft.Colors.BLUE_GREY_900

        # --- UI-Elemente definieren und in Instanzvariablen speichern, damit wir später darauf zugreifen können ---
        self.species_text_field = ft.TextField(
            helper_text="Komma getrennt",
            hint_text="Vogelarten hier eingeben ...",
            multiline=True,
            min_lines=1,
            max_lines=4,
            expand=False
        )
        self.sound_radio_group = ft.RadioGroup(
            value="All",
            content=ft.Row(
                spacing=20,
                controls=[
                    ft.Radio(value="All", label="All Sounds"),
                    ft.Radio(value="Call", label="Call"),
                    ft.Radio(value="Song", label="Song"),
                    ft.Radio(value="Other", label="Other"),
                ]
            ),
            on_change=self.sound_type_changed  # Callback unten definiert
        )
        self.other_dropdown = ft.Dropdown(
            width=150,
            options=[
                ft.dropdown.Option("Alarm call"),
                ft.dropdown.Option("Begging call"),
                ft.dropdown.Option("Drumming"),
                ft.dropdown.Option("Female song"),
                ft.dropdown.Option("Flight call"),
                ft.dropdown.Option("Imitation"),
                ft.dropdown.Option("Subsong"),
            ],
            visible=False
        )


        # Dropdown für Geschlecht (entspricht Combobox)
        self.selected_sex = ft.Dropdown(
            label="Geschlecht",
            value="All sex",
            options=[
                ft.dropdown.Option("All sex"),
                ft.dropdown.Option("Male"),
                ft.dropdown.Option("Female")
            ],
            expand=True
        )

        # Dropdown für Lifestage (entspricht Combobox)
        self.selected_lifestage = ft.Dropdown(
            label="Alter",
            value="All lifestage",
            options=[
                ft.dropdown.Option("All lifestage"),
                ft.dropdown.Option("Adult"),
                ft.dropdown.Option("Juvenile"),
                ft.dropdown.Option("Nestling")
            ],
            expand=True
        )

        # Für die Switches ebenfalls als Instanzvariablen:
        self.images_switch = ft.Switch(label="Bilder anzeigen", value=False)
        self.spectrogram_switch = ft.Switch(label="Spektrogramm anzeigen", value=True)

        # "Back to Menu"-Button
        top_bar = ft.Container(
            bgcolor=ft.Colors.GREEN_400,  # Oder z.B. ft.Colors.GREEN_ACCENT_400
            padding=10,  # Optional etwas Innenabstand
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        expand=1,
                        alignment=ft.alignment.center_left,
                        content=ft.OutlinedButton(
                            text="Back to Menu",
                            icon=ft.Icons.MENU,
                            icon_color="white",
                            style=ft.ButtonStyle(
                                bgcolor={"": "green_100", ft.ControlState.DISABLED: "grey_100"},
                                color={"": "white", ft.ControlState.DISABLED: "grey"},
                                side=ft.BorderSide(1, ft.Colors.WHITE)
                            ),
                            on_click=lambda e: page.go("/")
                        )
                    ),
                    ft.Container(
                        expand=2,
                        alignment=ft.alignment.center,
                        content=ft.Text("Neue Einstellungen", size=30, weight=ft.FontWeight.BOLD, color="white")
                    ),
                    ft.Container(
                        expand=1,
                        alignment=ft.alignment.center_right,
                        content=ft.Text("")
                    ),
                ]
            )
        )

        # Überschrift
        text_row = ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            controls=[
                ft.Text(
                    "Hier kannst du deine Spieleinstellungen festlegen.",
                    style="bodyMedium",
                    color="white"
                ),
            ],
        )

        # Radiogruppe + Dropdown in einer Zeile
        sound_row = ft.Row(
            spacing=20,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                self.sound_radio_group,
                self.other_dropdown
            ]
        )

        #Funktionen für die Inhalte/Ersetzten bei Menuclick der Artenlisten
        species_lists = {
            "Laubwald": "Blaumeise, Rotkehlchen, Singdrossel, Zaunkönig, Waldlaubsänger, Trauerschnäpper, Kohlmeise, Buntspecht, Gimpel, Zilpzalp, Mönchsgrasmücke, Kleiber",
            "Nadelwald": "Tannenmeise, Haubenmeise, Erlenzeisig, Fichtenkreuzschnabel, Waldbaumläufer, Wintergoldhähnchen",
            "Offenland/Agrarlandschaft": "Feldlerche, Rebhuhn, Neuntöter, Schwarzkehlchen, Dorngrasmücke, Grauammer, Goldammer, Feldsperling, Mäusebussard",
            "Siedlung": "Haussperling, Hausrotschwanz, Blaumeise, Bachstelze, Kohlmeise, Amsel, Feldsperling, Grünfink, Star, Buchfink, Elster",
            "Auenwald": "Pirol, Nachtigall, Kleinspecht, Mittelspecht, Trauerschnäpper, Kohlmeise, Blaumeise, Kleiber, Schwarzspecht, Buchfink",
            "Feuchtgebiet Binnenland": "Bartmeise, Sumpfrohrsänger, Schilfrohrsänger, Eisvogel, Rohrammer, Teichrohrsänger, Zwergtaucher, Waldwasserläufer, Kiebitz",
            "Alpine Zone": "Alpendohle, Mauerläufer, Bergpieper, Taigabirkenzeisig, Hausrotschwanz, Alpenbraunelle",
            "Küste (typische Arten)": "Austernfischer, Silbermöwe, Sandregenpfeifer, Brandgans, Lachmöwe, Alpenstrandläufer, Rotschenkel, Eiderente",
            "Watvögel": "Rotschenkel, Grünschenkel, Flussuferläufer, Waldwasserläufer, Bruchwasserläufer, Dunkler Wasserläufer, Alpenstrandläufer, Sandregenpfeifer",
            "Drosseln": "Singdrossel, Ringdrossel, Amsel, Misteldrossel",
            "Mitteleuropäische Grasmücken": "Mönchsgrasmücke, Gartengrasmücke, Klappergrasmücke, Dorngrasmücke, Sperbergrasmücke",
            "Meisen": "Blaumeise, Kohlmeise, Sumpfmeise, Weidenmeise, Tannenmeise, Schwanzmeise, Haubenmeise",
            "Spechte": "Buntspecht, Kleinspecht, Schwarzspecht, Weißrückenspecht, Dreizehenspecht, Grünspecht, Grauspecht, Mittelspecht",
            "Möwen": "Silbermöwe, Lachmöwe, Heringsmöwe, Mantelmöwe, Sturmmöwe",
            "Eulen": "Waldkauz, Waldohreule, Uhu, Sperlingskauz, Raufußkauz, Schleiereule",
            "Rohrsänger": "Teichrohrsänger, Sumpfrohrsänger, Drosselrohrsänger, Schilfrohrsänger",
            "Greifvögel": "Sperber, Turmfalke, Mäusebussard, Habicht, Rotmilan, Rohrweihe",
            "Enten": "Stockente, Krickente, Knäkente, Reiherente, Schnatterente, Löffelente, Pfeifente, Tafelente, Schellente",
            "Laubsänger": "Zilpzalp, Fitis, Waldlaubsänger, Berglaubsänger",
            "Schnäpper": "Trauerschnäpper, Grauschnäpper, Halsbandschnäpper, Zwergschnäpper",
            "Ammern": "Goldammer, Grauammer, Zippammer, Zaunammer",
            "Singvogelzug": "Buchfink, Bergfink, Heckenbraunelle, Singdrossel, Rotdrossel, Feldlerche, Wacholderdrossel, Heidelerche, Haubenlerche, Baumpieper, Wiesenpieper, Erlenzeisig",
            "Pieper": "Baumpieper, Wiesenpieper, Bergpieper, Rotkehlpieper, Brachpieper, Waldpieper",
            "Eisvogel-Heckenbraunelle (Call)": "Eisvogel, Heckenbraunelle",
            "Zippammer-Zaunammer (Call)": "Zippammer, Zaunammer",
            "Blaumerle-Steinrötel (Song)": "Blaumerle, Steinrötel",
            "Bergfink-Buchfink (Other: Flightcall)": "Bergfink, Buchfink",
            "Amsel-Misteldrossel (Song)": "Amsel, Misteldrossel",
            "Fitis-Gartenrotschwanz (Call)": "Fitis, Gartenrotschwanz"
        }

        # Liste der "Call"-Kategorien
        call_categories = [
            "Eisvogel-Heckenbraunelle (Call)",
            "Zippammer-Zaunammer (Call)",
            "Fitis-Gartenrotschwanz (Call)"
        ]

        song_categories = [
            "Amsel-Misteldrossel (Song)",
            "Blaumerle-Steinrötel (Song)"
        ]

        def update_species_list(e, key):
            # Setze die Artenliste
            self.species_text_field.value = species_lists[key]

            # Falls "Leicht verwechselbar" gewählt wurde, ändere auch Sound-Optionen
            if key == "Bergfink-Buchfink (Other: Flightcall)":
                self.sound_radio_group.value = "Other"  # Setzt das Radio auf "Other"
                self.other_dropdown.value = "Flight call"  # Standardwert im Dropdown setzen
                self.other_dropdown.visible = True  # Zeigt den Dropdown an
            # Falls eine der Call-Kategorien gewählt wurde, Sound auf "Call" setzen
            if key in call_categories:
                self.sound_radio_group.value = "Call"
            # Falls eine der Song-Kategorien gewählt wurde, Sound auf "Song" setzen
            if key in song_categories:
                self.sound_radio_group.value = "Song"

            self.page.update()  # Aktualisiere die Seite

        #Menu Button einzeln
        menu_one = ft.Row(
            alignment=ft.MainAxisAlignment.START,
            controls=[
                ft.SubmenuButton(
                    content=ft.Text("Liste auswählen"),
                    leading=ft.Icon(ft.Icons.WYSIWYG),
                    controls=[
                        ft.SubmenuButton(
                            content=ft.Text("Habitate"),
                            leading=ft.Icon(ft.Icons.FOREST),
                            style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN_100}),
                            controls=[
                                ft.MenuItemButton(
                                    content=ft.Text("Alpine Zone"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Alpine Zone")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Auenwald"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Auenwald")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Feuchtgebiet Binnenland"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Feuchtgebiet Binnenland")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Küste (typische Arten)"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Küste (typische Arten)")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Laubwald"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Laubwald")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Nadelwald"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Nadelwald")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Offenland/Agrarlandschaft"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Offenland/Agrarlandschaft")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Siedlung"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Siedlung")
                                )
                            ]
                        ),
                        ft.SubmenuButton(
                            content=ft.Text("Artengruppe"),
                            leading=ft.Icon(ft.Icons.GROUPS),
                            style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN_100}),
                            controls=[
                                ft.MenuItemButton(
                                    content=ft.Text("Ammern"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Ammern")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Drosseln"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Drosseln")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Enten"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Enten")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Eulen"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Eulen")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Greifvögel"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Greifvögel")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Laubsänger"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Laubsänger")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Meisen"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Meisen")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Mitteleuropäische Grasmücken"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Mitteleuropäische Grasmücken")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Möwen"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Möwen")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Pieper"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Pieper")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Rohrsänger"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Rohrsänger")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Schnäpper"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Schnäpper")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Singvogelzug"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Singvogelzug")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Spechte"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Spechte")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Watvögel"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Watvögel")
                                )
                            ]
                        ),
                        ft.SubmenuButton(
                            content=ft.Text("Leicht verwechselbar"),
                            leading=ft.Icon(ft.Icons.COMPARE_ARROWS),
                            style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN_100}),
                            controls=[
                                ft.MenuItemButton(
                                    content=ft.Text("Amsel-Misteldrossel (Song)"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Amsel-Misteldrossel (Song)")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Bergfink-Buchfink (Other: Flightcall)"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Bergfink-Buchfink (Other: Flightcall)")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Blaumerle-Steinrötel (Song)"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Blaumerle-Steinrötel (Song)")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Eisvogel-Heckenbraunelle (Call)"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Eisvogel-Heckenbraunelle (Call)")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Fitis-Gartenrotschwanz (Call)"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Fitis-Gartenrotschwanz (Call)")
                                ),
                                ft.MenuItemButton(
                                    content=ft.Text("Zippammer-Zaunammer (Call)"),
                                    style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
                                    on_click=lambda e: update_species_list(e, "Zippammer-Zaunammer (Call)")
                                )
                            ]
                        ),
                    ],
                ),
            ]
        )

        #Row für Switch udn Lifestage/Geschlecht Dropdown
        lifestage_row = ft.Row(
            spacing=20,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                self.selected_sex,
                self.selected_lifestage
            ]
        )



        # Container mit ListView (scrollable!)
        settings_container = ft.Container(
            width=800,
            height=400,  # Feste Höhe für Scrollbarkeit
            padding=ft.Padding(30, 30, 30, 30),
            bgcolor="#f2f2f2",  # Helles Grau für Formularbox
            border_radius=10,
            content=ft.ListView(
                expand=True,
                spacing=15,
                controls=[
                    ft.Text(
                        "Welche Arten möchtest du üben?",
                        style="titleSmall",
                        weight=ft.FontWeight.BOLD
                    ),
                    ft.Text(
                        "Trage die Namen der Arten ein oder wähle eine bestehende Liste aus.",
                        style="body_small",
                        weight=ft.FontWeight.NORMAL
                    ),
                    self.species_text_field,
                    menu_one,
                    # Divider
                    ft.Container(
                        alignment=ft.alignment.center,
                        bgcolor=ft.Colors.GREEN_400,
                        border_radius=5,
                        height=10
                    ),
                    ft.Text(
                        "Soundtyp spezifizieren",
                        style="titleSmall",
                        weight=ft.FontWeight.BOLD
                    ),
                    # Hier fügen wir die Zeile mit Radiogruppe + Dropdown ein
                    sound_row,

                    #Zeile für Lifestage/Geschlecht
                    lifestage_row,

                    # Divider
                    ft.Container(
                        alignment=ft.alignment.center,
                        bgcolor=ft.Colors.GREEN_400,
                        border_radius=5,
                        height=10
                    ),
                    # Zwei Switches
                    self.spectrogram_switch,
                    self.images_switch,

                ]
            )
        )

        # "Save & Start Quiz"-Button außerhalb des Containers
        save_and_start_button = ft.Container(
            alignment=ft.alignment.bottom_center,
            padding=30,
            content=ft.ElevatedButton(
                text="Save & Start Quiz",
                icon=ft.Icons.PLAY_ARROW,
                icon_color="white",
                color="white",
                bgcolor="green",
                on_click=self.save_and_start
            )
        )

        #CSV Tabelle anzeigen-Container
        # Schließfunktion für den Dialog
        def close_settings_dialog(e):
            page.close(dlg_modal)
            page.add(ft.Text(f"Modal dialog closed with action: {e.control.text}"))

        # Funktion, um den Dialog-Inhalt auf die CSV-Tabelle umzustellen
        def show_csv_table(e):
            print("[DEBUG] show_csv_table wurde aufgerufen")

            # 🔹 Lokale Filterfunktion
            def update_table(search_value):
                filtered_df = species_df[
                    species_df.apply(lambda row: search_value.lower() in str(row).lower(), axis=1)
                ]

                rows = [
                    ft.DataRow(cells=[ft.DataCell(ft.Text(str(cell))) for cell in row])
                    for row in filtered_df.values
                ]
                data_table.rows = rows
                page.update()

            # 🔹 Suchfeld mit Callback bei Änderung
            search_field = ft.TextField(
                hint_text="Nach Art suchen...",
                on_change=lambda e: update_table(e.control.value),
                autofocus=True,
                width=780
            )

            # 🔹 Initiale Tabelle
            columns = [ft.DataColumn(ft.Text(col)) for col in species_df.columns]
            data_table = ft.DataTable(columns=columns, rows=[
                ft.DataRow(cells=[ft.DataCell(ft.Text(str(cell))) for cell in row])
                for row in species_df.values
            ])

            # 🔹 Neuen Inhalt setzen
            dlg_modal.title = ft.Text("Mögliche Arten für die Liste")
            dlg_modal.content = ft.Container(
                width=800,
                height=500,
                padding=ft.Padding(20, 20, 20, 20),
                content=ft.Column(
                    controls=[
                        search_field,
                        ft.Divider(height=10, color="transparent"),
                        ft.Container(data_table, expand=True, bgcolor=ft.Colors.GREEN_ACCENT_100)
                    ],
                    expand=True,
                    scroll="adaptive"
                )
            )
            dlg_modal.actions = [
                ft.TextButton("Schließen", on_click=close_settings_dialog)
            ]

            dlg_modal.open = True
            page.dialog = dlg_modal
            page.update()

        # Erstelle den Settings-Dialog
        dlg_modal = ft.AlertDialog(
            modal=True,
            title=ft.Text("Wie lege ich neue Einstellungen fest?"),
            content=ft.Text("Infos über den Ablauf hier.\nDrücke 'Tabelle anzeigen', um die CSV-Tabelle zu sehen."),
            actions=[
                ft.TextButton("Tabelle anzeigen", on_click=show_csv_table),
                ft.TextButton("Schließen", on_click=close_settings_dialog),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        #Info-Button erstellen
        settings_info = ft.IconButton(
                        icon=ft.Icons.HELP_OUTLINE,
                        icon_color="white",
                        tooltip="Informationen zu den Einstellungen",
                        on_click=lambda e: page.open(dlg_modal)
                    )

        # Container für den Info-Button mit fester Positionierung
        info_container = ft.Container(
            content=settings_info,
            alignment=ft.alignment.bottom_left,  # Position unten links
        )

        #Gesamtlayout
        self.controls = [
            ft.Stack(
                expand=True,  # Stack nimmt die gesamte Höhe ein
                controls=[
                    # Haupt-Layout bleibt normal klickbar
                    ft.Column(
                        spacing=20,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            top_bar,
                            text_row,
                            settings_container,  # Buttons im Settings-Container bleiben klickbar!
                        ],
                    ),
                    # Absolut platzierter Start-Button (unten mittig)
                    ft.Container(
                        content=save_and_start_button,
                        bottom=20,  # Fixiere den Button unten
                        left=0,  # Zentriert ausrichten
                        right=0  # Stellt sicher, dass es mittig bleibt
                    ),
                    # Absolut platzierter Info-Button (unten links)
                    ft.Container(
                        content=info_container,
                        bottom=10,  # Abstand vom unteren Rand
                        left=10  # Abstand vom linken Rand
                    ),
                ]
            )
        ]


    # Callback für die Radiogruppe
    def sound_type_changed(self, e):
        if self.sound_radio_group.value == "Other":
            self.other_dropdown.visible = True
        else:
            self.other_dropdown.visible = False
        self.page.update()



    # Funktion zum Speichern der Einstellungen in einer JSON-Datei
    def save_settings(self, e):
        # Standardmäßig den Wert der Radiogruppe übernehmen
        sound_type_value = self.sound_radio_group.value
        # Wenn "Other" ausgewählt ist, den Wert aus dem Dropdown verwenden
        if sound_type_value == "Other":
            sound_type_value = self.other_dropdown.value
            print("sound_type überschrieben mit:", sound_type_value)
        # Wenn "Alle Soundtypen" ausgewählt ist, den Wert mit "" ersetzen
        if sound_type_value == "All":
            sound_type_value = ""

        sex_value = self.selected_sex.value
        # Wenn "Other" ausgewählt ist, den Wert aus dem Dropdown verwenden
        if sex_value == "All sex":
            sex_value = ""

        lifestage_value = self.selected_lifestage.value
        # Wenn "Other" ausgewählt ist, den Wert aus dem Dropdown verwenden
        if lifestage_value == "All lifestage":
            lifestage_value = ""


        settings_data = {
            "species_list": self.species_text_field.value,
            "sound_type": sound_type_value,
            "show_images": self.images_switch.value,
            "show_spectrogram": self.spectrogram_switch.value,
            "Lifestage": lifestage_value,
            "Geschlecht": sex_value,
        }
        with open("settings.json", "w") as f:
            json.dump(settings_data, f)
        self.page.snack_bar = ft.SnackBar(ft.Text("Settings saved!"))
        self.page.snack_bar.open = True
        self.page.update()

    def save_and_start(self, e):
        # Speichern der Einstellungen
        self.save_settings(e)
        # Anschließend zum Spiel wechseln
        self.page.go("/game")

class Game(ft.View):
    def __init__(self, page: ft.Page):
        super().__init__(route="/game")
        self.page = page
        self.answer_submitted = False
        self.bgcolor = ft.Colors.BLUE_GREY_900

        # Spielvariablen
        self.selected_species = []
        self.current_audio = None
        self.correct_species = None
        self.player = None

        # UI-Elemente
        # Rundenzähler initialisieren
        self.round = 1
        self.round_label = ft.Text(f"Runde {self.round}", style="headlineSmall", color=ft.Colors.WHITE)

        self.audio_button = ft.OutlinedButton(
            text="Repeat Audio",
            icon=ft.Icons.VOLUME_UP,
            icon_color="white",
            style=ft.ButtonStyle(
                bgcolor={"": "green_100", ft.ControlState.DISABLED: "grey_100"},
                color={"": "white", ft.ControlState.DISABLED: "grey"}
            ),
            on_click=self.repeat_audio
        )

        # ✅ AlertDialog wird hier als Instanzattribut gespeichert
        self.dlg_no_answer = ft.AlertDialog(
            modal=False,
            title=ft.Text("Hinweis"),
            content=ft.Text("Es muss mindestens eine Antwort geben, um Ergebnisse erstellen zu können."),
            on_dismiss=lambda e: print("[DEBUG] Hinweis-Dialog geschlossen")
        )

        # Dialog der Seite zuweisen
        self.page.dialog = self.dlg_no_answer


        self.species_buttons_container = ft.ListView(
            height=90, #Feste Höhe. Wenn mehr Arten sind (ab 3 Reihen), kann gescrolled werden
            spacing=10,
            controls=[]
        )

        self.feedback_text = ft.Text("", style="titleMedium")


        #Frame für Spektrogram
        self.media_image = ft.Image(
            src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADElEQVR42mP8/5+hHgAHggJ/PFC2GAAAAABJRU5ErkJggg==",
            width=480,
            height=160,
            fit=ft.ImageFit.CONTAIN,
            border_radius=5
        )

        self.copyright_info = ft.IconButton(icon=ft.Icons.COPYRIGHT_OUTLINED,icon_size=18, icon_color="grey", tooltip="Info zum Audio/Bild")

        # Buttons: Next und Skip
        self.next_button = ft.ElevatedButton(
            text="Next",
            icon=ft.Icons.ARROW_FORWARD,
            style=ft.ButtonStyle(
                bgcolor={"": "green", ft.ControlState.DISABLED: "grey"},
                color={"": "white", ft.ControlState.DISABLED: "grey_200"},
                icon_color = {"": "white", ft.ControlState.DISABLED: "grey_200"}
            ),
            width=200,
            on_click=self.next_round
        )
        self.skip_button = ft.ElevatedButton(
            text="Skip",
            icon=ft.Icons.SKIP_NEXT,
            style=ft.ButtonStyle(
                bgcolor={"": "green", ft.ControlState.DISABLED: "grey"},
                color={"": "white", ft.ControlState.DISABLED: "grey_200"},
                icon_color={"": "white", ft.ControlState.DISABLED: "grey_200"}
            ),
            width=200,
            on_click=self.skip_round
        )
        top_bar = ft.Container(
            bgcolor=ft.Colors.GREEN_700,  # Oder z.B. ft.Colors.GREEN_ACCENT_400
            padding=10,  # Optional etwas Innenabstand
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        expand=1,
                        alignment=ft.alignment.center_left,
                        content=ft.OutlinedButton(
                            text="Back to Menu",
                            icon=ft.Icons.MENU,
                            icon_color="white",
                            style=ft.ButtonStyle(
                                bgcolor={"": "green_100", ft.ControlState.DISABLED: "grey_100"},
                                color={"": "white", ft.ControlState.DISABLED: "grey"},
                                side=ft.BorderSide(1, ft.Colors.WHITE)
                            ),
                            on_click=lambda e: page.go("/")
                        )
                    ),
                    ft.Container(
                        expand=2,
                        alignment=ft.alignment.center,
                        content=ft.Text("Welche Art hörst du?", size=30, weight=ft.FontWeight.BOLD, color="white")
                    ),
                    ft.Container(
                        expand=1,
                        alignment=ft.alignment.center_right,
                        content=ft.OutlinedButton(
                            text="End Game & Show Results",
                            icon=ft.Icons.REPLAY,
                            icon_color="white",
                            style=ft.ButtonStyle(
                                bgcolor={"": "green_100", ft.ControlState.DISABLED: "grey_100"},
                                color={"": "white", ft.ControlState.DISABLED: "grey"},
                                side=ft.BorderSide(1, ft.Colors.WHITE)
                            ),
                            on_click=self.check_before_navigate
                        )
                    ),
                ]
            )
        )


        # Haupt-Layout
        self.main_content = ft.Column(
                spacing=10,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    top_bar,
                    self.round_label,
                    self.audio_button,
                    self.media_image,
                    self.copyright_info,
                    self.species_buttons_container,
                    self.feedback_text,
                    ft.Row(
                        spacing=20,
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[self.skip_button, self.next_button]
                    ),

                ],
            )

        # Erstelle einen Splash Screen als Overlay (zunächst unsichtbar)
        self.splash_container = ft.Container(
            expand=True,
            visible=False,  # anfänglich nicht sichtbar
            alignment=ft.alignment.center,
            bgcolor=ft.Colors.BLUE_GREY_900,
            content=ft.Column(
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
                controls=[
                    ft.ProgressRing(width=100, height=100, color=ft.Colors.WHITE),
                    ft.Text("Neue Recordings werden geladen...", style="headlineSmall", color=ft.Colors.WHITE)
                ]
            )
        )

        # Packe den Hauptinhalt und den Splash Screen in einen Stack
        self.page_layout = ft.Stack(
            expand=True,
            controls=[
                self.main_content,
                self.splash_container  # Dieser liegt über dem Hauptinhalt
            ]
        )

        # Setze das gesamte Layout als Inhalt der View
        self.controls = [self.page_layout]

        # **Höchste gespeicherte session_id abrufen und um 1 erhöhen**
        last_session_id = get_last_session_id()  # Holt die letzte gespeicherte Session-ID aus SQLite
        self.session_id = last_session_id + 1  # Neue Session-ID (immer um 1 höher)

        # **Speichern der neuen Session-ID in Flet**
        self.page.session.set("session_id", self.session_id)
        print(f"[DEBUG] Neue Session-ID: {self.session_id}")

        # Lade gespeicherte Einstellungen, baue die Arten-Buttons & Initialisiere das Quiz
        self.load_settings()
        self.update_species_buttons()
        if self.show_images:
            cache_bird_images(self.selected_species)  # Bilder herunterladen & speichern
        self.start_new_round()




    def show_loading(self):
        self.splash_container.visible = True
        self.page.update()


    def hide_loading(self):
        self.splash_container.visible = False
        self.page.update()

    def backtomenu (self,e):
        # Audio stoppen
        if self.player is not None:
            self.player.stop()
        #Redirect
        self.page.go("/")


    def check_before_navigate(self, e):
        """Überprüft, ob eine Antwort gegeben wurde, bevor zur Ergebnis-Seite gewechselt wird."""

        if not self.answer_submitted:  # ❗ Falls keine Antwort gespeichert wurde
            print("[DEBUG] Keine Antwort gespeichert!")  # ✅ Debugging
            # Audio stoppen
            if self.player:
                self.player.stop()

            self.page.open(self.dlg_no_answer)

        else:
            # 🔹 Falls Antwort existiert, normal navigieren
            self.gotoresults(e)


    def gotoresults (self,e, dialog=None):
        # Audio stoppen
        if self.player is not None:
            self.player.stop()
        self.page.go("/results")  # Setzt die Route zur Ergebnis-Seite

    def load_settings(self):
        """Lädt die gespeicherten Einstellungen aus der JSON-Datei."""
        if os.path.exists("settings.json"):
            with open("settings.json", "r",encoding="utf-8") as f:
                settings = json.load(f)
            print("[DEBUG] Geladene species_list:", settings["species_list"])
            species_list_str = settings.get("species_list", "")
            # Konvertiere den Text in ein Mapping:
            self.species_mapping = convert_species_list(species_list_str)
            # Speichere als Liste der wissenschaftlichen Namen (für API-Abrufe)
            self.selected_species = list(self.species_mapping.keys())
            self.sound_type = settings.get("sound_type", "")
            self.show_images = settings.get("show_images", "")
            self.show_spectrogram = settings.get("show_spectrogram", False)
            self.selected_lifestage = settings.get("Lifestage", "")
            self.selected_sex = settings.get("Geschlecht", "")
        else:
            species_list_str = ""
            self.species_mapping = {}
            self.selected_species = ["blaumeise", "kohlmeise"]
            self.sound_type = ""
            self.show_images = False
            self.show_spectrogram = True
            self.selected_lifestage = ""
            self.selected_sex = ""


        self.page.update()


    def update_species_buttons(self):
        """Erstellt Buttons für die möglichen Arten."""
        self.species_buttons_container.controls.clear()  # Vorherige Buttons entfernen
        buttons = []
        for scientific in self.selected_species:
            # Hole den angezeigten Namen aus dem Mapping
            display_name = self.species_mapping.get(scientific, scientific)
            btn = ft.OutlinedButton(
                text=display_name,
                style=ft.ButtonStyle(
                    bgcolor={"": "green_accent_700", ft.ControlState.DISABLED: "grey_100"},
                    color={"": "white", ft.ControlState.DISABLED: "grey"}
                ),
                on_click=lambda e, s=scientific: self.check_answer(s)
            )
            buttons.append(btn)

        # Beispiel: Erstelle eine Column, in der du dynamisch Rows (Zeilen) erzeugst:
        max_buttons_per_row = 8
        rows = []
        current_row = []
        for idx, btn in enumerate(buttons):
            current_row.append(btn)
            if (idx + 1) % max_buttons_per_row == 0:
                rows.append(ft.Row(controls=current_row, spacing=10, alignment=ft.MainAxisAlignment.CENTER))
                current_row = []
        if current_row:
            rows.append(ft.Row(controls=current_row, spacing=10, alignment=ft.MainAxisAlignment.CENTER))

        # Setze die erstellten Rows als Controls des ListView
        self.species_buttons_container.controls = rows
        self.page.update()



    async def async_get_random_recording(self, scientific, sound_type, selected_sex, selected_lifestage):
        """
        Führt die API-Abfrage asynchron durch und cached die Antwort.
        Verwendet den wissenschaftlichen Namen (scientific) und zusätzliche Filter:
          - sound_type: Aufnahmetyp (z.B. "Call", "Song", etc.)
          - selected_sex: Geschlecht
          - selected_lifestage: Lifestage
        """
        key = (scientific, sound_type, selected_sex, selected_lifestage)
        if key in api_cache:
            data = api_cache[key]
        else:
            sound_type_final = sound_type.lower() if sound_type else ""
            type_query = f'+type:"{sound_type_final}"' if sound_type_final else ""
            sex_type_final = selected_sex.lower() if selected_sex else ""
            sex_query = f'+sex:"{sex_type_final}"' if sex_type_final else ""
            lifestage_final = selected_lifestage.lower() if selected_lifestage else ""
            lifestage_query = f'+stage:"{lifestage_final}"' if lifestage_final else ""
            url = f'https://www.xeno-canto.org/api/2/recordings?query={scientific}{type_query}{sex_query}{lifestage_query}'
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    data = await response.json()
                    api_cache[key] = data  # Cache die Antwort
        recordings = data.get("recordings", [])
        if not recordings:
            return None
        rec = random.choice(recordings)
        audio_url = rec.get("file")
        sonogram_data = rec.get("sono", {}).get("med")
        sonogram_url = "https:" + sonogram_data if sonogram_data else None
        print(sonogram_url)
        rec_value = rec.get("rec")
        lic_value = rec.get("lic")
        combined_info = ""
        if rec_value:
            combined_info += f"Recorded by {rec_value}"
        if lic_value:
            if combined_info:
                combined_info += " | "
            combined_info += f" \nLicensed under: https:{lic_value}"
        return {
            "audio_url": audio_url,
            "sonogram_url": sonogram_url,
            "correct_species": scientific,
            "copyright_info": combined_info
        }

    async def load_recording_async(self):
        """
        Wrapper, der eine zufällige Art aus deiner Liste (self.selected_species) auswählt und
        dann async_get_random_recording mit den entsprechenden Einstellungen aufruft.
        Für die laufende Runde.
        """
        scientific = random.choice(self.selected_species)
        rec = await self.async_get_random_recording(scientific, self.sound_type, self.selected_sex, self.selected_lifestage)
        return rec


    def prefetch_next_round(self):
        """
        Lädt im Hintergrund schon das Recording für die nächste Runde.
        """
        async def _prefetch():
            # Wähle zufällig einen wissenschaftlichen Namen aus
            random_species = random.choice(self.selected_species)
            recording = await self.async_get_random_recording(
                random_species,
                self.sound_type,
                self.selected_sex,
                self.selected_lifestage
            )
            self.prefetched_recording = recording
            if self.page:
                self.page.update()
            else:
                print("[ERROR] self.page ist None!")

        self.page.run_task(_prefetch)

    def start_new_round(self):
        if not self.selected_species:
            self.feedback_text.value = "Hinweis: Keine Arten ausgewählt!"
            self.feedback_text.color = "red"
            self.page.update()
            return

        # Zeige den Splash Screen
        self.show_loading()

        # Buttons aktivieren/deaktivieren
        self.skip_button.disabled = False
        self.next_button.disabled = True
        for btn in self.species_buttons_container.controls:
            btn.disabled = False



        def update_ui(recording):
            if recording:
                self.current_audio = recording["audio_url"]
                self.correct_species = recording["correct_species"]
                if self.show_spectrogram and recording.get("sonogram_url"):
                    fetch_and_display_sonogram(recording["sonogram_url"], self.media_image)
                else:
                    self.media_image.src = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADElEQVR42mP8/5+hHgAHggJ/PFC2GAAAAABJRU5ErkJggg=="
                # Aktualisiere den Tooltip-Text des Copyright-Buttons
                self.copyright_info.tooltip = recording.get("copyright_info", "Keine Info verfügbar")
                # Automatisch das Audio abspielen:
                self.play_audio()  # Übergibt None als e

            else:
                self.feedback_text.value = "Kein Audio gefunden!"
            # Verberge den Splash Screen, sobald alles geladen ist
            self.hide_loading()
            self.page.update()
            # Starte sofort den nächsten Prefetch im Hintergrund
            self.prefetch_next_round()

        # Überprüfe, ob ein vorab geladenes Recording vorhanden ist
        if hasattr(self, "prefetched_recording") and self.prefetched_recording:
            recording = self.prefetched_recording
            self.prefetched_recording = None
            update_ui(recording)
        else:
            # Wenn nicht, lade das Recording asynchron
            task = self.page.run_task(self.load_recording_async)
            task.add_done_callback(lambda fut: update_ui(fut.result()))


    def play_audio(self, e=None):
        """Spielt das aktuelle Audio ab."""
        if self.current_audio:

            self.player = vlc.MediaPlayer(self.current_audio)

            def run_player():
                self.player.play()

            threading.Thread(target=run_player, daemon=True).start()

    def repeat_audio(self, e):
        #Audio stoppen, damit es von vorne läuft
        if self.player is not None:
            self.player.stop()

        """Spielt das aktuelle Audio ab."""
        if self.current_audio:

            self.player = vlc.MediaPlayer(self.current_audio)

            def run_player():
                self.player.play()

            threading.Thread(target=run_player, daemon=True).start()

    def save_result(self, correct_species, selected_species, is_correct):
        """Speichert das Ergebnis einer einzelnen Runde mit der aktuellen Session-ID."""
        session_id = self.session_id  # Aktuelle Session-ID der Runde verwenden

        conn = sqlite3.connect("game_results.db")
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO results (session_id, correct_species, selected_species, is_correct, timestamp)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (session_id, correct_species, selected_species, is_correct))

        conn.commit()
        conn.close()
        print(
            f"[DEBUG] Ergebnis gespeichert: {correct_species} - {selected_species} ({'Richtig' if is_correct else 'Falsch'}) in Session {session_id}")

    def check_answer(self, selected_scientific):
        # 1. Audio stoppen
        if self.player:
            self.player.stop()

        # Antwort prüfen
        is_correct = 1 if selected_scientific.strip().lower() == self.correct_species.strip().lower() else 0

        # 2. Alle Buttons durchgehen und Farben anpassen
        for btn_row in self.species_buttons_container.controls:  # Jede Zeile im Grid
            for btn in btn_row.controls:  # Jeder Button in der Zeile
                if btn.text == self.species_mapping.get(selected_scientific, selected_scientific):
                    if is_correct:
                        btn.style.bgcolor = ft.colors.GREEN
                    else:
                        btn.style.bgcolor = "red"
                # Nach der Auswahl sollen alle Buttons deaktiviert werden
                btn.disabled = True
                btn.update()

        # 3. Skip-Button deaktivieren und Next-Button aktivieren
        self.skip_button.disabled = True
        self.next_button.disabled = False


        # Speichere das Ergebnis mit der aktuellen Session-ID
        self.save_result(self.correct_species, selected_scientific, is_correct)
        self.answer_submitted = True  # ✅ Markiert, dass check_answer() aufgerufen wurde

        # UI aktualisieren
        if is_correct:
            self.feedback_text.value = "Richtig!"
            self.feedback_text.color = "green"
        else:
            correct_display = self.species_mapping.get(self.correct_species, self.correct_species)
            self.feedback_text.value = f"Falsch! Es war {correct_display}."
            self.feedback_text.color = "red"


        # 5. Vogelbild laden und anzeigen:
        # Hier nutzen wir load_bird_image, um die URL zu erhalten.
        if self.show_images:
            # Vogelbild laden und anzeigen:
            image_url = load_bird_image(self.correct_species)  # load_bird_image gibt z.B. "http://localhost:8000/<safe_name>/image_0.jpg" zurück
            print(f"[DEBUG] Lade Bild von: {image_url}")
            self.media_image.src = image_url
            self.media_image.update()

            # Metadaten laden und Tooltip aktualisieren:
            metadata = load_image_metadata(self.correct_species)
            photo_author = metadata.get("author", "Keine Info verfügbar")
            photo_license = metadata.get("license", "Keine Info verfügbar")
            tooltip_text = f"Picture by: {photo_author}\nLicensed under: {photo_license}"
            print(f"[DEBUG] Aktualisiere Tooltip: {tooltip_text}")
            self.copyright_info.tooltip = tooltip_text
            # Falls dein Widget update() benötigt:
            self.copyright_info.update()
        else:
            print("[DEBUG] show_images ist False – kein Bild wird angezeigt.")


        self.page.update()

    

    def next_round(self, e):
        """Wird aufgerufen, wenn der Next-Button gedrückt wird."""
        # Stoppe laufende Audio
        if self.player is not None:
            self.player.stop()

        #Sono Bild repracen
        self.media_image.src = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADElEQVR42mP8/5+hHgAHggJ/PFC2GAAAAABJRU5ErkJggg=="

        #Feedback Text entfernen
        self.feedback_text.value = ""

        # Alle Buttons aktivieren & Farbe zurücksetzen
        for btn_row in self.species_buttons_container.controls:  # Jede Zeile im Grid
            for btn in btn_row.controls:  # Jeder Button in der Zeile
                btn.disabled = False
                btn.style.bgcolor = "green_accent_700"  # Originalfarbe wieder setzen
                btn.update()

        #  Skip-Button aktivieren und Next-Button deaktivieren
        self.skip_button.disabled = False
        self.next_button.disabled = True

        # Erhöhe den Rundenzähler und aktualisiere das Label
        self.round += 1
        self.round_label.value = f"Runde {self.round}"

        self.page.update()

        self.start_new_round()

    def skip_round(self, e):
        """Wird aufgerufen, wenn der Skip-Button gedrückt wird."""
        if self.player is not None:
            self.player.stop()

        # Species Buttons deaktivieren
        for btn in self.species_buttons_container.controls:
            btn.disabled = True

        # Hole den anzuzeigenden Namen aus dem Mapping (z. B. in Deutsch)
        correct_display = self.species_mapping.get(self.correct_species, self.correct_species)
        self.feedback_text.value = f"Skipped! Korrekt war: {correct_display}."
        self.feedback_text.color = "yellow"

        # Next Button aktivieren
        self.next_button.disabled = False

        self.page.update()



class Results(ft.View):
    def __init__(self, page: ft.Page):
        super().__init__(route="/results")
        self.page = page
        self.bgcolor = ft.Colors.BLUE_GREY_900

        # 🟢 Content-Bereich (rechts)
        self.content_area = ft.Column(expand=True)

        # 🟢 Menü-Button oben links
        toggle_drawer_btn = ft.IconButton(
            icon=ft.Icons.ARROW_CIRCLE_LEFT,
            icon_color=ft.Colors.GREEN_700,
            icon_size=40,
            tooltip="Navigation anzeigen",
            on_click=lambda e: self.page.open(self.drawer)
        )

        # **Top-Bar mit Zurück- & Wiederholen-Button und Titel**
        top_bar = ft.Container(
            bgcolor=ft.Colors.GREEN_700,  # Oder z.B. ft.Colors.GREEN_ACCENT_400
            padding=10,  # Optional etwas Innenabstand
            content=ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Container(
                        expand=1,
                        alignment=ft.alignment.center_left,
                        content=ft.OutlinedButton(
                            text="Back to Menu",
                            icon=ft.Icons.MENU,
                            icon_color="white",
                            style=ft.ButtonStyle(
                                bgcolor={"": "green_100", ft.ControlState.DISABLED: "grey_100"},
                                color={"": "white", ft.ControlState.DISABLED: "grey"},
                                side=ft.BorderSide(1, ft.Colors.WHITE)
                            ),
                            on_click=lambda e: page.go("/")
                        )
                    ),
                    ft.Container(
                        expand=2,
                        alignment=ft.alignment.center,
                        content=ft.Text("Ergebnisse", size=30, weight=ft.FontWeight.BOLD, color="white")
                    ),
                    ft.Container(
                        expand=1,
                        alignment=ft.alignment.center_right,
                        content=ft.OutlinedButton(
                            text="Repeat Game",
                            icon=ft.Icons.REPLAY,
                            icon_color="white",
                            style=ft.ButtonStyle(
                                bgcolor={"": "green_100", ft.ControlState.DISABLED: "grey_100"},
                                color={"": "white", ft.ControlState.DISABLED: "grey"},
                                side=ft.BorderSide(1, ft.Colors.WHITE)
                            ),
                            on_click=lambda e: page.go("/game")
                        )
                    ),
                ]
            )
        )

        # 🟢 Handler-Funktion innerhalb von __init__
        def change_page_handler(e):
            selected_index = e.control.selected_index
            self.change_page(selected_index)

        self.drawer = ft.NavigationDrawer(
            on_change=change_page_handler,
            controls=[
                ft.Container(height=20),
                ft.Text("Aktuelle Runde", style="titleMedium", color="black", text_align=ft.TextAlign.CENTER),
                ft.Divider(),
                ft.NavigationDrawerDestination(
                    icon=ft.Icons.HOME,
                    label="Runde beendet!"
                ),
                ft.NavigationDrawerDestination(
                    icon=ft.Icons.PIE_CHART,
                    label="Gesamtübersicht"
                ),
                ft.NavigationDrawerDestination(
                    icon=ft.Icons.BAR_CHART,
                    label="Richtige Antworten pro Art"
                ),
                ft.NavigationDrawerDestination(
                    icon=ft.Icons.GRID_ON,
                    label="Confusion Matrix"
                ),
                ft.Text("Gesamt Analyse", style="titleMedium", color="black", text_align=ft.TextAlign.CENTER),
                ft.Divider(),
                ft.NavigationDrawerDestination(
                    icon=ft.Icons.INSIGHTS,
                    label="Top 3 Arten"
                ),
                ft.NavigationDrawerDestination(
                    icon=ft.Icons.SHOW_CHART,
                    label="Liniendiagramm"
                ),
                ft.NavigationDrawerDestination(
                    icon=ft.Icons.AREA_CHART,
                    label="Dynamisches Diagramm"
                ),
            ]
        )



        self.controls = [
            self.drawer,
            ft.Column(
                controls=[
                    top_bar,
                    ft.Row([
                        toggle_drawer_btn,
                        ft.Text("Navigation", size=15, color="white")
                    ], alignment=ft.MainAxisAlignment.START),
                    self.content_area
                ],
                expand=True,
            )
        ]

        # Starte mit Ansicht 0 (z.B. Runde beendet)
        self.change_page(0)

    # 🔁 Methode zur Änderung des Inhalts
    def change_page(self, index):
        self.content_area.controls.clear()

        if index == 0:
            self.content_area.controls.append(
                ft.Column(
                    controls=[
                        ft.Text("Runde beendet!", size=24, weight=ft.FontWeight.BOLD, color="white"),

                    ]
                )
            )

        elif index == 1:
            self.content_area.controls.append(
                ft.Column(
                    controls=[
                        ft.Text("Gesamtübersicht", size=24, weight=ft.FontWeight.BOLD, color="white"),
                        ft.Text(
                            f"Hier siehst du den Anteil an korrekten und falschen Antworten aus der aktuellen Runde ",
                            color="white"),

                    ]
                )
            )

        elif index == 2:
            self.content_area.controls.append(
                ft.Column(
                    controls=[
                        ft.Text("Richtige Antworten pro Art", size=24, weight=ft.FontWeight.BOLD, color="white"),

                    ]
                )
            )

        elif index == 3:
            self.content_area.controls.append(
                ft.Column(
                    controls=[
                        ft.Text("Confusion-Matrix", size=24, weight=ft.FontWeight.BOLD, color="white"),
                        ft.Text(
                            "Diese Matrix zeigt, welche Arten du häufig verwechselt hast. \n Die Zeilen stellen die korrekten Vogelarten dar, die Spalten deine Vorhersagen.Arten bei denen nur die diagonale Zelle grün ist, hast du besonders gut erkannt. Hat eine Art in der Zeile viele oder besonders rote Zellen, hast du sie häufig mit einer anderen Art verwechselt. Die von dir fälschlicherweise angenommene Art, kannst du in der Spalte (oben) ablesen.",
                            color="white"),
                        ft.Row(
                            controls=[
                                ft.ElevatedButton(
                                    text="Bild vergrößern",
                                    icon=ft.Icons.ZOOM_IN
                                )
                            ],
                            alignment=ft.MainAxisAlignment.CENTER
                        ),
                    ]
                )
            )

        elif index == 5:
            self.content_area.controls.append(
                ft.Column(
                    controls=[
                        ft.Text("Top 3 Arten", size=24, weight=ft.FontWeight.BOLD, color="white"),
                        ft.Text(
                            "Hier siehst du die Arten, die du bis jetzt am besten und am schlechtesten erkannt hast.",
                            color="white")
                    ]
                )
            )

        elif index == 6:
            search_field = ft.TextField(label="Art suchen (Deutsch, Englisch oder Wissenschaftlich)", width=400)
            chart_container = ft.Container(width=700, height=500)



            search_button = ft.ElevatedButton("Suchen")
            info_button = ft.IconButton(icon=ft.Icons.INFO_OUTLINE,
                                        tooltip="Welche Arten sind sinnvoll für das Liniendiagramm?")

            self.content_area.controls.append(
                ft.Column(
                    controls=[
                        ft.Row([search_field, search_button, info_button], alignment=ft.MainAxisAlignment.CENTER),
                        chart_container
                    ],
                    alignment=ft.MainAxisAlignment.CENTER
                )
            )

        elif index == 7:
            self.content_area.controls.append(
                ft.Column(
                    controls=[
                        ft.Text("Top 3 Arten", size=24, weight=ft.FontWeight.BOLD, color="white"),
                        ft.Text(
                            "Hier siehst du die Arten, die du bis jetzt am besten und am schlechtesten erkannt hast.",
                            color="white")
                    ]
                )
            )
        self.page.update()


class OverallSetting(ft.View):
    def __init__(self, page: ft.Page):
        super().__init__(route="/")
        self.page = page
        self.bgcolor = ft.Colors.BLUE_GREY_900

        self.dialog_reset_confirm = None  # wird später erstellt
        self.new_list_name = ft.TextField(
            label="Eigene Liste",
            hint_text="Name der Liste: Species A, Species B, ... ",
            border_color="black",
            text_style=ft.TextStyle(color="black"),
            label_style=ft.TextStyle(color="black"),
            expand=True
        )

        self.user_lists_column = ft.Column(spacing=10)


        add_list_button = ft.ElevatedButton(
            text="Liste erstellen",
            icon=ft.Icons.ADD,
            on_click=self.add_user_list
        )

        #Alertdialog
        action_style = ft.ButtonStyle(color=ft.Colors.BLUE)
        self.confirm_banner = ft.AlertDialog(
            modal=True,
            icon=ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=ft.Colors.AMBER, size=40),
            title=ft.Text("Hinweis"),
            content=ft.Text("Willst du wirklich alle gespeicherten Daten löschen?"),
            actions=[
                ft.TextButton(text="Ja, löschen", style=action_style, on_click=self.execute_pending_delete),
                ft.TextButton(text="Abbrechen", style=action_style, on_click=self.close_banner)
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )

        self.page.dialog = self.confirm_banner

        # "Back to Menu"-Button
        header_row = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.OutlinedButton(
                    text="Back to Menu",
                    icon=ft.Icons.MENU,
                    icon_color="white",
                    style=ft.ButtonStyle(
                        bgcolor={"": "green_100", ft.ControlState.DISABLED: "grey_100"},
                        color={"": "white", ft.ControlState.DISABLED: "grey"}
                    ),
                    on_click=lambda e: self.page.go("/")
                ),
            ],
        )

        # Überschrift
        text_row = ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            controls=[
                ft.Text(
                    "Grundeinstellungen",
                    style="headlineMedium",
                    color="white",
                    weight=ft.FontWeight.BOLD
                ),
            ],
        )

        #Einstellungen
        # 🔹 Inhalte für jedes Panel als ListTile
        cache_tile = ft.ListTile(
            title=ft.Text("Alle gespeicherten Bilder löschen"),
            subtitle=ft.Text("Press the icon to delete Image Cache"),
            trailing=ft.IconButton(icon=ft.Icons.DELETE,tooltip="Kompletten Cache löschen",on_click=lambda e: self.open_banner_delete("cache"))
        )

        results_tile = ft.ListTile(
            title=ft.Text("Alle bisher gespeicherten Ergebnisse (Sessions) löschen"),
            subtitle=ft.Text("Press the icon to delete Saved Results"),
            trailing=ft.IconButton(icon=ft.Icons.DELETE, tooltip="Alle Sessions löschen", on_click=lambda e: self.open_banner_delete("results"))
        )

        # 🔹 ExpansionPanelList mit drei Panels
        panel_list = ft.ExpansionPanelList(
            expand_icon_color=ft.Colors.WHITE,
            elevation=2,
            divider_color="white",
            controls=[
                ft.ExpansionPanel(
                    header=ft.Container(
                        alignment=ft.alignment.center,
                        padding=10,
                        content=ft.Text(
                            "Eigene Listen",
                            weight=ft.FontWeight.BOLD,
                            style="titleMedium",
                            color="black"
                        )
                    ),
                    content=ft.Container(
                        padding=10,
                        bgcolor=ft.Colors.GREEN_ACCENT_700,
                        content=ft.Column(
                            spacing=10,
                            controls=[
                                ft.ListTile(
                                    title=ft.Text(
                                        "Hier kannst du eigene Listen erstellen, die in den Settings mit angezeigt werden."),
                                    subtitle=ft.Text("Diese Funktion ist leider noch nicht vorhanden.")
                                ),
                                ft.Row([self.new_list_name, add_list_button]),
                                self.user_lists_column
                            ]
                        )
                    ),
                    bgcolor=ft.Colors.GREEN_ACCENT_700,
                    expanded=False
                ),
                ft.ExpansionPanel(
                    header=ft.Container(
                        alignment=ft.alignment.center,
                        padding=10,
                        content=ft.Text(
                            "Bilder Cache",
                            weight=ft.FontWeight.BOLD,
                            style="titleMedium",
                            color="black")),
                    content=cache_tile,
                    bgcolor=ft.Colors.GREEN_ACCENT_400,
                    expanded=False
                ),
                ft.ExpansionPanel(
                    header=ft.Container(
                        alignment=ft.alignment.center,
                        padding=10,
                        content=ft.Text(
                            "Gespeicherte Ergebnisse",
                            weight=ft.FontWeight.BOLD,
                            style="titleMedium",
                            color="black")),
                    content=results_tile,
                    bgcolor=ft.Colors.GREEN_ACCENT_200,
                    expanded=False
                )
            ]
        )

        #Contentbereich
        scrollable_content = ft.Column(
            controls=[
                ft.Text("Hier kannst du die gespeicherten Daten verwalten.", color="white"),
                panel_list
            ],
            spacing=20,
            expand=True,
            scroll=ft.ScrollMode.AUTO  # Vertikales Scrollen
        )




        # Inhalt setzen
        self.controls = [
            ft.Column(
                expand=True,
                controls=[
                    header_row,
                    text_row,
                    ft.Container(  # Scrollbarer Bereich für alles weitere
                        content=scrollable_content,
                        expand=True,
                        padding=20,
                        bgcolor=ft.Colors.BLUE_GREY_900
                    )
                ],
                spacing=20
            )
        ]

        self.page.dialog = self.dialog_reset_confirm


    def add_user_list(self, e):
        if not self.new_list_name.value.strip():
            return  # Leere Eingabe ignorieren

        list_component = UserList(self.new_list_name.value, self.delete_user_list)
        self.user_lists_column.controls.append(list_component)
        self.new_list_name.value = ""
        self.page.update()

    def delete_user_list(self, list_component):
        self.user_lists_column.controls.remove(list_component)
        self.page.update()



    def open_banner_delete(self, delete_type):
        print("[DEBUG] Öffne Dialog für:", delete_type)
        self._pending_delete = delete_type
        self.page.open(self.confirm_banner)
        self.page.update()  #

    def execute_pending_delete(self, e):
        if self._pending_delete == "cache":
            delete_entire_image_cache()
            print("[INFO] Bild-Cache gelöscht.")
        elif self._pending_delete == "results":
            delete_all_results()
            print("[INFO] Ergebnisse gelöscht.")

        self.confirm_banner.open = False
        self.page.update()

    def close_banner(self, e):
        self.confirm_banner.open = False
        self.page.update()


class UserList(ft.Column):
    def __init__(self, list_name, on_delete):
        super().__init__()
        self.list_name = list_name
        self.on_delete = on_delete

        self.display_label = ft.Text(value=list_name, size=16, color="black")
        self.edit_field = ft.TextField(value=list_name, expand=1)

        self.display_view = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                self.display_label,
                ft.Row(
                    controls=[
                        ft.IconButton(icon=ft.Icons.EDIT, icon_color="black", tooltip="Liste bearbeiten", on_click=self.edit_clicked),
                        ft.IconButton(icon=ft.Icons.DELETE, icon_color="black", tooltip="Liste löschen", on_click=self.delete_clicked),
                    ]
                )
            ]
        )

        self.edit_view = ft.Row(
            visible=False,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                self.edit_field,
                ft.IconButton(icon=ft.Icons.DONE, tooltip="Speichern", icon_color="black", on_click=self.save_clicked),
            ]
        )

        self.controls = [self.display_view, self.edit_view]

    def edit_clicked(self, e):
        self.edit_field.value = self.display_label.value
        self.display_view.visible = False
        self.edit_view.visible = True
        self.update()

    def save_clicked(self, e):
        self.display_label.value = self.edit_field.value
        self.list_name = self.edit_field.value
        self.display_view.visible = True
        self.edit_view.visible = False
        self.update()

    def delete_clicked(self, e):
        self.on_delete(self)








def main(page: ft.Page):
    page.title = "Sound Bird Quiz"
    page.padding = ft.padding.all(0)
    page.horizontal_alignment = "center"
    page.vertical_alignment = "top"
    page.bgcolor = ft.Colors.BLUE_GREY_900
    page.scroll = ft.ScrollMode.AUTO


    def route_change(route):
        page.views.clear()
        if page.route == "/":
            page.views.append(MainMenu(page))
        elif page.route == "/settings":
            page.views.append(Settings(page))
        elif page.route == "/game":
            page.views.append(Game(page))
        elif page.route == "/results":
            page.views.append(Results(page))
        elif page.route == "/overall_setting":
            page.views.append(OverallSetting(page))
        page.update()

    page.on_route_change = route_change
    page.go(page.route)

ft.app(target=main)

