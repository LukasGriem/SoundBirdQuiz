import ttkbootstrap as tb
from ttkbootstrap.constants import *
from tkinter import *
from ttkbootstrap.tooltip import ToolTip
from ttkbootstrap.scrolled import ScrolledFrame
import tkinter as tk
from tkinter import Frame
from PIL import Image, ImageTk, ImageSequence
if not hasattr(Image, "CUBIC"):
    Image.CUBIC = Image.BICUBIC
import random
import json  # Für Speichern/Laden der Einstellungen
import requests
import vlc
import threading
import urllib.request
import io
import pandas as pd  # Zum Einlesen der CSV-Datei
import asyncio
import aiohttp
import time


# Globaler Cache für API-Antworten
api_cache = {}


# --- Funktion zum Nachschlagen der Arten in der CSV ---
def lookup_species(species_input, species_df):
    """
    Sucht in species_df (CSV mit den Spalten 'Deutsch', 'Wissenschaftlich', 'Englisch')
    nach einem Eintrag, der dem normalisierten species_input (unabhängig von Groß-/Kleinschreibung
    und ob '+' als Trenner verwendet wird) entspricht.

    Gibt ein Dictionary zurück, z.B.:
    {"Deutsch": "Blaumeise", "Wissenschaftlich": "Cyanistes+caeruleus", "Englisch": "Blue Tit"}
    oder None, falls kein Eintrag gefunden wurde.
    """
    species_input_norm = species_input.strip().lower().replace("+", " ")
    for idx, row in species_df.iterrows():
        for col in ["Deutsch", "Wissenschaftlich", "Englisch"]:
            val = str(row[col]).strip().lower().replace("+", " ")
            if val == species_input_norm:
                return {
                    "Deutsch": row["Deutsch"],
                    "Wissenschaftlich": row["Wissenschaftlich"],
                    "Englisch": row["Englisch"]
                }
    return None


# --- Funktionen für den Xenocanto-Abruf und Audio-Playback ---
async def async_get_random_recording(species, record_type, sex_type, lifestage_type):
    """
    Führt die API-Abfrage asynchron durch und cached die Antwort.
    """
    key = (species, record_type)
    if key in api_cache:
        data = api_cache[key]
    else:
        record_type_final = record_type.lower()  # API erwartet Kleinbuchstaben
        type_query = f'+type:"{record_type_final}"' if record_type_final else ""
        sex_type_final = sex_type.lower()
        sex_query = f'+sex:"{sex_type_final}"' if sex_type_final else ""
        lifestage_type_final = lifestage_type.lower()
        lifestage_query = f'+stage:"{lifestage_type_final}"' if lifestage_type_final else ""
        url = f'https://www.xeno-canto.org/api/2/recordings?query={species}{type_query}{sex_query}{lifestage_query}'
        print(url)
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
    rec_value = rec.get("rec")
    lic_value = rec.get("lic")
    combined_info = ""
    if rec_value:
        combined_info += f"Recorded by {rec_value}"
    if lic_value:
        if combined_info:
            combined_info += " | "
        combined_info += f" licensed under: https:{lic_value}"
    return {"audio_url": audio_url, "sonogram_url": sonogram_url, "correct_species": species,  "copyright_info": combined_info}

def get_random_recording(species, record_type, sex_type, lifestage_type):
    """
    Synchrone Wrapper-Funktion, die das asynchrone Gegenstück ausführt.
    """
    try:
        return asyncio.run(async_get_random_recording(species, record_type, sex_type, lifestage_type))
    except Exception as e:
        print(f"Error in get_random_recording: {e}")
        return None



def fetch_wikipedia_bird_image(latin_name, thumb_size=300):
    """
    Searches English Wikipedia for the given Latin (scientific) bird name,
    retrieves the main page image, downloads it, and returns a Tkinter-compatible
    PhotoImage. Returns None if no suitable image is found.
    """
    # 1) Search Wikipedia for the page title
    endpoint = "https://en.wikipedia.org/w/api.php"
    search_params = {
        "action": "query",
        "list": "search",
        "srsearch": latin_name,
        "format": "json",
        "srnamespace": 0  # Limit to articles (not talk pages, etc.)
    }
    response = requests.get(endpoint, params=search_params).json()
    search_results = response.get("query", {}).get("search", [])
    if not search_results:
        return None

    # Take the first search result's title
    page_title = search_results[0]["title"]

    # 2) Use 'pageimages' to get the main page image (thumbnail)
    image_params = {
        "action": "query",
        "prop": "pageimages",
        "titles": page_title,
        "pithumbsize": thumb_size,  # how large (in px) the thumbnail should be
        "format": "json"
    }
    img_response = requests.get(endpoint, params=image_params).json()
    pages = img_response.get("query", {}).get("pages", {})
    if not pages:
        return None

    # Extract the thumbnail URL if present
    thumbnail_url = None
    for _, page_data in pages.items():
        thumb = page_data.get("thumbnail")
        if thumb and "source" in thumb:
            thumbnail_url = thumb["source"]
            break

    if not thumbnail_url:
        return None

    # 3) Download the image and convert to Tkinter-friendly PhotoImage
    img_data = requests.get(thumbnail_url).content
    img_pil = Image.open(io.BytesIO(img_data))
    # Resize (optional, can adjust as needed)
    img_pil = img_pil.resize((thumb_size, thumb_size))

    print(img_pil)
    return ImageTk.PhotoImage(img_pil)



