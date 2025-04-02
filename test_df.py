import flet as ft
import os
import pandas as pd
import http.server
import socketserver
import threading
from functools import partial
import sqlite3
import json
import random
import vlc
import aiohttp
import shutil
import requests
from bs4 import BeautifulSoup
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt



# =========================
# Zentrale App-Logik -->Zustände/Daten etc. (einmalig geladen)
# =========================

class AppState:
    USER_LISTS_FILE = "user_lists.json"
    def __init__(self):
        self.theme_mode = ft.ThemeMode.LIGHT  # Start mit Light
        self.active_list_name = ""



    def toggle_theme(self, page: ft.Page):
        self.theme_mode = (
            ft.ThemeMode.DARK if self.theme_mode == ft.ThemeMode.LIGHT else ft.ThemeMode.LIGHT
        )
        page.theme_mode = self.theme_mode
        page.update()

    def start_local_http_server(self, directory="bird_cache", port=8000):
        handler = partial(http.server.SimpleHTTPRequestHandler, directory=directory)
        thread = threading.Thread(
            target=lambda: socketserver.TCPServer(("", port), handler).serve_forever(),
            daemon=True
        )
        thread.start()

    def init_database(self):
        db_path = os.path.join(os.getenv("LOCALAPPDATA"), "SoundBirdQuiz", "game_results.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                correct_species TEXT,
                selected_species TEXT,
                is_correct INTEGER,
                list_name TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                
            )
        """)
        try:
            cursor.execute("ALTER TABLE results ADD COLUMN session_id INTEGER")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        conn.close()

    def load_species_csv(self, path="Europ_Species_3.csv"):
        df = pd.read_csv(path, encoding="utf-8-sig")
        self.species_df = df
        self.latin_to_german = dict(zip(df["Wissenschaftlich"], df["Deutsch"]))

    def lookup_species(self, species_input):
        """
        Sucht in self.species_df nach einem passenden Eintrag in den Spalten
        'Deutsch', 'Wissenschaftlich', 'Englisch'. Gibt ein Dictionary zurück
        oder None, falls kein Treffer.
        """
        if self.species_df is None:
            print("[WARN] species_df wurde noch nicht geladen.")
            return None

        species_input_norm = species_input.strip().lower().replace("+", " ").encode("utf-8").decode("utf-8")

        print(f"[DEBUG] Suche nach normalisierter Art: {species_input_norm}")

        for _, row in self.species_df.iterrows():
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

    def convert_species_list(self, species_str):
        """
        Wandelt eine komma-getrennte Liste von Arten in ein Mapping um.
        Nutzt self.lookup_species() und self.species_df.
        """
        print(f"[DEBUG] Eingehender species_str: {species_str}")

        species_inputs = [s.strip() for s in species_str.split(",") if s.strip()]
        print("[DEBUG] Getrennte Einträge:", species_inputs)

        mapping_dict = {}

        for input_name in species_inputs:
            print(f"[DEBUG] Suche nach: {input_name}")
            mapping = self.lookup_species(input_name)  # nutzt die Instanzmethode

            if mapping:
                scientific = mapping["Wissenschaftlich"].strip().lower()
                display_name = mapping[mapping["display_language"]].strip()
                mapping_dict[scientific] = display_name
                print(f"[DEBUG] Treffer: {scientific} → {display_name}")
            else:
                print(f"[WARN] Art '{input_name}' nicht in der CSV gefunden.")

        return mapping_dict

    def load_user_lists(self):
        if os.path.exists(self.USER_LISTS_FILE):
            with open(self.USER_LISTS_FILE, "r", encoding="utf-8") as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return {}
        return {}

    def get_last_session_id(self):
        """Holt die höchste gespeicherte session_id aus der SQLite-Datenbank."""
        conn = sqlite3.connect("game_results.db")
        cursor = conn.cursor()

        cursor.execute("SELECT MAX(session_id) FROM results")  # Höchste session_id abrufen
        last_session_id = cursor.fetchone()[0]  # Wert extrahieren

        conn.close()
        return last_session_id if last_session_id is not None else 0  # Falls leer, starte mit 0



# ------------------------------
# Basis-Seitenklasse -->Objekte, die auf mehreren Seiten erstellt werden (Layout)
# ------------------------------
class BasePage:
    def __init__(self, page: ft.Page, app_state: "AppState"):
        self.page = page
        self.app_state = app_state
        self.page.session.set("current_view", self)

        self.loading_overlay = self.build_loading_overlay()
        self.page.overlay.append(self.loading_overlay)

    def update(self):
        self.page.update()

    def go_to(self, route: str):
        Router.go(self.page, route)

    def toggle_theme(self, e=None):
        self.app_state.toggle_theme(self.page)

    def build_appbar(self, title: str = "SoundBirdQuiz",  extra_actions: list[ft.Control] = None):
        extra_actions = extra_actions or []

        self.page.appbar = ft.AppBar(
            leading=ft.Icon(ft.Icons.MUSIC_NOTE),
            leading_width=40,
            title=ft.Text("SoundBirdQuiz"),
            center_title=False,
            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            actions=[
                *extra_actions,
                ft.IconButton(icon=ft.Icons.HELP_OUTLINE, tooltip="Informationen zur aktuellen Quiz-Seite", on_click=lambda e: self.show_info_alert(*self.get_info_alert_content())),
                ft.IconButton(
                    icon=ft.Icons.HOME_FILLED,
                    tooltip="Zurück zur Startseite",
                    on_click=lambda e: self.go_to("/")
                ),
                ft.IconButton(
                    icon=ft.Icons.SETTINGS,
                    tooltip="Allgemeine Info & übergeordnete Einstellungen",
                    on_click=lambda e: self.go_to("/overallsettings")
                ),
                ft.IconButton(
                    icon=ft.Icons.DARK_MODE if self.page.theme_mode == ft.ThemeMode.LIGHT else ft.Icons.LIGHT_MODE,
                    tooltip="Theme wechseln",
                    on_click=self.toggle_theme,
                ),
            ]
        )

    def get_info_alert_content(self) -> tuple[str, str]:
        return ("Hinweis", "Diese Seite hat noch keinen eigenen Info-Text.")

    def show_info_alert(self, title: str, message: str, confirm_text="OK", on_confirm=None):
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Text(message),
            actions=[
                ft.TextButton(
                    text=confirm_text,
                    on_click=lambda e: (
                        on_confirm(e) if on_confirm else None,
                        self.page.close(dialog),
                        self.update()
                    )
                )
            ],
            actions_alignment=ft.MainAxisAlignment.END
        )
        self.page.dialog = dialog
        self.page.open(dialog)
        self.update()

    def build_loading_overlay(self):
        return ft.Container(
            visible=False,
            bgcolor=ft.Colors.with_opacity(0.75, "black"),
            alignment=ft.alignment.center,
            expand=True,
            content=ft.Column(
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=20,
                controls=[
                    ft.ProgressRing(width=60, height=60, color="white"),
                    ft.Text("Wird geladen...", color="white", size=18)
                ]
            )
        )

    def show_loading(self, text="Wird geladen..."):
        self.loading_overlay.content.controls[1].value = text
        self.loading_overlay.visible = True
        self.page.update()

    def hide_loading(self):
        self.loading_overlay.visible = False
        self.page.update()


# =========================
# Router mit zentralem Theme-State
# =========================

class Router:
    routes = {}

    @staticmethod
    def init_routes(app_state: AppState):
        Router.routes = {
            "/": lambda page: MainMenu(page, app_state),
            "/settings": lambda page: Settings(page, app_state),
            "/game": lambda page: Game(page, app_state),
            "/results": lambda page: Results(page, app_state),
            "/overallsettings": lambda page: Overallsettings(page, app_state),

        }

    @staticmethod
    def go(page: ft.Page, route: str):
        # Rufe destroy auf, wenn vorhanden
        current_view = page.session.get("current_view")
        if current_view and hasattr(current_view, "on_destroy"):
            current_view.on_destroy()

        # Neue View laden
        handler = Router.routes.get(route, lambda p: MainMenu(p, app_state))
        handler(page)


# =========================
# Seiten als Klassen
# =========================

class MainMenu(BasePage):
    def __init__(self, page, app_state):
        super().__init__(page, app_state)

        self.build_appbar()
        self.page.padding = 0
        self.page.controls.clear()

        self.build_layout()

        self.update()

    def build_layout(self):
        # Bilddateien
        image_files = [
            "vogel3.jpg", "vogel4.jpg", "vogel9.jpg",
            "vogel6.jpg", "vogel5.jpg", "puffin_iceland.jpg",
            "vogel7.jpg", "puffin.jpg", "vogel8.jpg"
        ]

        image_grid = ft.GridView(
            expand=True,
            max_extent=250,
            spacing=0,
            run_spacing=0,
            controls=[
                ft.Image(src=img, fit=ft.ImageFit.COVER) for img in image_files
            ]
        )

        overlay_text = ft.Container(
            alignment=ft.alignment.center,
            content=ft.Text(
                "SOUND\nBIRD\nQUIZ",
                size=150,
                color=ft.Colors.with_opacity(0.5, 'white'),
                text_align=ft.TextAlign.CENTER,
                weight=ft.FontWeight.BOLD,
            )
        )

        right_container = ft.Container(
            expand=True,
            content=ft.Stack(
                expand=True,
                controls=[image_grid, overlay_text]
            )
        )

        left_container = ft.Container(
            width=600,
            padding=20,
            content=ft.Column(
                spacing=30,
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Text(
                        "WILLKOMMEN",
                        style="headlineLarge",
                        weight=ft.FontWeight.BOLD
                    ),
                    ft.Text(
                        "Teste & trainiere deine Vogelstimmenkenntnisse!",
                        style="titleMedium"
                    ),
                    ft.ElevatedButton(
                        text="Quiz starten mit neuen Einstellungen",
                        icon=ft.Icons.SETTINGS,
                        width=400,
                        height=40,
                        on_click=lambda e: Router.go(self.page, "/settings")
                    ),
                    ft.ElevatedButton(
                        text="Quiz starten mit vorherigen Einstellungen",
                        icon="rotate_left",
                        width=400,
                        height=40,
                        on_click=lambda e: Router.go(self.page, "/game")
                    ),
                    ft.ElevatedButton(
                        text="Quiz starten mit 10 zufälligen Vogelarten",
                        icon="shuffle",
                        width=400,
                        height=40,
                        on_click=self.shuffle_and_start_quiz
                    ),
                ]
            )
        )

        main_row = ft.Row(
            expand=True,
            controls=[left_container, right_container]
        )

        self.page.add(main_row)

    def get_info_alert_content(self):
        return (
            "SoundBirdQuiz Menü",
            "Du hast drei Optionen."
        )

    def shuffle_and_start_quiz(self, e):
        print("[DEBUG] Quiz starten: Wähle 10 zufällige Arten")

        df = self.app_state.species_df
        if df is None:
            print("[ERROR] species_df wurde nicht geladen.")
            return

        num_species = min(10, len(df))
        random_species = df.sample(n=num_species)["Deutsch"].tolist()

        species_list_str = ", ".join(random_species)
        print("[DEBUG] Zufällige Arten:", species_list_str)

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

        self.go_to("/game")  # nutzt BasePage-Router


class Settings(BasePage):
    def __init__(self, page, app_state):
        super().__init__(page, app_state)

        self.build_appbar()
        self.page.padding = 20

        self.page.controls.clear()

        self.build_layout()

        self.update()

    def build_layout (self):
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

        # Row für verschiedenen Soundtyp
        sound_row = ft.Row(
            spacing=20,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                self.sound_radio_group,
                self.other_dropdown
            ]
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

        # Row Lifestage/Geschlecht Dropdown
        lifestage_row = ft.Row(
            spacing=20,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                self.selected_sex,
                self.selected_lifestage
            ]
        )

        # Switches als Instanzvariablen:
        self.images_switch = ft.Switch(label="Bilder anzeigen", value=False)
        self.spectrogram_switch = ft.Switch(label="Spektrogramm anzeigen", value=True)

        #Menu button erstellen
        menu_button = self.build_species_menu()



        settings_container = ft.Container(
            width=800,
            height=400,  # Feste Höhe für Scrollbarkeit
            padding=ft.Padding(30, 30, 30, 30),
            bgcolor=ft.Colors.OUTLINE_VARIANT,  # Helles Grau für Formularbox
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
                    menu_button,
                    # Divider
                    ft.Container(
                        alignment=ft.alignment.center,
                        bgcolor=ft.Colors.GREEN_400,
                        border_radius=5,
                        height=5
                    ),
                    ft.Text(
                        "Soundtyp spezifizieren",
                        style="titleSmall",
                        weight=ft.FontWeight.BOLD
                    ),
                    # Zeile mit Radiogruppe + Dropdown und Zeile für Lifestage/Geschlecht
                    sound_row,
                    lifestage_row,

                    # Divider
                    ft.Container(
                        alignment=ft.alignment.center,
                        bgcolor=ft.Colors.GREEN_400,
                        border_radius=5,
                        height=5
                    ),
                    # Zwei Switches
                    self.spectrogram_switch,
                    self.images_switch,


                ]
            )
        )

        self.page.add(
            ft.Text("Hier sind die Einstellungen"),
            settings_container,
            ft.ElevatedButton("Einstellungen speichern und Quiz starten", on_click=self.save_and_start)
        )

    def get_info_alert_content(self):
        return (
            "Neue Spieleinstellungen festlegen",
            "Hier kommt noch eine Erklärung"
        )

    def build_species_menu(self):
        user_lists = self.app_state.load_user_lists()

        # Für vorgefertigte Listen: Nur key übergeben
        def menu_item_fixed(label):
            return ft.MenuItemButton(
                content=ft.Text(label),
                on_click=lambda _: self.update_species_list(label),
                style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
            )

        # Für eigene Listen aus JSON
        def menu_item_user(list_name, species_str):
            return ft.MenuItemButton(
                content=ft.Text(list_name),
                tooltip=species_str,
                on_click=lambda _: self.update_species_list(list_name, species_str),
                style=ft.ButtonStyle(bgcolor={ft.ControlState.HOVERED: ft.Colors.GREEN}),
            )

        eigene_listen_submenu = ft.SubmenuButton(
            content=ft.Text("Eigene Listen"),
            leading=ft.Icon(ft.Icons.EDIT_DOCUMENT),
            controls=[menu_item_user(name, species_str) for name, species_str in user_lists.items()]
        )

        return ft.Row(
            alignment=ft.MainAxisAlignment.START,
            controls=[
                ft.SubmenuButton(
                    content=ft.Text("Liste auswählen"),
                    leading=ft.Icon(ft.Icons.WYSIWYG),
                    controls=[
                        ft.SubmenuButton(
                            content=ft.Text("Habitate"),
                            leading=ft.Icon(ft.Icons.FOREST),
                            controls=[menu_item_fixed(name) for name in [
                                "Alpine Zone", "Auenwald", "Feuchtgebiet Binnenland",
                                "Küste (typische Arten)", "Laubwald", "Nadelwald",
                                "Offenland/Agrarlandschaft", "Siedlung"
                            ]]
                        ),
                        ft.SubmenuButton(
                            content=ft.Text("Artengruppe"),
                            leading=ft.Icon(ft.Icons.GROUPS),
                            controls=[menu_item_fixed(name) for name in [
                                "Ammern", "Drosseln", "Enten", "Eulen", "Greifvögel", "Laubsänger",
                                "Meisen", "Mitteleuropäische Grasmücken", "Möwen", "Pieper",
                                "Rohrsänger", "Schnäpper", "Singvogelzug", "Spechte", "Watvögel"
                            ]]
                        ),
                        ft.SubmenuButton(
                            content=ft.Text("Leicht verwechselbar"),
                            leading=ft.Icon(ft.Icons.COMPARE_ARROWS),
                            controls=[menu_item_fixed(name) for name in [
                                "Amsel-Misteldrossel (Song)", "Bergfink-Buchfink (Other: Flightcall)",
                                "Blaumerle-Steinrötel (Song)", "Eisvogel-Heckenbraunelle (Call)",
                                "Fitis-Gartenrotschwanz (Call)", "Zippammer-Zaunammer (Call)"
                            ]]
                        ),
                        eigene_listen_submenu
                    ]
                )
            ]
        )

    def update_species_list(self, key, species_str=None):
        self.app_state.active_list_name = key
        # Wenn species_str vorhanden ist (z.B. bei eigenen Listen), nutze den!
        if species_str:
            self.species_text_field.value = species_str
        else:
            # Für hinterlegte Listen:
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

            self.species_text_field.value = species_lists.get(key, "")

            # Extra Optionen setzen
            if key == "Bergfink-Buchfink (Other: Flightcall)":
                self.sound_radio_group.value = "Other"
                self.other_dropdown.value = "Flight call"
                self.other_dropdown.visible = True
            elif key in ["Eisvogel-Heckenbraunelle (Call)", "Zippammer-Zaunammer (Call)",
                         "Fitis-Gartenrotschwanz (Call)"]:
                self.sound_radio_group.value = "Call"
            elif key in ["Amsel-Misteldrossel (Song)", "Blaumerle-Steinrötel (Song)"]:
                self.sound_radio_group.value = "Song"

        self.update()

    def sound_type_changed(self, e):
        if self.sound_radio_group.value == "Other":
            self.other_dropdown.visible = True
        else:
            self.other_dropdown.visible = False
        self.page.update()

    def save_settings(self, e=None):
        # Soundtyp bestimmen
        sound_type_value = self.sound_radio_group.value
        if sound_type_value == "Other":
            sound_type_value = self.other_dropdown.value
            print("[DEBUG] sound_type überschrieben mit:", sound_type_value)
        elif sound_type_value == "All":
            sound_type_value = ""

        # Geschlecht bestimmen
        sex_value = self.selected_sex.value
        if sex_value == "All sex":
            sex_value = ""

        # Lebensstadium bestimmen
        lifestage_value = self.selected_lifestage.value
        if lifestage_value == "All lifestage":
            lifestage_value = ""

        # JSON-Datenstruktur
        settings_data = {
            "species_list": self.species_text_field.value,
            "sound_type": sound_type_value,
            "show_images": self.images_switch.value,
            "show_spectrogram": self.spectrogram_switch.value,
            "Lifestage": lifestage_value,
            "Geschlecht": sex_value,
        }

        # In Datei speichern
        with open("settings.json", "w", encoding="utf-8") as f:
            json.dump(settings_data, f, ensure_ascii=False, indent=4)

        # Feedback an den User
        self.page.snack_bar = ft.SnackBar(ft.Text("Einstellungen gespeichert!"))
        self.page.snack_bar.open = True
        self.page.update()

    def save_and_start(self, e):
        self.save_settings()
        Router.go(self.page, "/game")


class Game(BasePage):
    def __init__(self, page, app_state):
        super().__init__(page, app_state)

        self.answer_submitted = False
        self.selected_species = []
        self.current_audio = None
        self.correct_species = None
        self.player = None
        self.api_cache = {}
        self.round = 1
        self.session_id = self.app_state.get_last_session_id() + 1
        self.page.session.set("session_id", self.session_id)

        self.wikipedia_api = "https://en.wikipedia.org/w/api.php"
        self.headers = {
            "User-Agent": "BirdQuizBot/1.0 (Python Script for Bird Sound Quiz)"
        }

        end_btn = ft.ElevatedButton("Stop Game & Show Results",
                                       icon=ft.Icons.STOP_CIRCLE_OUTLINED,
                                       color=ft.Colors.WHITE,
                                       tooltip="Spielrunde beenden und Ergebnisse anzeigen",
                                       icon_color=ft.Colors.WHITE,
                                       bgcolor=ft.Colors.GREEN_700,
                                       on_click=lambda e: Router.go(self.page, "/results")
                                       )

        self.build_appbar(extra_actions=[end_btn])
        self.page.padding = 20
        self.page.controls.clear()

        self.build_layout()
        self.load_settings()
        self.update_species_buttons()
        if self.show_images:
            self.cache_bird_images(self.selected_species)
        self.start_new_round()
        self.update()

    def build_layout(self):
        # Sonogram & Bild
        self.media_image = ft.Image(
            src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADElEQVR42mP8/5+hHgAHggJ/PFC2GAAAAABJRU5ErkJggg==",
            width=480,
            height=160,
            fit=ft.ImageFit.CONTAIN,
            border_radius=5
        )
        self.copyright_info = ft.IconButton(icon=ft.Icons.COPYRIGHT_OUTLINED, icon_size=18, icon_color="grey")
        # Steuerelemente
        self.round_label = ft.Text(f"Runde {self.round}", style="headlineSmall")
        self.feedback_text = ft.Text("")
        self.species_buttons_container = ft.ListView(height=90, spacing=10, controls=[])

        self.audio_button = ft.OutlinedButton(
            text="Repeat Audio",
            icon=ft.Icons.VOLUME_UP,
            on_click=self.play_audio
        )
        self.next_button = ft.ElevatedButton("Next", icon=ft.Icons.ARROW_FORWARD, width=200, on_click=self.next_round)
        self.skip_button = ft.ElevatedButton("Skip", icon=ft.Icons.SKIP_NEXT, width=200, on_click=self.skip_round)

        self.page_layout = ft.Stack(
            expand=True,
            controls=[
                ft.Column(
                    spacing=10,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        self.round_label,
                        self.audio_button,
                        self.media_image,
                        self.copyright_info,
                        self.species_buttons_container,
                        self.feedback_text,
                        ft.Row(
                            alignment=ft.MainAxisAlignment.CENTER,
                            spacing=20,
                            controls=[self.skip_button, self.next_button]
                        )
                    ]
                ),
            ]
        )

        self.page.add(
            ft.Text("Welche Art kannst du hören?"),
            self.page_layout,
        )

    def get_info_alert_content(self):
        return (
            "Quiz spielen",
            "Es werden automatisch und zufällig Audios deine ausgewählten Arten abgespielt. Klicke auf den passenden Vogelnamen. \n"
            "Teilweise sind die Audios auf Xenocanto sehr kurz, dann kannst du mit REPEAT die Aufname wiederholen. Falls die Qualität zu schlecht ist, kannst du die Aufname mit SKIP überspringen.\n"
            "Sobald du eine Art ausgewählt hast, kommt eine Auflösung. Mit NEXT kannst du die nächste Runde starten."
        )

    def load_settings(self):
        if os.path.exists("settings.json"):
            with open("settings.json", "r", encoding="utf-8") as f:
                settings = json.load(f)
            species_str = settings.get("species_list", "")
            self.species_mapping = self.app_state.convert_species_list(species_str)
            self.selected_species = list(self.species_mapping.keys())
            self.sound_type = settings.get("sound_type", "")
            self.show_images = settings.get("show_images", False)
            self.show_spectrogram = settings.get("show_spectrogram", False)
            self.selected_lifestage = settings.get("Lifestage", "")
            self.selected_sex = settings.get("Geschlecht", "")
        else:
            self.species_mapping = {}
            self.selected_species = []
            self.sound_type = ""
            self.show_images = False
            self.show_spectrogram = False
            self.selected_lifestage = ""
            self.selected_sex = ""

    def update_species_buttons(self):
        self.species_buttons_container.controls.clear()
        buttons = []
        for sci in self.selected_species:
            display_name = self.species_mapping.get(sci, sci)
            btn = ft.OutlinedButton(
                text=display_name,
                on_click=lambda e, s=sci: self.check_answer(s)
            )
            buttons.append(btn)

        # In Zeilen gruppieren
        row = []
        rows = []
        for i, btn in enumerate(buttons):
            row.append(btn)
            if (i + 1) % 8 == 0:
                rows.append(ft.Row(controls=row, alignment=ft.MainAxisAlignment.CENTER))
                row = []
        if row:
            rows.append(ft.Row(controls=row, alignment=ft.MainAxisAlignment.CENTER))
        self.species_buttons_container.controls = rows

    def start_new_round(self):
        if not self.selected_species:
            self.feedback_text.value = "Keine Arten ausgewählt!"
            self.feedback_text.color = "red"
            self.page.update()
            return

        def update_ui(recording):
            if recording:
                self.current_audio = recording["audio_url"]
                self.correct_species = recording["correct_species"]
                if self.show_spectrogram and recording.get("sonogram_url"):
                    self.fetch_and_display_sonogram(recording["sonogram_url"], self.media_image)
                self.play_audio()
                self.copyright_info.tooltip = recording.get("copyright_info", "")
            else:
                self.feedback_text.value = "Kein Audio gefunden!"
                self.feedback_text.color = "red"

            self.hide_loading()
            self.page.update()

        # 👇 Zeige nur den Ladebildschirm, wenn kein Prefetch da ist
        if not hasattr(self, "prefetched_recording") or self.prefetched_recording is None:
            self.show_loading("Neue Recordings werden geladen...")

        # Wenn ein Recording vorab geladen wurde, benutze das direkt:
        if hasattr(self, "prefetched_recording") and self.prefetched_recording:
            rec = self.prefetched_recording
            self.prefetched_recording = None  # Direkt verbrauchen
            update_ui(rec)
            self.prefetch_next_round()  # nächsten schon vorbereiten
        else:
            # Wenn keins da: Async laden und danach UI aktualisieren
            self.page.run_task(self.load_recording_async).add_done_callback(
                lambda fut: (
                    update_ui(fut.result()),
                    self.prefetch_next_round()
                )
            )

    async def load_recording_async(self):
        scientific = random.choice(self.selected_species)
        return await self.async_get_random_recording(scientific)

    async def async_get_random_recording(self, scientific):
        key = (scientific, self.sound_type, self.selected_sex, self.selected_lifestage)
        if key in self.api_cache:
            data = self.api_cache[key]
        else:
            query = f"{scientific}"
            if self.sound_type:
                query += f'+type:"{self.sound_type}"'
            if self.selected_sex:
                query += f'+sex:"{self.selected_sex}"'
            if self.selected_lifestage:
                query += f'+stage:"{self.selected_lifestage}"'

            url = f"https://www.xeno-canto.org/api/2/recordings?query={query}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    data = await response.json()
                    self.api_cache[key] = data
        recs = data.get("recordings", [])
        if not recs:
            return None
        rec = random.choice(recs)
        return {
            "audio_url": rec.get("file"),
            "sonogram_url": "https:" + rec.get("sono", {}).get("med", "") if rec.get("sono", {}).get("med") else None,
            "correct_species": scientific,
            "copyright_info": f"Recorded by {rec.get('rec', '')} | Licensed under: https:{rec.get('lic', '')}"
        }

    def prefetch_next_round(self):
        async def fetch():
            scientific = random.choice(self.selected_species)
            rec = await self.async_get_random_recording(scientific)
            self.prefetched_recording = rec

        self.page.run_task(fetch)

    def play_audio(self, e=None):
        if self.current_audio:
            if self.player:
                self.player.stop()
            self.player = vlc.MediaPlayer(self.current_audio)
            threading.Thread(target=self.player.play, daemon=True).start()

    def check_answer(self, selected):
        if self.player:
            self.player.stop()
        is_correct = selected.strip().lower() == self.correct_species.strip().lower()
        for row in self.species_buttons_container.controls:
            for btn in row.controls:
                if btn.text == self.species_mapping.get(selected, selected):
                    if btn.style is None:
                        btn.style = ft.ButtonStyle()
                    btn.style.bgcolor = ft.Colors.GREEN if is_correct else ft.Colors.RED
                btn.disabled = True
                btn.update()
        self.skip_button.disabled = True
        self.next_button.disabled = False
        self.answer_submitted = True
        self.save_result(self.correct_species, selected, is_correct)

        if is_correct:
            self.feedback_text.value = "Richtig!"
            self.feedback_text.color = "green"
        else:
            self.feedback_text.value = f"Falsch! Es war {self.species_mapping.get(self.correct_species)}"
            self.feedback_text.color = "red"

        if self.show_images:
            url = self.load_bird_image(self.correct_species)
            self.media_image.src = url
            metadata = self.load_image_metadata(self.correct_species)
            self.copyright_info.tooltip = f"Picture by: {metadata.get('author', '')} | {metadata.get('license', '')}"
        self.page.update()

    def save_result(self, correct, selected, is_correct):
        list_name = self.app_state.active_list_name if hasattr(self.app_state, "active_list_name") else ""
        conn = sqlite3.connect("game_results.db")
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO results (session_id, correct_species, selected_species, is_correct, list_name, timestamp)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (self.session_id, correct, selected, is_correct, list_name))
        conn.commit()
        conn.close()

    def next_round(self, e):
        if self.player:
            self.player.stop()
        self.feedback_text.value = ""
        self.round += 1
        self.round_label.value = f"Runde {self.round}"
        self.skip_button.disabled = False
        self.next_button.disabled = True
        for row in self.species_buttons_container.controls:
            for btn in row.controls:
                btn.disabled = False
                btn.style = None  # komplett zurücksetzen
                btn.update()
        self.page.update()
        self.start_new_round()

    def skip_round(self, e):
        if self.player:
            self.player.stop()
        correct_display = self.species_mapping.get(self.correct_species, self.correct_species)
        self.feedback_text.value = f"Übersprungen! Es war: {correct_display}."
        self.feedback_text.color = "yellow"
        self.next_button.disabled = False
        for row in self.species_buttons_container.controls:
            for btn in row.controls:
                btn.disabled = True
        self.page.update()

    def fetch_and_display_sonogram(self, url, image_control: ft.Image):
        try:
            image_control.src = url
            image_control.update()
        except Exception as e:
            print(f"[ERROR] Sonogram konnte nicht geladen werden: {e}")

    def cache_bird_images(self, species_list):
        os.makedirs("bird_cache", exist_ok=True)
        for species in species_list:
            safe_name = species.replace("+", "_").replace(" ", "_").lower()
            cache_dir = os.path.join("bird_cache", safe_name)
            metadata_file = os.path.join(cache_dir, "metadata.json")
            image_file = os.path.join(cache_dir, "image_0.jpg")

            if os.path.exists(metadata_file):
                print(f"[INFO] Bereits im Cache: {species}")
                continue

            if os.path.exists(cache_dir):
                shutil.rmtree(cache_dir)
            os.makedirs(cache_dir, exist_ok=True)

            # Artikel finden
            search_params = {
                "action": "query",
                "list": "search",
                "srsearch": f"{species} +bird -chimp -ape -Pan",
                "format": "json"
            }

            try:
                resp = requests.get(self.wikipedia_api, headers=self.headers, params=search_params)
                data = resp.json()
                results = data.get("query", {}).get("search", [])
                if not results:
                    continue
                page_title = results[0]["title"]
            except Exception as e:
                print(f"[ERROR] Suche für {species}: {e}")
                continue

            # Bild abrufen
            image_params = {
                "action": "query",
                "prop": "pageimages",
                "titles": page_title,
                "piprop": "thumbnail|name",
                "pithumbsize": 800,
                "format": "json"
            }

            try:
                img_data = requests.get(self.wikipedia_api, headers=self.headers, params=image_params).json()
                pages = img_data.get("query", {}).get("pages", {})
                thumb = next(iter(pages.values()), {}).get("thumbnail", {}).get("source", None)
                page_img_name = next(iter(pages.values()), {}).get("pageimage", None)
                if not thumb or not page_img_name:
                    continue
            except Exception as e:
                print(f"[ERROR] Bildfehler {species}: {e}")
                continue

            try:
                image = requests.get(thumb)
                with open(image_file, "wb") as f:
                    f.write(image.content)
            except Exception as e:
                print(f"[ERROR] Download für {species} fehlgeschlagen: {e}")
                continue

            # Lizenzinfo abrufen
            file_name = "File:" + page_img_name
            license_params = {
                "action": "query",
                "titles": file_name,
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
                "format": "json"
            }

            try:
                license_resp = requests.get(self.wikipedia_api, headers=self.headers, params=license_params)
                license_data = license_resp.json()
                pages = license_data.get("query", {}).get("pages", {})
                image_info = next(iter(pages.values()), {}).get("imageinfo", [{}])[0]
                author_html = image_info.get("extmetadata", {}).get("Artist", {}).get("value", "")
                license = image_info.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
                photo_author = BeautifulSoup(author_html, "html.parser").text
            except Exception as e:
                photo_author = "Unbekannt"
                license = "Unbekannt"

            metadata = [{
                "filename": os.path.basename(image_file),
                "license": license,
                "author": photo_author
            }]

            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)

    def load_bird_image(self, species: str) -> str:
        safe_name = species.replace("+", "_").replace(" ", "_").lower()
        return f"http://localhost:8000/{safe_name}/image_0.jpg"

    def load_image_metadata(self, species: str) -> dict:
        safe_name = species.replace("+", "_").replace(" ", "_").lower()
        metadata_file = os.path.join("bird_cache", safe_name, "metadata.json")
        if os.path.exists(metadata_file):
            try:
                with open(metadata_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data[0] if data else {}
            except Exception as e:
                print(f"[ERROR] Metadata-Fehler bei {species}: {e}")
        return {"license": "Unbekannt", "author": "Unbekannt"}

    def on_destroy(self):
        if self.player:
            print("[INFO] Audio gestoppt beim Verlassen der Spielseite.")
            self.player.stop()
            self.player = None


class Results(BasePage):
    def __init__(self, page, app_state):
        super().__init__(page, app_state)

        self.selected_mode = 0  # 0 = Aktuelle Runde, 1 = Gesamtergebnisse
        self.selected_nav_index = 0
        self.session_id = self.app_state.get_last_session_id()
        self.session_accuracy_data = self.overall_accuracy_for_session()
        self.plot_confusion_matrix()

        self.nav_items = {
            0: [  # Aktuell
                ("Gesamtübersicht", ft.Icons.PIE_CHART),
                ("Antworten pro Art", ft.Icons.BAR_CHART),
                ("Confusion Matrix", ft.Icons.GRID_ON),
            ],
            1: [  # Gesamt
                ("Top 3 Arten", ft.Icons.INSIGHTS),
                ("Liniendiagramm", ft.Icons.SHOW_CHART),
                ("Diagramm", ft.Icons.AREA_CHART),
            ]
        }

        self.segmented = ft.CupertinoSlidingSegmentedButton(
            selected_index=0,
            thumb_color=ft.Colors.GREEN,
            padding=ft.padding.symmetric(0, 10),
            on_change=self.on_segment_change,
            controls=[ft.Text("Aktuelle Runde"), ft.Text("Gesamtergebnisse")]
        )

        self.rail = ft.NavigationRail(
            selected_index=0,
            label_type=ft.NavigationRailLabelType.ALL,
            on_change=self.on_rail_change
        )

        self.content_area = ft.Column(expand=True)

        self.build_appbar(extra_actions=[self.segmented])
        self.page.padding = 20
        self.build_layout()
        self.update_rail_items()
        self.change_page(0)

    def build_layout(self):
        self.page.controls.clear()
        layout = ft.Row(
            expand=True,
            controls=[
                self.rail,
                ft.VerticalDivider(width=1),
                ft.Container(
                    expand=True,
                    padding=20,
                    content=self.content_area
                )
            ]
        )
        self.page.add(layout)

    def update_rail_items(self):
        self.rail.destinations = [
            ft.NavigationRailDestination(icon=ft.Icon(icon), label=label)
            for label, icon in self.nav_items[self.selected_mode]
        ]
        self.rail.selected_index = 0

    def on_segment_change(self, e):
        self.selected_mode = e.control.selected_index
        self.selected_nav_index = 0
        self.update_rail_items()
        self.change_page(0)

    def on_rail_change(self, e):
        self.selected_nav_index = e.control.selected_index
        self.change_page(self.selected_nav_index)

    def change_page(self, index):
        self.content_area.controls.clear()

        if self.selected_mode == 0:
            # Aktuelle Runde
            if index == 0:
                self.content_area.controls.append(self.build_overview_chart())
            elif index == 1:
                self.content_area.controls.append(self.build_each_species_stats())
            elif index == 2:
                self.content_area.controls.append(self.build_confusion_matrix())
        else:
            # Gesamtergebnisse
            if index == 0:
                self.content_area.controls.append(self.build_top3())
            elif index == 1:
                self.content_area.controls.append(self.build_line_chart())
            elif index == 2:
                self.content_area.controls.append(self.build_dynamic_chart())

        self.page.update()

    def get_info_alert_content(self):
        return (
            "Ergebnisse anzeigen",
            "Hier findest du eine Übersicht der zuletzt gespielten Runde. Nutze die Navigation links, um einzelne Analysen anzuzeigen. Es gibt zusätzlich die Gesamtanalyse"
        )

    def build_overview_chart(self):
        chart_with_title, summary_text = self.pie_chart()
        feedback_text, gif_path = self.get_feedback_text_and_gif(percent_correct=None)  # Parameter ist optional

        return ft.Column([
            ft.Text(feedback_text, style=ft.TextStyle(size=18, weight=ft.FontWeight.BOLD)),
            summary_text,
            ft.Text("Noch nicht zufrieden? Dann spiele doch einfach nochmal mit den gleichen Einstellungen."),
            ft.ElevatedButton(
                "Repeat Game",
                icon=ft.Icons.REPLAY,
                color=ft.Colors.WHITE,
                tooltip="Spiel mit gleichen Einstellungen wiederholen",
                icon_color=ft.Colors.WHITE,
                bgcolor=ft.Colors.GREEN_700,
                on_click=lambda e: Router.go(self.page, "/game")
            ),
            ft.Row(
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.START,
                spacing=30,
                controls=[
                    chart_with_title,
                    ft.Image(src=gif_path, width=250, height=250, fit=ft.ImageFit.CONTAIN)
                ]
            ),
        ])

    def build_each_species_stats(self):
        return ft.Column([
            ft.Text("Richtige Antworten pro Art", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("Hier kannst du sehen, wie gut du einzelne Arten erkannt hast.\n" 
                    "Wenn du mit dem Curser über die Balken fährst, kannst du sehen, wie viele Audios jeweils abgespielt wurden sind.\n"
                    "Bei zu vielen Arten, kannst du die Grafik nach links & rechts hin verschieben, um alle Balken anzuzeigen."),
            ft.Text(""),
            self.species_bar()
        ])

    def build_confusion_matrix(self):
        return ft.Row([
            ft.Column([
                ft.Text("Confusion-Matrix", size=24, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Diese Matrix zeigt, welche Arten du häufig verwechselt hast.\n"
                    "Die Zeilen stellen die korrekten Vogelarten dar, die Spalten deine Vorhersagen.\n"
                    "Arten bei denen nur die diagonale Zelle grün ist, hast du besonders gut erkannt.\n"
                    "Hat eine Art in der Zeile viele oder besonders rote Zellen, hast du sie häufig \nmit einer anderen Art verwechselt."),
                ft.ElevatedButton("Bild vergrößern", icon=ft.Icons.ZOOM_IN)]
            ),
            ft.Image(src="matrix_plot.png", width=500, height=500)],
            alignment=ft.MainAxisAlignment.CENTER
        )



    def build_top3(self):
        return ft.Column([
            ft.Text("Top 3 Arten", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("Hier siehst du die Arten, die du bisher am besten oder schlechtesten erkannt hast.")
        ])

    def build_line_chart(self):
        return ft.Column([
            ft.Text("Liniendiagramm", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("Hier könntest du langfristige Trends für bestimmte Arten analysieren.")
        ])

    def build_dynamic_chart(self):
        search_field = ft.TextField(label="Art suchen (Deutsch, Englisch oder Wissenschaftlich)", width=400)
        chart_container = ft.Container(width=700, height=500)

        search_button = ft.ElevatedButton("Suchen")
        info_button = ft.IconButton(icon=ft.Icons.INFO_OUTLINE,
                                    tooltip="Welche Arten sind sinnvoll für das Liniendiagramm?")

        return ft.Column([
            ft.Text("Diagramm für einzelne Arten", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("Hier könntest du langfristige Trends für bestimmte Arten analysieren."),
            ft.Row([search_field, search_button, info_button], alignment=ft.MainAxisAlignment.CENTER),
            chart_container
        ])

    def pie_chart(self):
        stats = self.session_accuracy_data

        correct_percent = stats["correct_percent"]
        incorrect_percent = stats["incorrect_percent"]
        correct_count = stats["correct"]
        incorrect_count = stats["incorrect"]
        total_count = stats["total"]

        # Hover Effekt
        normal_radius = 50
        hover_radius = 60
        normal_title_style = ft.TextStyle(size=16, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD)
        hover_title_style = ft.TextStyle(
            size=22,
            color=ft.Colors.WHITE,
            weight=ft.FontWeight.BOLD,
            shadow=ft.BoxShadow(blur_radius=2, color=ft.Colors.BLACK54),
        )

        def on_chart_event(e: ft.PieChartEvent):
            for idx, section in enumerate(chart.sections):
                if idx == e.section_index:
                    section.radius = hover_radius
                    section.title_style = hover_title_style
                else:
                    section.radius = normal_radius
                    section.title_style = normal_title_style
            chart.update()


        chart = ft.PieChart(
            sections=[
                ft.PieChartSection(
                    correct_percent,
                    title=f"{correct_percent}%",
                    title_style=normal_title_style,
                    color=ft.Colors.GREEN,
                    radius=normal_radius,
                ),
                ft.PieChartSection(
                    incorrect_percent,
                    title=f"{incorrect_percent}%",
                    title_style=normal_title_style,
                    color=ft.Colors.RED,
                    radius=normal_radius,
                ),
            ],
            sections_space=0,
            center_space_radius=40,
            on_chart_event=on_chart_event,
            width=200,
            height=200,
        )

        chart_with_title = ft.Column(
            spacing=5,
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Text("Gesamt Korrekt / Falsch (in %)", size=18, weight=ft.FontWeight.BOLD,
                        text_align=ft.TextAlign.CENTER),
                chart
            ]
        )

        # Beschreibungstext
        summary_text = ft.Text(
            f"Du hast {correct_count} von {total_count} Audios korrekt erkannt.\n"
            f"{incorrect_count} Audios waren falsch zugeordnet.",
            text_align=ft.TextAlign.START
        )

        # Ausgabe
        return chart_with_title, summary_text




    def get_feedback_text_and_gif(self, percent_correct):
        correct_percent = self.session_accuracy_data["correct_percent"]

        if correct_percent >= 90:
            return "Sehr gut! Das schaffen nicht viele!", "flamingos.gif"
        elif correct_percent >= 70:
            return "Gar nicht schlecht! Weiter so!", "gull.gif"
        elif correct_percent >= 30:
            return "Das sieht doch schon ganz solide aus!", "papageintaucher.gif"
        else:
            return "Ausbaufähig, aber probiere es doch nochmal!", "sad.gif"

    def overall_accuracy_for_session(self):
        conn = sqlite3.connect("game_results.db")
        cursor = conn.cursor()
        cursor.execute("SELECT is_correct FROM results WHERE session_id = ?", (self.session_id,))

        results = cursor.fetchall()
        conn.close()

        if not results:
            return {
                "total": 0,
                "correct": 0,
                "incorrect": 0,
                "correct_percent": 0.0,
                "incorrect_percent": 0.0
            }

        total = len(results)
        correct = sum(row[0] for row in results)  # is_correct ist 1 oder 0
        incorrect = total - correct

        correct_percent = (correct / total) * 100
        incorrect_percent = 100 - correct_percent

        return {
            "total": total,
            "correct": correct,
            "incorrect": incorrect,
            "correct_percent": round(correct_percent),
            "incorrect_percent": round(incorrect_percent)
        }

    def species_bar(self):
        species_data = self.load_species_accuracy_for_session()
        bar_width = 40
        space_between_bars = 100  # Abstand zwischen Balken
        total_bars = len(species_data)
        chart_width = max(800, total_bars * (bar_width + space_between_bars))  # Mindestbreite 800px, sonst skaliert

        # 🔹 Bar Chart Gruppen erstellen
        bars = []
        for i, (species, values) in enumerate(species_data.items()):
            accuracy = values["accuracy"]
            total_count = values["total_count"]

            bars.append(
                ft.BarChartGroup(
                    x=i,  # Position auf der X-Achse
                    bar_rods=[
                        ft.BarChartRod(
                            from_y=0,
                            to_y=accuracy,
                            width=bar_width,  #Konstante Balkenbreite
                            color=ft.Colors.GREEN_800,
                            tooltip=f"{species}\nRichtig: {accuracy:.0f}%\nGesamtzahl Audios: {total_count}",
                            border_radius=5,
                        )
                    ]
                )
            )

        # 🔹 Barchart-Widget mit festen Y-Achsen-Werten (0-100%)
        bar_chart = ft.BarChart(
            bar_groups=bars,
            border=ft.border.only(bottom=ft.border.BorderSide(1,ft.Colors.ON_SECONDARY_CONTAINER), left=ft.border.BorderSide(1,ft.Colors.ON_SECONDARY_CONTAINER)),
            horizontal_grid_lines=ft.ChartGridLines(interval=10),
            vertical_grid_lines=ft.ChartGridLines(interval=2),
            left_axis=ft.ChartAxis(
                title=ft.Text("Prozent richtige Antworten"),
                title_size=40, labels_size=40,
                labels=[
                    ft.ChartAxisLabel(value=i, label=ft.Text(f"{i}"))
                    for i in range(0, 101, 10)
                ],
            ),
            bottom_axis=ft.ChartAxis(
                labels_size=40, title_size=40,
                title=ft.Text("Arten"),
                labels=[ft.ChartAxisLabel(value=i, label=ft.Text(species, rotate=0))
                        for i, species in enumerate(species_data.keys())],
            ),
            tooltip_bgcolor="grey",
            tooltip_fit_inside_horizontally=True,
            tooltip_fit_inside_vertically=True,
            max_y=100,
            width=chart_width,  # Dynamische Breite je nach Anzahl der Balken
            height=400,
        )

        # 🔹 Scrollbaren Container erstellen
        scrollable_chart = ft.Row(
            controls=[bar_chart],
            scroll=ft.ScrollMode.ALWAYS  # Immer scrollbar, falls Diagramm zu groß ist
        )

        return scrollable_chart

    def load_species_accuracy_for_session(self):
        print(f"[DEBUG] Lade Daten für Session-ID {self.session_id}")

        conn = sqlite3.connect("game_results.db")
        cursor = conn.cursor()

        # Korrekte Antworten pro Art in der aktuellen Session abrufen
        cursor.execute("""
             SELECT correct_species, 
                    SUM(is_correct) AS correct_count, 
                    COUNT(*) AS total_count
             FROM results
             WHERE session_id = ?
             GROUP BY correct_species
         """, (self.session_id,))

        data = cursor.fetchall()
        conn.close()

        # Erzeuge ein Dictionary mit den Prozentsätzen
        species_accuracy = {}
        for species, correct_count, total_count in data:
            accuracy = (correct_count / total_count) * 100 if total_count > 0 else 0

            # **🔹 Hier nutzen wir die bestehende Übersetzungsfunktion `lookup_species`**
            translated_species = self.app_state.lookup_species(species)

            if translated_species:
                display_name = translated_species["Deutsch"]  # Oder eine andere Sprache, falls gewünscht
            else:
                display_name = species  # Falls keine Übersetzung gefunden wird

            species_accuracy[display_name] = {"accuracy": accuracy, "total_count": total_count}

        return species_accuracy

    def plot_confusion_matrix(self, save_path="matrix_plot.png"):
        print(f"[DEBUG] Erstelle Confusion Matrix für Session-ID {self.session_id}")

        # 🔹 Lade alle Ergebnisse aus der aktuellen Session
        conn = sqlite3.connect("game_results.db")
        df = pd.read_sql_query(
            "SELECT correct_species, selected_species FROM results WHERE session_id = ?",
            conn,
            params=(self.session_id,)
        )
        conn.close()

        if df.empty:
            print("[WARN] Keine Daten für die aktuelle Session.")
            return

        print("[DEBUG] Original-Daten geladen:", df.head())

        # 🔹 Übersetze die Artnamen
        def translate(name):
            res = self.app_state.lookup_species(name)
            return res["Deutsch"] if res else name

        df["correct_translated"] = df["correct_species"].apply(translate)
        df["selected_translated"] = df["selected_species"].apply(translate)

        # 🔹 Artenliste in Original-Reihenfolge sichern
        session_species = list(dict.fromkeys(df["correct_translated"].tolist() + df["selected_translated"].tolist()))
        print("[DEBUG] Übersetzte Arten:", session_species)

        # 🔹 Leere nxn-Matrix mit allen Arten als Index und Spalten
        matrix = pd.DataFrame(
            np.zeros((len(session_species), len(session_species))),
            index=session_species,
            columns=session_species
        )

        # Berechne echte Confusion Matrix
        crosstab = pd.crosstab(df["correct_translated"], df["selected_translated"])

        # Werte in Matrix einfügen
        matrix = matrix.add(crosstab, fill_value=0)

        # Plotten
        plt.switch_backend("Agg")

        if matrix.empty:
            print("[WARN] Matrix ist leer.")
            return

        n = matrix.shape[0]
        diag_mask = np.eye(n, dtype=bool)
        off_diag_mask = ~diag_mask

        max_value = matrix.values.max()
        norm = plt.Normalize(vmin=0, vmax=max_value)

        fig, ax = plt.subplots(figsize=(10, 8))
        fig.patch.set_facecolor('black')
        ax.set_facecolor('black')
        ax.xaxis.tick_top()
        ax.xaxis.set_label_position("top")

        cmap_off_diag = sns.light_palette("#5cb85c", as_cmap=True)
        cmap_diag = sns.light_palette("#f0ad4e", as_cmap=True)

        sns.heatmap(matrix, mask=off_diag_mask, cmap=cmap_off_diag, annot=True,
                    cbar=False, linewidths=0, ax=ax, norm=norm, square=True)
        sns.heatmap(matrix, mask=diag_mask, cmap=cmap_diag, annot=True,
                    cbar=False, linewidths=0, ax=ax, norm=norm, square=True)

        ax.set_xlabel("Your Prediction", fontsize=18, labelpad=10, color='white')
        ax.set_ylabel("Correct Species", fontsize=18, labelpad=10, color='white')
        ax.tick_params(colors='white')
        plt.xticks(rotation=45, ha='left', fontsize=11, color='white')
        plt.yticks(rotation=0, fontsize=11, color='white')

        plt.subplots_adjust(left=0.2, right=0.9, top=0.85, bottom=0.15)
        plt.tight_layout(pad=2)
        plt.savefig(save_path, transparent=True, dpi=300)

        print(f"[DEBUG] Confusion Matrix gespeichert: {save_path}")


class Overallsettings(BasePage):
    def __init__(self, page, app_state):
        super().__init__(page, app_state)

        self.build_appbar()
        self.page.padding = 20
        self.page.controls.clear()
        self.build_layout()
        self.update()

    def build_layout(self):
        # Titel
        title = ft.Container(
            alignment=ft.alignment.center,
            content=ft.Text(
                "Allgemeine Einstellungen",
                style="headlineMedium",
                text_align=ft.TextAlign.CENTER,
                weight=ft.FontWeight.BOLD
            )
        )

        # Button & Liste erstellen
        self.user_lists_column = ft.Column(spacing=10)
        self.new_list_name = ft.TextField(
            label="Name der Liste: Species A, Species B, ...",
            hint_text="Name der Liste: Species A, Species B, ... ",
            border_color="black",
            text_style=ft.TextStyle(color="black"),
            label_style=ft.TextStyle(color="black"),
            expand=True
        )

        add_list_button = ft.ElevatedButton(
            text="Liste erstellen",
            icon=ft.Icons.ADD,
            on_click=self.add_user_list
        )

        # Bereits gespeicherte Listen anzeigen
        for name, species in self.app_state.load_user_lists().items():
            comp = UserList(name, species, self.delete_user_list, self.save_user_lists)
            self.user_lists_column.controls.append(comp)

        user_lists_area = ft.Container(
            padding=20,
            content=ft.Column(
                spacing=10,
                controls=[
                    self.new_list_name,
                    add_list_button,
                    self.user_lists_column
                ]
            )
        )

        # Expansion Panels
        expansion_panels = ft.Container(
            alignment=ft.alignment.center,
            width=self.page.width * 0.8,  # 80 % der Seitenbreite
            content=ft.ExpansionPanelList(
                elevation=2,
                divider_color=ft.Colors.INVERSE_SURFACE,
                controls=[
                    ft.ExpansionPanel(
                        header=ft.Container(
                            alignment=ft.alignment.center,
                            padding=10,
                            content=ft.Text(
                                "Eigene Listen erstellen",
                                style="titleMedium"
                            )
                        ),
                        bgcolor=ft.Colors.PRIMARY_CONTAINER,
                        content=user_lists_area
                    ),
                    ft.ExpansionPanel(
                        header=ft.Container(
                            alignment=ft.alignment.center,
                            padding=10,
                            content=ft.Text(
                                "Bilder Cache löschen",
                                style="titleMedium"
                            )
                        ),
                        bgcolor=ft.Colors.PRIMARY_CONTAINER,
                        content=ft.ListTile(
                            title=ft.Text("Alle bisher gespeicherten Bilder löschen"),
                            subtitle=ft.Text("Press the icon to delete the Picture Cache"),
                            trailing=ft.IconButton(icon=ft.Icons.DELETE, tooltip="Alle Bilder löschen",
                                                   on_click=lambda e: self.delete_entire_image_cache())
                        )
                    ),
                    ft.ExpansionPanel(
                        header=ft.Container(
                            alignment=ft.alignment.center,
                            padding=10,
                            content=ft.Text(
                                "Gespeicherte Ergebnisse verwalten",
                                style="titleMedium"
                            )
                        ),
                        bgcolor=ft.Colors.PRIMARY_CONTAINER,
                        content=ft.ListTile(
                            title=ft.Text("Alle bisher gespeicherten Ergebnisse (Sessions) löschen"),
                            subtitle=ft.Text("Press the icon to delete Saved Results"),
                            trailing=ft.IconButton(icon=ft.Icons.DELETE, tooltip="Alle Sessions löschen",
                                                   on_click=lambda e: self.delete_all_results())
                        )
                    )
                ]
            )
        )

        # Scrollbarer Bereich mit fester Höhe
        scrollable_container = ft.Container(
            height=self.page.height * 0.6,
            content=ft.Column(
                controls=[expansion_panels],
                spacing=20,
                scroll=ft.ScrollMode.AUTO
            )
        )

        # Seite gestalten
        layout = ft.Column(
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=30,
            controls=[
                title,
                ft.Text(
                    "© SoundBirdQuiz 2025. Das ist ein Spaßprojekt von L. Griem und J. Pieper. \nRecordings von XenoCanto.org. "),
                scrollable_container
            ]
        )

        self.page.add(layout)

    def get_info_alert_content(self):
        return (
            "Allgemeine Einstellungen",
            "Hier kannst du z.B. gespeicherte Datensätze von deinem Computer löschen"
        )

    def delete_all_results(self):
        db_path = os.path.join(os.getenv("LOCALAPPDATA"), "SoundBirdQuiz", "game_results.db")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM results")
        conn.commit()
        conn.close()
        print("[INFO] Alle Einträge wurden gelöscht.")

    def delete_entire_image_cache(self):
        cache_dir = "bird_cache"
        if os.path.exists(cache_dir):
            try:
                shutil.rmtree(cache_dir)
                print("[INFO] Gesamter Bilder-Cache erfolgreich gelöscht.")
            except Exception as e:
                print(f"[ERROR] Fehler beim Löschen des Bild-Caches: {e}")
        else:
            print("[INFO] Kein Cache-Ordner vorhanden – nichts zu löschen.")

    def save_user_lists(self):
        lists = {
            comp.list_name: comp.species_str
            for comp in self.user_lists_column.controls
            if isinstance(comp, UserList)
        }
        with open("user_lists.json", "w", encoding="utf-8") as f:
            json.dump(lists, f, ensure_ascii=False, indent=4)

    def add_user_list(self, e):
        raw = self.new_list_name.value.strip()

        # Trenne Name und Inhalt: Format = "Name: Amsel, Blaumeise"
        if ":" in raw:
            list_name, species_str = map(str.strip, raw.split(":", 1))
        else:
            list_name = raw
            species_str = ""

        if not list_name:
            return

        comp = UserList(list_name, species_str, self.delete_user_list, self.save_user_lists)
        self.user_lists_column.controls.append(comp)
        self.new_list_name.value = ""
        self.save_user_lists()
        self.update()

    def delete_user_list(self, comp):
        self.user_lists_column.controls.remove(comp)
        self.save_user_lists()
        self.update()

    def get_info_alert_content(self):
        return (
            "Allgemeine Einstellungen",
            "Hier kannst du z.B. gespeicherte Datensätze von deinem Computer löschen"
        )

class UserList(ft.Column):
    def __init__(self, list_name, species_str, on_delete, on_save=None):
        super().__init__()
        self.list_name = list_name
        self.species_str = species_str
        self.on_delete = on_delete
        self.on_save = on_save

        # Zeige direkt: "Name: Arten"
        self.display_label = ft.Text(value=f"{list_name}: {species_str}", size=16, color="black")
        self.edit_field = ft.TextField(value=f"{list_name}: {species_str}", expand=1)

        self.display_view = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                self.display_label,
                ft.Row(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.EDIT,
                            icon_color="black",
                            tooltip="Liste bearbeiten",
                            on_click=self.edit_clicked
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE,
                            icon_color="black",
                            tooltip="Liste löschen",
                            on_click=self.delete_clicked
                        ),
                    ]
                )
            ]
        )

        self.edit_view = ft.Row(
            visible=False,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                self.edit_field,
                ft.IconButton(
                    icon=ft.Icons.DONE,
                    tooltip="Speichern",
                    icon_color="black",
                    on_click=self.save_clicked
                ),
            ]
        )

        self.controls = [self.display_view, self.edit_view]

    def edit_clicked(self, e):
        self.edit_field.value = f"{self.list_name}: {self.species_str}"
        self.display_view.visible = False
        self.edit_view.visible = True
        self.update()

    def save_clicked(self, e):
        raw = self.edit_field.value.strip()
        if ":" in raw:
            name, species = map(str.strip, raw.split(":", 1))
            self.list_name = name
            self.species_str = species
        else:
            self.species_str = raw  # Falls keine Trennung vorhanden ist

        # Anzeige aktualisieren
        self.display_label.value = f"{self.list_name}: {self.species_str}"
        self.display_view.visible = True
        self.edit_view.visible = False
        if self.on_save:
            self.on_save()
        self.update()

    def delete_clicked(self, e):
        self.on_delete(self)




# =========================
# main
# =========================

def main(page: ft.Page):
    global app_state
    app_state = AppState()
    app_state.init_database()
    app_state.load_species_csv()
    app_state.start_local_http_server()





    page.title = "SoundBirdQuiz 2025"
    page.padding = 20
    page.theme_mode = app_state.theme_mode

    Router.init_routes(app_state)
    Router.go(page, "/")  # Startseite

ft.app(target=main)
#if __name__ == "__main__":
#    ft.app(target=main, view=ft.AppView.FLET_APP)