def play_audio(game_window, audio_url):
    """
    Startet den Audio-Player (VLC) in einem separaten Thread, um das GUI nicht zu blockieren.
    """
    player = vlc.MediaPlayer(audio_url)
    game_window.player = player


    def run_player():
        player.play()

    threading.Thread(target=run_player, daemon=True).start()
    return player


def fetch_and_display_sonogram(sonogram_url, label):
    """
    Lädt das Sonogramm von der URL, wandelt es in ein PhotoImage um und zeigt es in dem übergebenen Label an.
    """
    try:
        with urllib.request.urlopen(sonogram_url) as u:
            raw_data = u.read()
        im = Image.open(io.BytesIO(raw_data))
        im = im.resize((400, 300))  # Bei Bedarf anpassen
        photo = ImageTk.PhotoImage(im)
        label.config(image=photo)
        label.image = photo  # Referenz speichern
    except Exception as e:
        print(f"Error fetching sonogram: {e}")


class AnimatedGIF(tk.Label):
    def __init__(self, master, gif_path, delay=100, **kwargs):
        super().__init__(master, **kwargs)
        self.gif = Image.open(gif_path)
        self.frames = [ImageTk.PhotoImage(frame.copy().convert("RGBA"))
                       for frame in ImageSequence.Iterator(self.gif)]
        self.delay = delay  # Zeit in Millisekunden zwischen den Frames
        self.idx = 0
        self.running = True
        self.config(image=self.frames[0])
        self.animate()

    def animate(self):
        if not self.running:
            return
        self.idx = (self.idx + 1) % len(self.frames)
        self.config(image=self.frames[self.idx])
        self.after_id = self.after(self.delay, self.animate)

    def stop(self):
        self.running = False
        if hasattr(self, 'after_id'):
            self.after_cancel(self.after_id)



# --- GUI und Einstellungen ---

# Hauptfenster
root = tb.Window(themename="superhero")
root.title("Vogelquiz Einstellungen")
root.state("zoomed")
#root.geometry("1300x900") #Größe manuell definiert

# Erstelle einen Top-Frame, der Logo und Überschrift enthält
top_frame = tk.Frame(root, bg=root.cget("background"))
top_frame.pack(side="top", pady=10)

# Logo laden und skalieren
logo_original = Image.open("logoBQ3s.png")
logo_resized = logo_original.resize((320, 250), Image.Resampling.LANCZOS)
logo_img = ImageTk.PhotoImage(logo_resized)

# Logo-Label im top_frame platzieren und zentrieren
logo_label = tk.Label(top_frame, image=logo_img, bg=root.cget("background"))
logo_label.image = logo_img  # Referenz sichern
logo_label.pack(side="top", anchor="center", pady=(0,5))

# Überschrift auf zwei Zeilen (mittig zentriert)
header_text = "Willkommen zum Vogelquiz!"
header_label = tb.Label(top_frame, text=header_text, font=("Helvetica", 28), justify="center", bootstyle="default")
header_label.pack(side="top", anchor="center", pady=(0,0))
# Subtitle
my_subtitle = tb.Label(top_frame, text="Teste deine Vogelstimmen-Kenntnisse", font=("Helvetica", 10))
my_subtitle.pack(pady=20)
#Hintergrundinfo
my_info = tb.Label(root, text="Audios von xeno-canto.org; Sound-BirdQuiz 2025 © L.Griem & J.Pieper", font=("Helvetica", 8))
my_info.place(relx=0, rely=1, anchor="sw", x=40, y=-40)

# Frame für die Buttons
button_frame = tb.Frame(root)
button_frame.pack(pady=10)

# Dateiname für das Speichern der Einstellungen
settings_file = "settings.json"


# Funktion zum Speichern der neuen Einstellungen
def save_new_settings(species_list, var_spectro, var_image, record_type, sex_type, lifestage_type):
    settings = {
        "species_list": species_list,
        "spectrogram": var_spectro.get(),  # 1 oder 0
        "image": var_image.get(),  # 1 oder 0 (optional, hier beispielhaft)
        "record_type": record_type.get(),  # "Call" oder "Song" oder "Other:Type"
        "sex_type": sex_type.get(),
        "lifestage_type": lifestage_type.get()
    }
    with open(settings_file, "w") as f:
        json.dump(settings, f)

    print(f"Artenliste: {species_list}")
    print(f"Spektrogramm: {'Ja' if var_spectro.get() == 1 else 'Nein'}")
    print(f"Bild: {'Ja' if var_image.get() == 1 else 'Nein'}")
    print(f"Aufnahmetyp: {record_type.get()}")
    print(f"sex_type: {sex_type.get()}"),
    print(f"lifestage_type: {lifestage_type.get()}")

    # Starte das Spiel in einem neuen Fenster
    gamestart(species_list)


# Funktion für den Button "Neue Einstellungen"
def NewSet():
    settings_frame = tb.Frame(root)
    settings_frame.pack(pady=10)

    settings_frame.grid_columnconfigure(0, weight=1)
    settings_frame.grid_columnconfigure(1, weight=2)

    outer_frame = Frame(settings_frame, bg="grey", borderwidth=2, relief="groove")
    outer_frame.pack(fill=BOTH, expand=YES, padx=10, pady=10)
    sf = ScrolledFrame(outer_frame, height=300, width=1000)
    sf.pack(fill=BOTH, expand=YES, padx=10, pady=10)

    # Verwende sf.innerframe als Container
    try:
        inner = sf.interior
    except AttributeError:
        # Falls es keine "interior" gibt, schau, ob Kinder vorhanden sind
        children = sf.winfo_children()
        if children:
            inner = children[0]
        else:
            # Falls überhaupt keine Kinder existieren, kannst du manuell einen Frame hinzufügen:
            inner = tk.Frame(sf)
            inner.pack(fill="both", expand=True)

    #Artenauswahl
    label_species_list = tb.Label(inner, text="Welche Arten möchtest du üben? (Komma getrennt)",
                                  font=("Arial", 12))
    label_species_list.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")

    species_list_entry = tb.Entry(inner, width=93)
    species_list_entry.grid(row=1, column=0, columnspan=2, padx=10, pady=10, sticky="nsew")

    # Checkbox für Spektrogramm
    var_spectro = IntVar()
    spectro_check = tb.Checkbutton(inner, bootstyle="success-round-toggle", text="Spektrogramm anzeigen",
                                   variable=var_spectro, onvalue=1, offvalue=0)
    spectro_check.grid(row=2, column=0, padx=50, pady=10)

    # Checkbox für Bild
    var_image = IntVar()
    image_check = tb.Checkbutton(inner, bootstyle="success-round-toggle", text="Bild anzeigen",
                                 variable=var_image, onvalue=1, offvalue=0)
    image_check.grid(row=2, column=1, padx=50, pady=10)

    # Radiobuttons für Aufnahmetyp (gemeinsame Variable=record_type)
    # Container-Frame für Radiobuttons und Combobox
    radio_frame = tb.Frame(inner)
    radio_frame.grid(row=3, column=0, columnspan=3, padx=50, pady=10)

    record_type = StringVar(value="All_type")  # Standard: Alle

    # Radiobuttons
    all_radio = tb.Radiobutton(radio_frame, bootstyle="success",
                                text="Alle üben",
                                variable=record_type,
                                value="All_type")
    all_radio.pack(side=LEFT, padx=10)

    call_radio = tb.Radiobutton(radio_frame, bootstyle="success",
                                text="Call üben",
                                variable=record_type,
                                value="Call")
    call_radio.pack(side=LEFT, padx=10)

    song_radio = tb.Radiobutton(radio_frame, bootstyle="success",
                                text="Song üben",
                                variable=record_type,
                                value="Song")
    song_radio.pack(side=LEFT, padx=10)

    other_radio = tb.Radiobutton(radio_frame, bootstyle="success",
                                 text="Anderer Sound-Typ",
                                 variable=record_type,
                                 value="Other")
    other_radio.pack(side=LEFT, padx=10)

    # Combobox – zunächst ausgeblendet
    custom_record_type = StringVar(value="")  # Diese Variable speichert den benutzerdefinierten Wert
    other_combobox = tb.Combobox(radio_frame, bootstyle="success", textvariable=custom_record_type)
    other_combobox["values"] = ["Drumming", "Alarm call", "Begging call", "Female song", "Flight call", "Imitation", "Subsong"]
    other_combobox.set("Bitte auswählen")
    other_combobox.pack_forget()

    # Callback, der die Combobox ein- oder ausblendet, je nachdem, ob "Other" gewählt ist.
    def on_record_type_change(*args):
        if record_type.get() == "Other":
            other_combobox.pack(side=LEFT, padx=10)  # anzeigen
        else:
            other_combobox.pack_forget()  # verstecken

    record_type.trace("w", on_record_type_change)

    # Callback, der auf eine Auswahl in der Combobox reagiert
    def on_other_selected(event):
        print("Custom sound type ausgewählt:", custom_record_type.get())

    other_combobox.bind("<<ComboboxSelected>>", on_other_selected)

    #Combobutton für Geschlecht und Lifestage
    sex_type = StringVar(value="")
    sex = ["All Gender", "Male", "Female"]
    selected_sex = tb.Combobox(inner, bootstyle="success", values=sex, textvariable=sex_type)
    selected_sex.set("All Gender")
    selected_sex.grid(row=5, column=0, padx=10, pady=20)

    lifestage_type = StringVar(value="")
    lifestage = ["All Stages", "Adult", "Juvenile", "Nestling"]
    selected_lifestage = tb.Combobox(inner, bootstyle="success", value=lifestage, textvariable=lifestage_type)
    selected_lifestage.set("All Stages")
    selected_lifestage.grid(row=5, column=1, padx=10, pady=20)

    def save_and_start():
        # Falls "Other" gewählt ist, überschreibe record_type mit dem aktuellen Wert der Combobox
        if record_type.get() == "Other":
            # Hier rufen wir den aktuell in der Combobox eingegebenen Text ab:
            new_value = other_combobox.get()
            record_type.set(new_value)
            print("record_type überschrieben mit:", new_value)
        if record_type.get() == "All_type":
            record_type.set ("")
        if sex_type.get() == "All Gender":
            sex_type.set ("")
        if lifestage_type.get() == "All Stages":
            lifestage_type.set ("")
        species_list = species_list_entry.get()
        save_new_settings(species_list, var_spectro, var_image, record_type,sex_type, lifestage_type)
        settings_frame.pack_forget()  # Formular ausblenden


    save_button = tb.Button(settings_frame, text="Einstellungen speichern und Spiel starten", bootstyle=SUCCESS,
                            command=save_and_start)
    save_button.pack(pady=10)


# Funktion zum Laden der alten Einstellungen
def load_old_settings():
    try:
        with open(settings_file, "r") as f:
            settings = json.load(f)
            print("Alte Einstellungen geladen:")
            print(f"Artenliste: {settings['species_list']}")
            print(f"Spektrogramm: {'Ja' if settings['spectrogram'] == 1 else 'Nein'}")
            print(f"Bild: {'Ja' if settings['image'] == 1 else 'Nein'}")
            print(f"Aufnahmetyp: {settings['record_type']}")
            print(f"Geschlecht: {settings['sex_type']}")
            print(f"Alter: {settings['lifestage_type']}")
            gamestart(settings['species_list'])
    except FileNotFoundError:
        print("Keine alten Einstellungen gefunden.")
        gamestart("")


# Buttons für Neue/Alte Einstellungen
b1 = tb.Button(button_frame, text="Neue Einstellungen", bootstyle=SUCCESS, command=NewSet)
b1.pack(side=LEFT, padx=5, pady=10)

b2 = tb.Button(button_frame, text="Alte Einstellungen", bootstyle=(SUCCESS, OUTLINE), command=load_old_settings)
b2.pack(side=LEFT, padx=5, pady=10)


# --- Spiel-Fenster mit integriertem Xenocanto-Quiz ---
def gamestart(species_list):
    # Die vom Nutzer eingegebene Liste (Komma-getrennt) – Elemente können in Deutsch, Wissenschaftlich oder Englisch sein
    Artenliste_input = [art.strip() for art in species_list.split(",") if art.strip()]


    # Lade die CSV mit den Artennamen (Spalten: Deutsch, Wissenschaftlich, Englisch)
    try:
        species_df = pd.read_csv("Europ_Species_3.csv")
    except Exception as e:
        print(f"Fehler beim Laden der CSV: {e}")
        return

    # Baue eine kanonische Artenliste (als englische Version) und eine Mapping-Datenstruktur:
    # canonical_species: key = englischer Name (in Lowercase), value = Dictionary mit allen Varianten
    # species_options: Liste der kanonischen (englischen) Namen
    canonical_species = {}
    species_options = []
    for art in Artenliste_input:
        mapping = lookup_species(art, species_df)
        if mapping:
            eng = mapping["Englisch"].strip()
            eng_lower = eng.lower()
            canonical_species[eng_lower] = mapping
            species_options.append(eng_lower)
        else:
            print(f"Art '{art}' nicht in der CSV gefunden.")
    if not species_options:
        print("Keine gültigen Arten gefunden. Spiel kann nicht gestartet werden.")
        return

    # Lade gespeicherte Einstellungen (z.B. Spektrogramm, Aufnahmetyp)
    try:
        with open(settings_file, "r") as f:
            settings = json.load(f)
    except Exception:
        settings = {"spectrogram": 0, "record_type": "Call", "species_list": species_list}


    game_window = Toplevel(root)
    game_window.title("Vogelquiz Spiel")
    #game_window.geometry("1300x800") #Größe manuell definiert
    game_window.state("zoomed")

    def on_closing():
        if hasattr(game_window, 'player'):
            game_window.player.stop()
        game_window.destroy()

    game_window.protocol("WM_DELETE_WINDOW", on_closing)


    game_label = tb.Label(game_window, text="Teste dein Wissen", font=("Helvetica", 20))
    game_label.pack(pady=20)

    # Punktestand speichern
    game_window.korrekte_antworten = 0
    game_window.falsche_antworten = 0
    game_window.canonical_species = canonical_species
    game_window.species_stats = {}  # z.B. { "blue tit": {"correct": 0, "wrong": 0}, ... }

    # Audio-Frame für Visualisierung/Info vom Audio
    audio_frame = tb.Frame(game_window)
    audio_frame.pack(pady=40, fill=X, padx=50)

    def repeat_current_audio():
        # Stoppe das aktuelle Audio, falls es noch läuft
        if current_round.get("audio_player"):
            current_round["audio_player"].stop()

        # Hole die aktuelle Audio-URL aus der laufenden Aufnahme
        audio_url = current_round["recording"]["audio_url"]
        # Starte das Audio neu
        player = play_audio(game_window,audio_url)
        current_round["audio_player"] = player

        # Fortschrittsbalken zurücksetzen
        audio_progress.config(value=0)
        audio_progress.start(15)



    info_audio_button = tb.Label(audio_frame, text="Audio läuft", bootstyle="secondary")
    info_audio_button.grid(row=0, column=1, padx=10)

    repeat_button = tb.Button(audio_frame, text= "REPEAT", bootstyle="secondary-outline", command=repeat_current_audio)
    repeat_button.grid(row=1, column=2, padx=10)

    #Audio-Progressbar
    audio_progress = tb.Progressbar(audio_frame, bootstyle="success", mode="indeterminate", value=10)
    audio_progress.grid(row=1, column=1, padx=10, pady=10, sticky="ew")
    audio_progress.start(15)

    # Copyright_Info-Button
    game_window.info_button = tb.Button(audio_frame, text="?", bootstyle="light-link")
    game_window.info_button.grid(row=1, column=0, padx=10)
    game_window.info_button.tooltip = ToolTip(game_window.info_button, text="Keine Info verfügbar", bootstyle=(LIGHT, INVERSE))

    def update_info_tooltip(button, new_text):
        try:
            button.tooltip.config(text=new_text)
        except Exception:
            # Falls das nicht funktioniert, erstelle einen neuen Tooltip
            button.tooltip = ToolTip(button, text=new_text, bootstyle=(LIGHT, INVERSE))



    # Erstelle einen Media-Frame für Vogelbild und Spektrogramm (nebeneinander)
    media_frame = tb.Frame(game_window)
    media_frame.pack(pady=10)
    # Label für das Vogelbild:
    image_label = tb.Label(media_frame)
    image_label.grid(row=0, column=0, padx=10)
    # Label für das Spektrogramm:
    sonogram_label = tb.Label(media_frame)
    sonogram_label.grid(row=0, column=1, padx=10)

    # Speichere die Labels als Attribute des Fensters, damit sie in anderen Funktionen zugänglich sind
    game_window.image_label = image_label
    game_window.sonogram_label = sonogram_label

    # Frame für Arten-Buttons
    art_frame = tb.Frame(game_window)
    art_frame.pack(pady=10)

    feedback_label = tb.Label(game_window, text="", font=("Helvetica", 14))
    feedback_label.pack(pady=20)

    # Erstelle für jede Art einen Button – als Anzeige nutzen wir den deutschen Namen
    species_buttons = []
    row = 0
    col = 0
    for eng in species_options:
        display_name = canonical_species[eng]["Deutsch"]
        btn = tb.Button(art_frame, text=display_name, bootstyle="success-outline-toolbutton",
                        command=lambda eng=eng: select_species(eng))
        btn.grid(row=row, column=col, padx=10, pady=20)
        species_buttons.append(btn)

        col += 1
        if col == 6:
            col = 0
            row += 1

    # Variable, in der wir Daten der aktuellen Runde speichern
    current_round = {"species": None, "recording": None, "audio_player": None}
    game_window.current_round = current_round  # Speichern im Fenster, damit end_game darauf zugreifen kann

    # --- Prefetch-Funktion ---
    def prefetch_next_round():
        def load_next():
            # Wähle zufällig eine Art aus der kanonischen Liste
            next_species = random.choice(species_options)
            next_correct_eng =  canonical_species[next_species]["Wissenschaftlich"]
            print(next_correct_eng)
            # Lade das Recording für die nächste Runde
            rec_data = get_random_recording(
                next_correct_eng,
                settings.get("record_type", "Call"),
                settings.get("sex_type", ""),
                settings.get("lifestage_type", "")
            )
            # Speichere das Ergebnis in der prefetched_round
            game_window.prefetched_round = {
                "species": next_species,
                "recording": rec_data
            }
         # Deaktiviere den NEXT Button
        next_button.config(state="disabled")

        # Fortschrittsbalken zurücksetzen
        audio_progress.config(value=0)
        audio_progress.start(15)


        threading.Thread(target=load_next, daemon=True).start()


    # --- Angepasste start_round() ---
    def start_round():
        # Entferne das bisher angezeigte Vogelbild, falls vorhanden:
        game_window.image_label.config(image='')
        game_window.image_label.image = None

        # Fortschrittsbalken zurücksetzen
        audio_progress.config(value=0)
        audio_progress.start(15)

        # Stoppe ggf. laufende Audio
        if current_round["audio_player"]:
            current_round["audio_player"].stop()
        feedback_label.config(text="")


        # Hier wird die aktuelle Runde synchron mit Spinner geladen
        current_species = random.choice(species_options)
        current_round["species"] = current_species
        correct_eng = canonical_species[current_species]["Wissenschaftlich"]

        # Spinner (indeterminate Progressbar) einblenden
        # Erstelle den Container im game_window – damit alle Kinder gemeinsam verwaltet werden
        game_window.loading_frame = tk.Frame(game_window)
        game_window.loading_frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        spinner = AnimatedGIF(game_window.loading_frame, "logo2.gif", delay=100)
        spinner.place(relx=0, rely=0, relwidth=1, relheight=1)

        loading_label = tk.Label(game_window.loading_frame,
                                     text="Neue Audios werden geladen...",
                                     font=("Helvetica", 16),
                                     bg="#ffffff", fg="#000000")
        loading_label.place(relx=0.5, rely=0.5, anchor="center")

        def load_recording():
            rec_local = get_random_recording(
                correct_eng,
                settings.get("record_type", "Call"),
                settings.get("sex_type", ""),
                settings.get("lifestage_type", "")
            )

            def update_ui(recording):
                # Falls der Lade-Container noch existiert, entferne ihn vollständig
                if hasattr(game_window, "loading_frame"):
                    game_window.loading_frame.destroy()
                    del game_window.loading_frame
                if not recording:
                    feedback_label.config(
                        text=f"Kein Recording für {canonical_species[current_species]['Deutsch']} gefunden, nächste Runde.")
                    return
                current_round["recording"] = recording
                player = play_audio(game_window, recording["audio_url"])
                current_round["audio_player"] = player


                if settings.get("spectrogram") == 1 and recording.get("sonogram_url"):
                    fetch_and_display_sonogram(recording["sonogram_url"], sonogram_label)
                else:
                    sonogram_label.config(image="")

                #Aktualisiere den Tooltip mit den kombinierten Infos:
                info_text = current_round["recording"].get("copyright_info", "Keine Info verfügbar")
                update_info_tooltip(game_window.info_button, info_text)

            game_window.after(0, lambda: update_ui(rec_local))

        threading.Thread(target=load_recording, daemon=True).start()


        # Starte das Prefetching für die nächste Runde
        prefetch_next_round()

    # --- Angepasste next_round() ---
    def next_round():
        # Entferne das bisher angezeigte Vogelbild, falls vorhanden:
        game_window.image_label.config(image='')
        game_window.image_label.image = None

        for btn in species_buttons:
            btn.config(state=NORMAL)
        sonogram_label.config(image="")

        # Stoppe das aktuelle Audio, falls es noch läuft
        if current_round.get("audio_player"):
            current_round["audio_player"].stop()

        # Deaktiviere den NEXT Button
        next_button.config(state="disabled")

        # Fortschrittsbalken zurücksetzen
        audio_progress.config(value=0)
        audio_progress.start(15)

        # Feedback entfernen, indem der Text geleert wird
        feedback_label.config(text="")

        # Prüfe, ob bereits eine vorgeladene Runde vorliegt
        if getattr(game_window, "prefetched_round", None) is not None:
            next_data = game_window.prefetched_round
            # Aktualisiere current_round mit den vorgeladenen Daten
            current_round["species"] = next_data["species"]
            rec = next_data["recording"]

            if not rec:
                feedback_label.config(
                    text=f"Kein Recording für {canonical_species[current_round['species']]['Deutsch']} gefunden, nächste Runde.")
                # Starte Prefetch erneut
                prefetch_next_round()
                return
            current_round["recording"] = rec
            player = play_audio(game_window,rec["audio_url"])
            current_round["audio_player"] = player


            if settings.get("spectrogram") == 1 and rec.get("sonogram_url"):
                fetch_and_display_sonogram(rec["sonogram_url"], sonogram_label)
            else:
                sonogram_label.config(image="")
            # Leere die prefetched_round und lade die nächste Runde vor
            game_window.prefetched_round = None
            prefetch_next_round()

            # Aktualisiere den Tooltip mit den kombinierten Infos:
            info_text = current_round["recording"].get("copyright_info", "Keine Info verfügbar")
            update_info_tooltip(game_window.info_button, info_text)
        else:
            # Fallback: Falls keine vorgeladene Runde vorliegt, lade synchron
            start_round()


    def select_species(selected_eng):
        # Stoppe ggf. laufende Audio
        if current_round["audio_player"]:
            current_round["audio_player"].stop()

        #Audio_progress stoppen
        audio_progress.stop()

        species = current_round["species"]
        # Initialisiere Statistik, falls noch nicht vorhanden:
        if species not in game_window.species_stats:
            game_window.species_stats[species] = {"correct": 0, "wrong": 0}

        if selected_eng == species:
            feedback_label.config(text="Richtig!")
            game_window.korrekte_antworten += 1
            game_window.species_stats[species]["correct"] += 1
        else:
            richtig_deu = canonical_species[species]["Deutsch"]
            feedback_label.config(text=f"Falsch! Richtig war: {richtig_deu}")
            game_window.falsche_antworten += 1
            game_window.species_stats[species]["wrong"] += 1

        # Falls die Bildoption aktiviert ist, lade und zeige das Vogelbild:
        if settings.get("image") == 'Ja':
            try:
                latin_name_raw = canonical_species[species]["Wissenschaftlich"]
                # Replace the + sign with a space
                latin_name = latin_name_raw.replace("+", " ")
                print(latin_name)
                photo = fetch_wikipedia_bird_image(latin_name, thumb_size=300)
                if photo:
                    game_window.image_label.config(image=photo)
                    game_window.image_label.image = photo  # keep a reference
                else:
                    print(f"No Wikipedia image found for '{latin_name}'.")
            except Exception as e:
                print(f"Error fetching Wikipedia image for {species}: {e}")

        # Deaktiviere alle Antwort-Buttons
        for btn in species_buttons:
            btn.config(state=DISABLED)

        # Aktiviere den NEXT Button
        next_button.config(state="normal")

    def skip_round():
        if current_round["audio_player"]:
            current_round["audio_player"].stop()


        species = current_round["species"]
        if species not in game_window.species_stats:
            game_window.species_stats[species] = {"correct": 0, "wrong": 0}

        richtig_deu = canonical_species[species]["Deutsch"]
        feedback_label.config(text=f"Übersprungen! Richtig war: {richtig_deu}")

        # Bild anzeigen, falls aktiviert
        if settings.get("image") == 'Ja':
            try:
                latin_name_raw = canonical_species[species]["Wissenschaftlich"]
                # Replace the + sign with a space
                latin_name = latin_name_raw.replace("+", " ")
                print(latin_name)
                photo = fetch_wikipedia_bird_image(latin_name, thumb_size=300)
                if photo:
                    game_window.image_label.config(image=photo)
                    game_window.image_label.image = photo  # keep a reference
                else:
                    print(f"No Wikipedia image found for '{latin_name}'.")
            except Exception as e:
                print(f"Error fetching Wikipedia image for {species}: {e}")

        for btn in species_buttons:
            btn.config(state=DISABLED)

        next_button.config(state="normal")

    # Frame für Steuerungs-Buttons (SKIP, NEXT)
    control_frame = tb.Frame(game_window)
    control_frame.pack(pady=30, fill=X, padx=50)
    control_frame.grid_columnconfigure(0, weight=1)
    control_frame.grid_columnconfigure(1, weight=1)

    skip_button = tb.Button(control_frame, text="SKIP", bootstyle="success-outline", command=skip_round)
    skip_button.grid(row=0, column=0, padx=10, sticky="ew")

    next_button = tb.Button(control_frame, text="NEXT", state="disabled", bootstyle="success", command=next_round)
    next_button.grid(row=0, column=1, padx=10, sticky="ew")

    #Frame für end_back_button
    end_back_frame = tb.Frame(game_window)
    end_back_frame.pack(pady=30)

    # Back to Settings

    # Der End-Game-Button stoppt zusätzlich das laufende Audio
    endgame_button = tb.Button(end_back_frame, text="Spiel beenden", bootstyle="secondary",
                               command=lambda: end_game(game_window))
    endgame_button.pack (side=LEFT, padx=5, pady=10)


    backset_button = tb.Button(end_back_frame, text="Zurück zu Einstellungen", bootstyle="secondary",
                               command=lambda: back_to_settings(game_window))
    backset_button.pack (side=LEFT, padx=5, pady=10)

    start_round()

def back_to_settings(game_window):
     if game_window.current_round.get("audio_player"):
         game_window.current_round["audio_player"].stop()

     game_window.destroy()

def end_game(game_window):
    # Laufendes Audio stoppen (falls vorhanden) und Spiel-Fenster schließen
    if game_window.current_round.get("audio_player"):
        game_window.current_round["audio_player"].stop()

    correct_total = game_window.korrekte_antworten
    wrong_total = game_window.falsche_antworten
    game_window.destroy()

    # Neues Fenster für die Gesamtergebnisse
    results_window = tb.Toplevel(root)
    results_window.title("Gesamtergebnisse")
    #results_window.geometry("1200x800") # Window Größe manuell definiert
    results_window.state("zoomed")

    # Gesamtübersicht oben
    total_score_label = tb.Label(
        results_window,
        text=(f"Richtige Antworten (gesamt): {correct_total}\n"
              f"Falsche Antworten (gesamt): {wrong_total}"),
        font=("Arial", 12)
    )
    total_score_label.pack(pady=20)

    # Labelframe für die einzelnen Arten
    species_frame = tb.Labelframe(results_window, text="Ergebnisse pro Art", bootstyle="success")
    species_frame.pack(fill="both", expand=True, padx=10, pady=10)

    # Zunächst alle Widgets (Statistik-Label und Meter) in eine Liste sammeln
    meter_widgets = []
    # Sortierte Liste aller Arten (damit auch unbeantwortete Arten ein Meter bekommen)
    species_list = sorted(game_window.canonical_species.items(), key=lambda x: x[1]["Deutsch"])

    for species_lower, mapping in species_list:
        # Stats aus species_stats holen oder Default 0
        stats = game_window.species_stats.get(species_lower, {"correct": 0, "wrong": 0})
        total_attempts = stats["correct"] + stats["wrong"]

        # Prozentwert, auf 1 Nachkommastelle gerundet
        if total_attempts == 0:
            percentage = 0
        else:
            percentage = round((stats["correct"] / total_attempts) * 100)

        # Label zeigt nur "3 korrekt / 10 Audios"
        label_text = f"{stats['correct']} korrekt / {total_attempts} Audios"
        stats_label = tb.Label(species_frame, text=label_text, font=("Arial", 8))
        # Erstelle den Meter – dieser zeigt als Subtext den deutschen Namen
        meter = tb.Meter(
            species_frame,
            bootstyle="success",
            amountused=percentage,
            amounttotal=100,
            metersize=150,
            textright="%",
            subtext=mapping["Deutsch"]
        )


        # Statt die Widgets direkt zu griden, speichern wir sie in einer Liste
        meter_widgets.append((stats_label, meter))

    # Funktion, die die Widgets abhängig von der Breite von species_frame anordnet
    def arrange_meters(event=None):
        # Errechne die verfügbare Breite des species_frame
        frame_width = species_frame.winfo_width()
        # Schätze eine Mindestbreite pro "Spalte" – Meter (150 Pixel) plus Padding (z.B. 20 Pixel)
        min_col_width = 150 + 20
        max_cols = max(1, frame_width // min_col_width)

        # Ordne die Widgets neu an
        for i, (s_label, meter) in enumerate(meter_widgets):
            r = (i // max_cols) * 2
            c = i % max_cols
            s_label.grid_configure(row=r, column=c, padx=10, pady=(10, 0), sticky="w")
            meter.grid_configure(row=r+1, column=c, padx=10, pady=(0, 10))

    # Binde das <Configure>-Event, damit bei Größenänderung die Widgets neu angeordnet werden
    species_frame.bind("<Configure>", arrange_meters)
    # Rufe arrange_meters einmal direkt auf, um die erste Anordnung zu setzen
    arrange_meters()

    # Schließen-Button
    close_button = tb.Button(results_window, text="Fenster schließen", command=results_window.destroy)
    close_button.pack(pady=20)





root.mainloop()
