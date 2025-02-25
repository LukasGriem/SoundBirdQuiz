import ttkbootstrap as tb
from ttkbootstrap.constants import *
from tkinter import *
from ttkbootstrap.tooltip import ToolTip
from ttkbootstrap.scrolled import ScrolledFrame
import tkinter as tk
from tkinter import Frame
from tkinter import Canvas, Scrollbar
from PIL import Image, ImageTk, ImageSequence
if not hasattr(Image, "CUBIC"):
    Image.CUBIC = Image.BICUBIC
import random
import json  # Für Speichern/Laden der Einstellungen
import requests
import vlc
import threading #
import urllib.request #
import io #
import pandas as pd  # Zum Einlesen der CSV-Datei
import asyncio #
import aiohttp
from PIL.Image import Resampling
import os #
import shutil #
import time #
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from bs4 import BeautifulSoup
import sys

#Resource_path Code von: https://stackoverflow.com/questions/31836104/pyinstaller-and-onefile-how-to-include-an-image-in-the-exe-file
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# Globaler Cache für API-Antworten
api_cache = {}


# --- Funktion zum Nachschlagen der Arten in der CSV ---
def lookup_species(species_input, species_df):
    """
    Sucht in species_df (CSV mit den Spalten 'Deutsch', 'Wissenschaftlich', 'Englisch')
    nach einem Eintrag, der dem normalisierten species_input entspricht.

    Gibt ein Dictionary zurück, z.B.:
    {"Deutsch": "Blaumeise", "Wissenschaftlich": "Cyanistes+caeruleus", "Englisch": "Blue Tit",
     "display_language": "Deutsch"}
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
                    "Englisch": row["Englisch"],
                    "display_language": col
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

def cache_bird_images(species_list):
    """
    For each species in species_list:
      1) Skip caching if 'bird_cache/<latin_name>/metadata.json' exists.
      2) Search English Wikipedia for a page title (list=search).
      3) Use 'pageimages' to get the lead thumbnail (pithumbsize=300) + file name.
      4) Query the file's license/author via 'imageinfo&extmetadata'.
      5) Download the thumbnail as image_0.jpg.
      6) Store metadata.json with: filename, license, author.

    This downloads exactly ONE image per species. You can later load it
    and display the license & author info as needed.
    """
    WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
    HEADERS = {"User-Agent": "WikiBirdBot/1.0 (+https://your-website.example)"}

    # Ensure the main cache directory exists
    os.makedirs("bird_cache", exist_ok=True)

    for species in species_list:
        # Create a folder name, e.g. "parus_major"
        safe_name = species.replace("+", "_").replace(" ", "_").lower()
        cache_dir = os.path.join("bird_cache", safe_name)
        metadata_file = os.path.join(cache_dir, "metadata.json")
        image_file = os.path.join(cache_dir, "image_0.jpg")

        # If this species is already cached, skip
        if os.path.exists(cache_dir) and os.path.exists(metadata_file):
            print(f"Images for '{species}' are already cached. Skipping...")
            continue

        # Otherwise, ensure a clean directory
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
        os.makedirs(cache_dir, exist_ok=True)

        print(f"[INFO] Caching the lead Wikipedia image for '{species}'...")

        # 1) Search for the Wikipedia page
        species_search_term = species.replace("+", " ").replace("_", " ").lower()
        print(species_search_term)
        search_params = {
            "action": "query",
            "list": "search",
            "srsearch": f"{species_search_term} +bird -chimp -ape -Pan",
            "format": "json"
        }
        try:
            resp = requests.get(WIKIPEDIA_API, headers=HEADERS, params=search_params)
            data = resp.json()
        except Exception as e:
            print(f"[ERROR] Searching '{species}': {e}")
            continue

        search_results = data.get("query", {}).get("search", [])
        if not search_results:
            print(f"[WARN] No Wikipedia page found for '{species}'.")
            continue

        page_title = search_results[0]["title"]
        print(page_title)

        # 2) Get the pageimage (thumbnail + file name)
        image_params = {
            "action": "query",
            "prop": "pageimages",
            "titles": page_title,
            "piprop": "thumbnail|name",
            "pithumbsize": 800,  # ~300 px wide
            "format": "json"
        }
        try:
            img_resp = requests.get(WIKIPEDIA_API, headers=HEADERS, params=image_params)
            img_data = img_resp.json()
        except Exception as e:
            print(f"[ERROR] pageimages for '{page_title}': {e}")
            continue

        pages = img_data.get("query", {}).get("pages", {})
        if not pages:
            print(f"[WARN] No pages returned from pageimages for '{page_title}'.")
            continue

        thumbnail_url = None
        file_name = None
        for _, page_info in pages.items():
            thumb = page_info.get("thumbnail")
            page_img_name = page_info.get("pageimage")  # e.g. "BlueTit.jpg"
            if thumb and page_img_name:
                thumbnail_url = thumb.get("source")
                file_name = "File:" + page_img_name
                break

        if not thumbnail_url or not file_name:
            print(f"[WARN] No thumbnail or file name found for '{page_title}'.")
            continue

        # 3) Fetch license & author from the File:* page
        file_params = {
            "action": "query",
            "titles": file_name,
            "prop": "imageinfo",
            "iiprop": "extmetadata",
            "format": "json"
        }
        try:
            file_resp = requests.get(WIKIPEDIA_API, headers=HEADERS, params=file_params)
            file_json = file_resp.json()
        except Exception as e:
            print(f"[ERROR] Fetching file metadata for '{file_name}': {e}")
            continue

        file_pages = file_json.get("query", {}).get("pages", {})
        license_str = ""
        author_str = ""
        for _, fpage_info in file_pages.items():
            imageinfo_list = fpage_info.get("imageinfo", [])
            if not imageinfo_list:
                continue
            extmetadata = imageinfo_list[0].get("extmetadata", {})
            license_str = extmetadata.get("LicenseShortName", {}).get("value", "")
            author_str = extmetadata.get("Artist", {}).get("value", "")
            break

        # 4) Download the thumbnail
        try:
            r = requests.get(thumbnail_url, headers=HEADERS)
            if r.status_code != 200:
                print(f"[ERROR] Could not download image from {thumbnail_url}, code={r.status_code}")
                continue

            with open(image_file, "wb") as f:
                f.write(r.content)
        except Exception as e:
            print(f"[ERROR] Downloading thumbnail for '{species}': {e}")
            continue

        # 5) Write metadata.json
        file_metadata = [{
            "filename": os.path.basename(image_file),
            "license": license_str,
            "author": author_str
        }]
        try:
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(file_metadata, f, ensure_ascii=False, indent=2)
            print(f"[OK] Cached image+metadata for '{species}': {image_file}")
        except Exception as e:
            print(f"[ERROR] Writing metadata.json for '{species}': {e}")
            # In case of error, optionally remove partial cache
            # shutil.rmtree(cache_dir)


def clear_bird_cache(): #heruntergeladene Bilder werden gelöscht. Aktuell nicht genutzte Funktion
    """
    Removes the entire 'bird_cache/' directory (if it exists),
    deleting all cached images and metadata.
    """
    cache_folder = "bird_cache"
    if os.path.exists(cache_folder):
        shutil.rmtree(cache_folder)
        print("Cleared the entire bird_cache folder.")
    else:
        print("No 'bird_cache' folder found to clear.")


def fetch_bird_image_from_commons(latin_name):
    """
    Retrieves a Tkinter PhotoImage + license + author for 'latin_name'.
    Loads the metadata.json in bird_cache/<latin_name>, picks one image randomly,
    loads it from disk, and returns:
        {
            "photo": <Tkinter PhotoImage>,
            "license": <str>,
            "author": <str>
        }
    or returns None if no cached images exist.
    """

    # Read the metadata file
    print("FETCH RUNS")
    safe_name = latin_name.replace("+", "_").replace(" ", "_").lower()
    cache_dir = os.path.join("bird_cache", safe_name)
    print(cache_dir)
    metadata_file = os.path.join(cache_dir, "metadata.json")

    if not os.path.exists(metadata_file):
        print(f"No local cache found for {latin_name}.")
        return None

    try:
        with open(metadata_file, "r", encoding="utf-8") as f:
            file_metadata = json.load(f)
    except Exception as e:
        print(f"Error reading metadata.json for {latin_name}:", e)
        return None

    if not file_metadata:
        print(f"Empty metadata for {latin_name}.")
        return None

    # Randomly pick one image
    chosen = random.choice(file_metadata)
    local_path = os.path.join(cache_dir, chosen["filename"])

    if not os.path.exists(local_path):
        print(f"Local image file missing: {local_path}")
        return None

    # Load from disk with Pillow
    try:
        img_pil = Image.open(local_path)

        # Berechne die neue Breite basierend auf der fixen Höhe von 300px
        width, height = img_pil.size
        new_height = 300
        new_width = int((new_height / height) * width)  # Verhältnis beibehalten

        # Skaliere das Bild mit .thumbnail(), das das Seitenverhältnis erhält
        img_pil.thumbnail((new_width, new_height), Image.Resampling.LANCZOS)

        # In Tkinter-kompatibles Format umwandeln
        photo = ImageTk.PhotoImage(img_pil)

        return {
            "photo": photo,
            "license": chosen["license"],
            "author": chosen["author"]
        }
    except Exception as e:
        print(f"Error opening local image {local_path}:", e)
        return None

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

def show_placeholder(label):
    # Erzeuge ein Placeholder-Bild von 400x300-Bild
    placeholder_img = Image.new("RGB", (300, 200), color="#2B3E50")
    placeholder_photo = ImageTk.PhotoImage(placeholder_img)
    label.config(image=placeholder_photo)
    label.image = placeholder_photo
    # WICHTIG: Referenz behalten, damit das Bild nicht vom Garbage Collector gelöscht wird


class AnimatedGIF(tk.Label):
    def __init__(self, master, gif_path, delay=10, **kwargs):
        super().__init__(master, **kwargs)
        self.gif = Image.open(gif_path)

        scale = 2.0 # Speichert den Skalierungsfaktor
        # Neue Größe berechnen
        original_width, original_height = self.gif.size
        new_size = (int(original_width * scale), int(original_height * scale))

        self.frames = [ImageTk.PhotoImage(frame.copy().convert("RGBA").resize(new_size, Image.LANCZOS))
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



def plot_final_stats_matrix(matrix, save_path=None):
    """
    Plots the final_stats_matrix as a heatmap with:
    - Diagonal values colored from white to green (higher values = darker green)
    - Off-diagonal values colored from white to red (higher values = darker red)
    - Dark theme: black background, white text
    - No title (as requested)
    - X-axis stays on top
    - Option to save as PNG for GUI integration
    """
    # Create masks for diagonal and off-diagonal elements
    diag_mask = np.eye(len(matrix), dtype=bool)
    off_diag_mask = ~diag_mask

    # Define colormaps
    cmap_diag = sns.light_palette("#5cb85c", as_cmap=True)
    cmap_off_diag = sns.light_palette("#f0ad4e", as_cmap=True)

    # Normalize values (0 = white)
    max_value = matrix.values.max()
    norm = plt.Normalize(vmin=0, vmax=max_value)

    # Create figure and axis with dark background
    fig, ax = plt.subplots(figsize=(10, 8))
    fig.patch.set_facecolor('black')  # Set figure background to black
    ax.set_facecolor('black')  # Set axis background to black

    # X-axis stays on top
    ax.xaxis.tick_top()
    ax.xaxis.set_label_position("top")

    # Plot off-diagonal values first (no grid lines)
    sns.heatmap(matrix, mask=~off_diag_mask, cmap=cmap_off_diag, annot=True,
                cbar=False, linewidths=0, ax=ax, norm=norm, square=True)

    # Overlay the diagonal values (no grid lines)
    sns.heatmap(matrix, mask=~diag_mask, cmap=cmap_diag, annot=True,
                cbar=False, linewidths=0, ax=ax, norm=norm, square=True)

    # Set axis labels in white
    ax.set_xlabel("Your Prediction", fontsize=18, labelpad=10, color='white')
    ax.set_ylabel("Correct Species", fontsize=18, labelpad=10, color='white')

    # Set tick labels in white
    ax.tick_params(colors='white')
    plt.xticks(rotation=45,ha='left', fontsize=11, color='white')
    plt.yticks(rotation=0, fontsize=11, color='white')

    # Ensure equal aspect ratio for quadratic cells
    ax.set_aspect('equal')
    plt.subplots_adjust(left=0.2, right=0.9, top=0.85, bottom=0.15) #Adjust margins
    plt.tight_layout(pad=2) #Tight layout but with padding


    # Save PNG with transparent background (for GUI integration)
    save_path = "matrix_plot.png"
    if save_path:
        plt.savefig(save_path, transparent=True, dpi=300)

def load_matrix_image(tab_matrix):
    try:
        image_path = "matrix_plot.png"  # Speicherpfad aus der Plot-Funktion
        image = Image.open(image_path)

        # Frame für den Canvas, der sich automatisch an die Größe des Tabs anpasst
        frame_canvas = tb.Frame(tab_matrix)
        frame_canvas.pack(fill="both", expand=True, padx=10, pady=10)
        frame_canvas.columnconfigure(0, weight=1)
        frame_canvas.rowconfigure(0, weight=1)

        # Canvas, der den gesamten Platz einnimmt
        canvas = Canvas(frame_canvas, bg="white")
        canvas.grid(row=0, column=0, sticky="nsew")

        # update_image passt das Bild an die Höhe des frame_canvas an und zentriert es
        def update_image(event=None):
            frame_width = frame_canvas.winfo_width()
            frame_height = frame_canvas.winfo_height()
            if frame_width > 0 and frame_height > 0:
                img_width, img_height = image.size
                # Skalierungsfaktor basierend auf der Höhe (das Bild kann auch vergrößert werden)
                scale_factor = frame_height / img_height
                new_width = int(img_width * scale_factor)
                new_height = int(img_height * scale_factor)
                image_resized = image.resize((new_width, new_height), Image.LANCZOS)
                img_tk = ImageTk.PhotoImage(image_resized)
                canvas.delete("all")
                # Bild genau in die Mitte des Canvas legen:
                canvas.create_image(frame_width // 2, frame_height // 2, anchor="center", image=img_tk)
                canvas.img_tk = img_tk  # Referenz speichern
                canvas.config(scrollregion=canvas.bbox("all"))

        # update_image wird immer dann aufgerufen, wenn sich der frame_canvas ändert
        frame_canvas.bind("<Configure>", update_image)
        update_image()  # Initialer Aufruf


    except Exception as e:
        print("Fehler beim Laden des Matrix-Bildes:", e)


def open_fullscreen_image(image):
    fs = tb.Toplevel()
    fs.state("zoomed")
    fs.title("Vollbildansicht_Confusion-Matrix")

    canvas_fs = Canvas(fs, bg="black")
    canvas_fs.pack(fill="both", expand=True)

    def update_fs(event=None):
        width = canvas_fs.winfo_width()
        height = canvas_fs.winfo_height()
        # Falls das Fenster noch sehr klein ist, abbrechen (damit width/height nicht 0 sind)
        if width < 50 or height < 50:
            return
        img_width, img_height = image.size
        scale_factor = min(width / img_width, height / img_height)
        new_width = max(1, int(img_width * scale_factor))
        new_height = max(1, int(img_height * scale_factor))
        img_resized = image.resize((new_width, new_height), Image.LANCZOS)
        img_tk_fs = ImageTk.PhotoImage(img_resized)
        canvas_fs.delete("all")
        # Bild in der Mitte des Canvas platzieren:
        canvas_fs.create_image(width // 2, height // 2, anchor="center", image=img_tk_fs)
        canvas_fs.img_tk = img_tk_fs  # Referenz speichern
        canvas_fs.config(scrollregion=canvas_fs.bbox("all"))

    fs.bind("<Configure>", update_fs)
    update_fs()


def load_all_species_from_csv():
    try:
        species_df = pd.read_csv(resource_path("Europ_Species_3.csv"))
    except Exception as e:
        print(f"Fehler beim Laden der CSV: {e}")
        return []

    # Hier nehmen wir an, dass die CSV eine Spalte "Deutsch" enthält
    if "Deutsch" not in species_df.columns:
        print("Spalte 'Deutsch' nicht in der CSV gefunden!")
        return []

    all_species = species_df["Deutsch"].dropna().unique().tolist()
    all_species = [str(name).strip() for name in all_species]
    return all_species




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
logo_original = Image.open(resource_path("logoBQ3s.png"))
logo_resized = logo_original.resize((300, 230), Image.Resampling.LANCZOS)
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
my_subtitle = tb.Label(top_frame, text="Teste deine Vogelstimmen-Kenntnisse. Du kannst die Arten auf Deutsch, Englisch oder als wissenschaftlichen Name (mit + getrennt) eingeben.",
                       font=("Helvetica", 10))
my_subtitle.pack(pady=20)
#Hintergrundinfo
my_info = tb.Label(root, text="Audios von xeno-canto.org; Sound-BirdQuiz 2025 © L.Griem & J.Pieper", font=("Helvetica", 8))
my_info.place(relx=0, rely=1, anchor="sw", x=40, y=-40)

# Frame für die Einstellungs-Buttons
button_frame = tb.Frame(root)
button_frame.pack(pady=10)

# Globale Variable für das Settings-Frame (initial None) -->Wichtig für Toolbutton Funktion bei "Neue Einstellungen"
settings_frame = None
# BooleanVar, die den Toggle-Status speichert -->Wichtig für Toolbutton Funktion bei "Neue Einstellungen"
toggle_var = tk.BooleanVar(value=False)

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
    global settings_frame
    if toggle_var.get():
        # Nur einmal erstellen, falls noch nicht vorhanden
        if settings_frame is None:
            settings_frame = tb.Frame(root)
            settings_frame.pack(pady=5)

            outer_frame = tb.Frame(settings_frame, bootstyle="dark")
            outer_frame.pack(fill=BOTH, expand=YES, padx=10, pady=5)

            sf = ScrolledFrame(outer_frame, height=300, width=1000)
            sf.pack(fill=BOTH, expand=YES, padx=10, pady=10)

            inner = tb.Frame(sf)
            inner.pack(fill="both", expand=True, padx=(5, 30), pady=10)
    else:
        # Beim Deaktivieren den Frame zerstören
        if settings_frame is not None:
            settings_frame.destroy()
            settings_frame = None



    label_species_list = tb.Label(inner, text="Welche Arten möchtest du üben? (Komma getrennt)",
                                  font=("Arial", 10))
    label_species_list.pack(pady=1)

    #Artenauswahl
    choose_species_frame = tb.Frame(inner)
    choose_species_frame.pack(pady=5, fill=BOTH, expand=YES)
    choose_species_frame.grid_columnconfigure(0, weight=1)
    choose_species_frame.grid_columnconfigure(1, weight=1)
    choose_species_frame.grid_columnconfigure(2, weight=1)

    #Entry für Arten
    species_list_entry = tb.Entry(choose_species_frame, bootstyle="secondary")
    species_list_entry.grid(row=0, column=0, columnspan=3, padx=10, pady=5, sticky="nsew")


    # Funktion zum automatisches Einfügen der Arten in das Entry-Feld
    item_var = tk.StringVar() # Variable für die Menüauswahl

    # Funktion zum Setzen der Artenliste basierend auf der Auswahl
    def set_species_list():
        selection = item_var.get()  # Aktuelle Auswahl aus dem Menü

        # Definiere die Arten für verschiedene Lebensräume
        habitat_species = {
            "Laubwald": "Blaumeise, Rotkehlchen, Singdrossel, Zaunkönig, Waldlaubsänger, Trauerschnäpper, Kohlmeise, Buntspecht, Gimpel, Zilpzalp, Mönchsgrasmücke, Kleiber",
            "Nadelwald": "Tannenmeise, Haubenmeise, Erlenzeisig, Fichtenkreuzschnabel, Waldbaumläufer, Wintergoldhähnchen",
            "Offenland/Agrarlandschaft": "Feldlerche, Rebhuhn, Neuntöter, Schwarzkehlchen, Dorngrasmücke, Grauammer, Goldammer, Feldsperling, Mäusebussard",
            "Siedlung": "Haussperling, Hausrotschwanz, Blaumeise, Bachstelze, Kohlmeise, Amsel, Feldsperling, Grünfink, Star, Buchfink, Elster",
            "Auenwald": "Pirol, Nachtigall, Kleinspecht, Mittelspecht, Trauerschnäpper, Kohlmeise, Blaumeise, Kleiber, Schwarzspecht, Buchfink",
            "Feuchtgebiet Binnenland": "Bartmeise, Sumpfrohrsänger, Schilfrohrsänger, Eisvogel, Rohrammer, Teichrohrsänger, Zwergtaucher, Waldwasserläufer, Kiebitz",
            "Alpine Zone": "Alpendohle, Mauerläufer, Bergpieper, Birkenzeisig, Hausrotschwanz, Alpenbraunelle",
            "Küste (typische Arten)": "Austernfischer, Silbermöwe, Sandregenpfeifer, Brandgans, Lachmöwe, Alpenstrandläufer, Rotschenkel, Eiderente"
        }

        # Falls die Auswahl existiert, ins Entry-Feld eintragen
        species_list_entry.delete(0, tk.END)
        species_list_entry.insert(0, habitat_species.get(selection, ""))

    # Menubutton für die spezifischen Habitat Listen
    specific_list = tb.Menubutton(choose_species_frame, text="Spezifische Habitate", bootstyle="success-outline")
    specific_list.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")

    # Menü mit Radiobuttons erstellen
    inside_specific_menu = tk.Menu(specific_list, tearoff=0)

    # Lebensräume zur Auswahl hinzufügen
    habitats = [
        "Alpine Zone",
        "Auenwald",
        "Feuchtgebiet Binnenland",
        "Küste (typische Arten)",
        "Laubwald",
        "Nadelwald",
        "Offenland/Agrarlandschaft",
        "Siedlung",
            ]

    # Menüeinträge mit Radiobuttons
    for habitat in habitats:
        inside_specific_menu.add_radiobutton(label=habitat, variable=item_var, value=habitat, command=set_species_list)

    specific_list["menu"] = inside_specific_menu


    # Funktion zum Setzen der Artenliste basierend auf der Auswahl
    def set_species_list_group():
        selection = item_var.get()  # Aktuelle Auswahl aus dem Menü

        # Definiere die Artengruppen
        group_species = {
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
            "Pieper": "Baumpieper, Wiesenpieper, Bergpieper, Rotkehlpieper, Brachpieper, Waldpieper"
        }

        # Falls die Auswahl existiert, ins Entry-Feld eintragen
        species_list_entry.delete(0, tk.END)
        species_list_entry.insert(0, group_species.get(selection, ""))

    # Menubutton für die spezifischen Artengruppen- Listen
    specific_group_list = tb.Menubutton(choose_species_frame, text="Spezifische Artenliste", bootstyle="success-outline")
    specific_group_list.grid(row=1, column=1, padx=10, pady=10, sticky="nsew")

    # Menü mit Radiobuttons erstellen
    inside_specific_group_menu = tk.Menu(specific_group_list, tearoff=0)

    # Artengruppen zur Auswahl hinzufügen
    groups = [
        "Ammern",
        "Drosseln",
        "Enten",
        "Eulen",
        "Greifvögel",
        "Laubsänger",
        "Meisen",
        "Mitteleuropäische Grasmücken",
        "Möwen",
        "Pieper",
        "Rohrsänger",
        "Schnäpper",
        "Singvogelzug",
        "Spechte",
        "Watvögel"
        ]

    # Menüeinträge mit Radiobuttons
    for group in groups:
        inside_specific_group_menu.add_radiobutton(label=group, variable=item_var, value=group, command=set_species_list_group)

    specific_group_list["menu"] = inside_specific_group_menu

    # Funktion zum Setzen der Artenliste basierend auf der Auswahl
    def set_species_list_similar():
        selection = item_var.get()  # Aktuelle Auswahl aus dem Menü

        # Definiere die Arten für verschiedene Paare
        similar_species = {
            "Eisvogel-Heckenbraunelle (Call)": "Eisvogel, Heckenbraunelle",
            "Zippammer-Zaunammer (Call)": "Zippammer, Zaunammer",
            "Blaumerle-Steinrötel (Song)": "Blaumerle, Steinrötel",
            "Bergfink-Buchfink (Other: Flightcall)": "Bergfink, Buchfink",
            "Amsel-Misteldrossel (Song)": "Amsel, Misteldrossel",
            "Fitis-Gartenrotschwanz (Ruf)": "Fitis, Gartenrotschwanz"
        }

        # Zuordnung des passenden Radiobutton-Wertes
        record_type_mapping = {
            "Eisvogel-Heckenbraunelle (Call)": "Call",
            "Zippammer-Zaunammer (Call)": "Call",
            "Blaumerle-Steinrötel (Song)": "Song",
            "Bergfink-Buchfink (Other: Flightcall)": "Other",
            "Amsel-Misteldrossel (Song)": "Song",
            "Fitis-Gartenrotschwanz (Ruf)": "Call"
        }

        # Mapping für die Combobox-Werte, falls "Other" gewählt wird
        combobox_mapping = {
            "Bergfink-Buchfink (Other: Flightcall)": "Flight call"
        }

        ### **1. Setze zuerst das Entry-Feld**
        species_list_entry.delete(0, tk.END)
        if selection in similar_species:
            species_list_entry.insert(0, similar_species[selection])

        ### **2. Setze den passenden Radiobutton**
        if selection in record_type_mapping:
            record_type.set(record_type_mapping[selection])

        ### **3. Falls "Other" gewählt wurde, überprüfe die Combobox**
        if selection in combobox_mapping:
            custom_record_type.set(combobox_mapping[selection])  # Setze Combobox-Wert
            other_combobox.pack(side=LEFT, padx=10)  # Zeige die Combobox an
        else:
            custom_record_type.set("Bitte auswählen")  # Standardwert setzen
            other_combobox.pack_forget()  # Combobox verstecken

    # Menubutton für die spezifischen Listen
    similar_list = tb.Menubutton(choose_species_frame, text="Verwechselbare Arten", bootstyle="success-outline")
    similar_list.grid(row=1, column=2, padx=10, pady=10, sticky="nsew")

    # Menü mit Radiobuttons erstellen
    inside_similar_list_menu = tk.Menu(similar_list, tearoff=0)

    # Paare zur Auswahl hinzufügen
    similars = [
        "Amsel-Misteldrossel (Song)",
        "Blaumerle-Steinrötel (Song)",
        "Bergfink-Buchfink (Other: Flightcall)",
        "Eisvogel-Heckenbraunelle (Call)",
        "Fitis-Gartenrotschwanz (Ruf)",
        "Zippammer-Zaunammer (Call)"
    ]

    # Menüeinträge mit Radiobuttons
    for similar in similars:
        inside_similar_list_menu.add_radiobutton(label=similar, variable=item_var, value=similar, command=set_species_list_similar)

    similar_list["menu"] = inside_similar_list_menu

    #Frame für Spektro/Bild
    visual_frame = tb.Frame(inner)
    visual_frame.pack(pady=15)

    # Checkbox für Spektrogramm
    var_spectro = IntVar()
    spectro_check = tb.Checkbutton(visual_frame, bootstyle="success-round-toggle", text="Spektrogramm anzeigen",
                                   variable=var_spectro, onvalue=1, offvalue=0)
    spectro_check.pack(side=LEFT, padx=10, pady=10)

    # Checkbox für Bild
    var_image = IntVar()
    image_check = tb.Checkbutton(visual_frame, bootstyle="success-round-toggle", text="Bild anzeigen",
                                 variable=var_image, onvalue=1, offvalue=0)
    image_check.pack(side=LEFT, padx=40, pady=10)

    # Radiobuttons für Aufnahmetyp (gemeinsame Variable=record_type)
    # Container-Frame für Radiobuttons und Combobox
    radio_frame = tb.Labelframe(inner, bootstyle="success",text="Audiotyp wählen")
    radio_frame.pack(pady=10, fill=BOTH, expand=YES)
    radio_frame.grid_columnconfigure(0, weight=1)
    radio_frame.grid_columnconfigure(1, weight=1)
    radio_frame.grid_columnconfigure(2, weight=1)

    record_type = StringVar(value="All_type")  # Standard: Alle

    # Radiobuttons
    all_radio = tb.Radiobutton(radio_frame, bootstyle="success",
                                text="Alle üben",
                                variable=record_type,
                                value="All_type")
    all_radio.grid(row=0, column=0, padx=(1,10), pady=10)

    call_radio = tb.Radiobutton(radio_frame, bootstyle="success",
                                text="Call üben",
                                variable=record_type,
                                value="Call")
    call_radio.grid(row=0, column=1, padx=10, pady=10)

    song_radio = tb.Radiobutton(radio_frame, bootstyle="success",
                                text="Song üben",
                                variable=record_type,
                                value="Song")
    song_radio.grid(row=0, column=2, padx=10, pady=10)

    other_radio = tb.Radiobutton(radio_frame, bootstyle="success",
                                 text="Specific Sound-Typ",
                                 variable=record_type,
                                 value="Other")
    other_radio.grid(row=1, column=0, padx=(55,5), pady=(20,10))

    # Combobox – zunächst ausgeblendet
    custom_record_type = StringVar(value="")  # Diese Variable speichert den benutzerdefinierten Wert
    other_combobox = tb.Combobox(radio_frame, bootstyle="success", textvariable=custom_record_type)
    other_combobox["values"] = ["Alarm call", "Begging call", "Drumming", "Female song", "Flight call", "Imitation", "Subsong"]
    other_combobox.set("Bitte auswählen")
    other_combobox['state'] = 'readonly'
    other_combobox.grid_forget()
    #other_combobox.pack(side=LEFT, padx=10) #Wenn nicht ausgeblendet werden soll (pack_forget weg und der ganze Callback)

    # Callback, der die Combobox ein- oder ausblendet, je nachdem, ob "Other" gewählt ist.
    def on_record_type_change(*args):
        if record_type.get() == "Other":
            other_combobox.grid(row=1, column=1, padx=5, pady=10)  # anzeigen
        else:
            other_combobox.grid_forget()  # verstecken

    record_type.trace("w", on_record_type_change)

    # Callback, der auf eine Auswahl in der Combobox reagiert
    def on_other_selected(event):
        print("Custom sound type ausgewählt:", custom_record_type.get())

    other_combobox.bind("<<ComboboxSelected>>", on_other_selected)

    #Sex/Lifestage festlegen
    # Callback, der die Combobox ein- oder ausblendet, je nachdem, ob "Other" gewählt ist.
    def on_sex_stage_change(*args):
        if sex_stage_var.get() == 1:
            selected_sex.grid(row=2, column=1, padx=5, pady=10)  # anzeigen
            selected_lifestage.grid(row=2, column=2, padx=5, pady=20)
        else:
            selected_sex.grid_forget()  # verstecken
            selected_lifestage.grid_forget()

    sex_stage_var = IntVar()
    sex_stage_check = tb.Checkbutton(radio_frame, bootstyle="success-round-toggle",
                               text="Specify sex/lifestage", variable=sex_stage_var, onvalue=1, offvalue=0,  command=on_sex_stage_change)
    sex_stage_check.grid(row=2, column=0, padx=(75,5), pady=30)


    #Combobutton für Geschlecht und Lifestage
    sex_type = StringVar(value="")
    sex = ["All sex", "Male", "Female"]
    selected_sex = tb.Combobox(radio_frame, bootstyle="success", values=sex, textvariable=sex_type)
    selected_sex['state'] = 'readonly'
    selected_sex.set("All sex")
    selected_sex.grid(row=2, column=1, padx=5, pady=10)
    selected_sex.grid_forget()

    lifestage_type = StringVar(value="")
    lifestage = ["All lifestage", "Adult", "Juvenile", "Nestling"]
    selected_lifestage = tb.Combobox(radio_frame, bootstyle="success", value=lifestage, textvariable=lifestage_type)
    selected_lifestage['state'] = 'readonly'
    selected_lifestage.set("All lifestage")
    selected_lifestage.grid(row=2, column=2, padx=5, pady=20)
    selected_lifestage.grid_forget()

    def save_and_start():
        # Falls "Other" gewählt ist, überschreibe record_type mit dem aktuellen Wert der Combobox
        if record_type.get() == "Other":
            new_value = other_combobox.get() # Hier rufen wir den aktuell in der Combobox eingegebenen Text ab
            if new_value == "Bitte auswählen":  # Falls der Wert "Bitte auswählen" ist, ersetze ihn mit einem leeren String
                new_value = ""
            record_type.set(new_value)
            print("record_type überschrieben mit:", new_value)
        if record_type.get() == "All_type":
            record_type.set ("")
        if sex_type.get() == "All sex":
            sex_type.set ("")
        if lifestage_type.get() == "All lifestage":
            lifestage_type.set ("")
        species_list = species_list_entry.get()
        save_new_settings(species_list, var_spectro, var_image, record_type,sex_type, lifestage_type)
        settings_frame.pack_forget()  # Formular ausblenden


    save_button = tb.Button(settings_frame, text="Einstellungen speichern und Spiel starten", bootstyle="success",
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


def shuffle_settings():
    # Lade die vollständige Artenliste (deutsche Namen) direkt aus der CSV
    all_species = load_all_species_from_csv()
    if not all_species:
        print("Keine Arten gefunden!")
        return

    # Wähle zufällig 10 Arten aus
    species_list = random.sample(all_species, 10)

    # Setze Spectrogram und Image automatisch auf 1
    var_spectro = 1
    var_image = 1

    settings = {
        "species_list": ",".join(species_list),
        "spectrogram": var_spectro,
        "image": var_image,
        "record_type": "",
        "sex_type": "",
        "lifestage_type": ""
    }
    with open(settings_file, "w") as f:
        json.dump(settings, f)

    print("Shuffle Settings: Zufällig ausgewählte Arten:")
    print(species_list)

    # Starte das Spiel – gamestart erwartet nun ein settings-Dictionary
    gamestart(settings['species_list'])


# Buttons für Neue/Alte Einstellungen
b1 = tb.Checkbutton(button_frame, text="Neue Einstellungen", variable=toggle_var, bootstyle="success-outline-toolbutton", command=NewSet)
b1.pack(side=LEFT, padx=5, pady=10)

b2 = tb.Button(button_frame, text="Alte Einstellungen", bootstyle="success", command=load_old_settings)
b2.pack(side=LEFT, padx=5, pady=10)

b3 = tb.Button(button_frame, text="Shuffle 10 Arten", bootstyle="secondary-outline", command=shuffle_settings)
b3.pack(side=RIGHT, padx=5, pady=10)


# --- Spiel-Fenster mit integriertem Xenocanto-Quiz ---
def gamestart(species_list):
    # Die vom Nutzer eingegebene Liste (Komma-getrennt) – Elemente können in Deutsch, Wissenschaftlich oder Englisch sein
    Artenliste_input = [art.strip() for art in species_list.split(",") if art.strip()]

    # Lade die CSV mit den Artennamen (Spalten: Deutsch, Wissenschaftlich, Englisch)
    try:
        species_df = pd.read_csv(resource_path("Europ_Species_3.csv"))
    except Exception as e:
        print(f"Fehler beim Laden der CSV: {e}")
        return

    # Baue eine kanonische Artenliste (als wissenschaftliche Version) und eine Mapping-Datenstruktur:
    # canonical_species: key = wissenschaftlicher Name (in Lowercase), value = Dictionary mit allen Varianten
    # species_options: Liste der kanonischen (wissenschaftlichen) Namen
    canonical_species = {}
    species_options = []
    for art in Artenliste_input:
        mapping = lookup_species(art, species_df)
        if mapping:
            # Schlüssel kann z.B. der wissenschaftliche Name in Kleinbuchstaben sein:
            scient = mapping["Wissenschaftlich"].strip()
            scient_lower = scient.lower()
            canonical_species[scient_lower] = mapping
            species_options.append(scient_lower)
        else:
            print(f"Art '{art}' nicht in der CSV gefunden.")

    # Lade gespeicherte Einstellungen (z.B. Spektrogramm, Aufnahmetyp)
    try:
        with open(settings_file, "r") as f:
            settings = json.load(f)
    except Exception:
        settings = {"spectrogram": 1, "image": 1, "species_list": species_list}


    game_window = Toplevel(root)
    game_window.title("Vogelquiz Spiel")
    #game_window.geometry("1300x800") #falls man die Größe manuell definieren möchte
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
    audio_frame.pack(pady=10, fill=X, padx=50)

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
    game_window.info_button = tb.Button(audio_frame, text="©Recording", bootstyle="light-link")
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
    media_frame.pack(pady=5)
    # Label für das Vogelbild:
    image_label = tb.Label(media_frame)
    image_label.grid(row=0, column=0, padx=10)
    # Label für das Spektrogramm:
    sonogram_label = tb.Label(media_frame)
    sonogram_label.grid(row=0, column=0, padx=10)

    # Speichere die Labels als Attribute des Fensters, damit sie in anderen Funktionen zugänglich sind
    game_window.image_label = image_label
    game_window.sonogram_label = sonogram_label

    # Frame für Arten-Buttons
    art_frame = tb.Frame(game_window)
    art_frame.pack(pady=10, padx=100, fill="both", expand=True)
    art_frame.grid_columnconfigure(0, weight=1)
    art_frame.grid_columnconfigure(1, weight=1)
    art_frame.grid_columnconfigure(2, weight=1)
    art_frame.grid_columnconfigure(3, weight=1)
    art_frame.grid_columnconfigure(4, weight=1)
    art_frame.grid_columnconfigure(5, weight=1)
    art_frame.grid_columnconfigure(6, weight=1)
    art_frame.grid_columnconfigure(7, weight=1)
    art_frame.grid_columnconfigure(8, weight=1)
    art_frame.grid_columnconfigure(9, weight=1)
    art_frame.grid_columnconfigure(10, weight=1)


    feedback_label = tb.Label(game_window, text="", font=("Helvetica", 14))
    feedback_label.pack(pady=10)

    # Funktion zum Verstecken des Copyright-Buttons
    def hide_copyright_button():
        if hasattr(media_frame, "copyright_button"):
            media_frame.copyright_button.grid_remove()
            print("Copyright-Button wurde versteckt.")

    def update_tooltip_text(widget, new_text):
        """Aktualisiert den Tooltip-Text eines Widgets ohne es neu zu erstellen."""
        try:
            # Setze den neuen Text in der internen Variablen
            widget.tooltip.text = new_text
            # Falls das Tooltip-Objekt ein internes Label besitzt, aktualisiere auch dessen Text
            if hasattr(widget.tooltip, 'label'):
                widget.tooltip.label.config(text=new_text)
            widget.tooltip.update_idletasks()
            print("DEBUG: Tooltip text updated to:", new_text)
        except Exception as e:
            print("Error updating tooltip text:", e)

    def create_or_update_copyright_button(parent, image_data):
        """Erstellt oder aktualisiert den Copyright-Button und passt den Tooltip-Text an."""
        try:
            from bs4 import BeautifulSoup  # HTML-Tags entfernen

            # Neue Werte abrufen
            photo_author = image_data.get("author", "Unbekannter Autor")
            photo_license = image_data.get("license", "Unbekannte Lizenz")
            # Entferne HTML-Tags (z. B. <a href=...>)
            photo_author = BeautifulSoup(photo_author, "html.parser").text
            tooltip_text = f"Foto von: {photo_author}\nLizenz: {photo_license}"
            print("DEBUG: Neuer Tooltip-Text:", tooltip_text)

            if hasattr(parent, "copyright_button"):
                # Aktualisiere den Tooltip-Text ohne den Tooltip neu zu erstellen:
                update_tooltip_text(parent.copyright_button, tooltip_text)
                # Stelle sicher, dass der Button sichtbar ist:
                parent.copyright_button.grid(row=1, column=0, padx=5, pady=2, sticky="w")
                print("DEBUG: Tooltip aktualisiert.")
            else:
                # Neuen Button und Tooltip erstellen
                parent.copyright_button = tb.Button(parent, text="© Bild", bootstyle="light-link")
                parent.copyright_button.grid(row=1, column=0, padx=5, pady=2, sticky="w")
                parent.copyright_button.tooltip = ToolTip(
                    parent.copyright_button,
                    text=tooltip_text,
                    bootstyle=(LIGHT, INVERSE)
                )
                print("DEBUG: Neuer Button mit Tooltip erstellt:", tooltip_text)

        except Exception as e:
            print("Error in updating tooltip:", e)

    #Funktion zum Vergleich, Bild anezeigen und Freischalten von Next-Button nach Auswahl eine Art
    def select_species(selected_key):
        # Stoppe laufende Audio und Progressbar:
        if current_round.get("audio_player"):
            current_round["audio_player"].stop()
        audio_progress.stop()

        #Deaktiviere die Antwortbuttons
        for btn in species_buttons:
            btn.config(state=DISABLED)

        # Deaktiviere den SKIP Button
        skip_button.config(state="disabled")

        # Aktiviere den NEXT Button
        next_button.config(state="normal")


        species = current_round["species"]
        if species not in game_window.species_stats:
            game_window.species_stats[species] = {"correct": 0, "wrong": 0}

        # Ermittle, in welcher Sprache die korrekte Art angezeigt werden soll.
        # Das wurde in lookup_species unter "display_language" gespeichert.
        display_language = canonical_species[species].get("display_language", "Deutsch")

        # Hole den angezeigten Text für die korrekte Art und für die ausgewählte Art
        correct_text = canonical_species[species][display_language]
        selected_text = canonical_species[selected_key][display_language]

        # fülle finale Matrix mit werten je nach Auswahl
        print("Korrekt ist:", correct_text)
        print("Ausgewählt wurde:", selected_text)
        global final_stats_matrix  # Ensure we refer to the global variable
        final_stats_matrix.loc[correct_text, selected_text] += 1
        print(final_stats_matrix)

        # Vergleiche diese Texte case-insensitiv
        if selected_text.strip().lower() == correct_text.strip().lower():
            feedback_label.config(text="Richtig!")
            game_window.korrekte_antworten += 1
            game_window.species_stats[species]["correct"] += 1
        else:
            # Hier kannst du z.B. immer noch den deutschen Namen anzeigen,
            # oder du verwendest den korrekten Text in der gewählten Sprache:
            feedback_label.config(text=f"Falsch! Richtig war: {correct_text}")
            game_window.falsche_antworten += 1
            game_window.species_stats[species]["wrong"] += 1



        # Bild anzeigen, falls aktiviert
        if settings.get("image") == 1:
            sonogram_label.config(image="") # Spektrogram rauslöschen
            try:
                latin_name = canonical_species[species]["Wissenschaftlich"]
                image_data = fetch_bird_image_from_commons(latin_name)  # Holt Bild & Metadaten
                photo = image_data.get("photo")
                # Bildinfo aktualisieren
                create_or_update_copyright_button(media_frame, image_data)

                if photo:
                    game_window.image_label.config(image=photo)
                    game_window.image_label.image = photo  # Referenz speichern
                    print("Bild wurde erfolgreich gesetzt.")  # Debugging


                    # Falls der Button zuvor versteckt war, wieder anzeigen
                    if hasattr(media_frame, "copyright_button"):
                        media_frame.copyright_button.grid()

                else:
                    print(f"No Wikimedia image found for '{latin_name}'.")
                    if hasattr(media_frame, "copyright_button"):
                        media_frame.copyright_button.grid_remove()  # Button verstecken, falls kein Bild

            except Exception as e:
                print(f"Error fetching Wikimedia image for {species}: {e}")



    # Erstelle für jede Art einen Button – als Anzeige nutzen wir sie Sprache des Species_list
    species_buttons = []
    row = 0
    col = 0

    display_names = []  # Collect display names
    for scient in species_options:
        # Determine the display language for the species name
        display_language = canonical_species[scient].get("display_language", "Deutsch")
        display_name = canonical_species[scient][display_language]
        display_names.append(display_name)

        # Debug output
        btn = tb.Button(
            art_frame,
            text=display_name,
            bootstyle="success-outline-toolbutton",
            command=lambda current=scient: select_species(current)
        )
        btn.grid(row=row, column=col, padx=1, pady=10)
        species_buttons.append(btn)

        col += 1
        if col == 10:
            col = 0
            row += 1

    # Create and store the matrix globally as a Pandas DataFrame with labeled rows and columns
    global final_stats_matrix  # Ensure we refer to the global variable
    final_stats_matrix = pd.DataFrame(
        np.zeros((len(display_names), len(display_names))),
        index=display_names,
        columns=display_names
    )

    # Variable, in der wir Daten der aktuellen Runde speichern
    current_round = {"species": None, "recording": None, "audio_player": None}
    game_window.current_round = current_round  # Speichern im Fenster, damit end_game darauf zugreifen kann

    # --- Prefetch-Funktion ---
    def prefetch_next_round():
        def load_next():
            # Wähle zufällig eine Art aus der kanonischen Liste
            next_species = random.choice(species_options)
            next_correct_scient =  canonical_species[next_species]["Wissenschaftlich"]
            print(next_correct_scient)
            # Lade das Recording für die nächste Runde
            rec_data = get_random_recording(
                next_correct_scient,
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
        correct_scient = canonical_species[current_species]["Wissenschaftlich"]

        # Spinner (indeterminate Progressbar) einblenden
        # Erstelle den Container im game_window – damit alle Kinder gemeinsam verwaltet werden
        game_window.loading_frame = tk.Frame(game_window)
        game_window.loading_frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        spinner = AnimatedGIF(game_window.loading_frame, resource_path("logo2.gif"), delay=100)
        spinner.place(relx=0, rely=0, relwidth=1, relheight=1)

        loading_label = tk.Label(game_window.loading_frame,
                                     text="Neue Audios werden geladen...",
                                     font=("Helvetica", 16),
                                     bg="#ffffff", fg="#000000")
        loading_label.place(relx=0.5, rely=0.5, anchor="center")

        def load_recording():
            rec_local = get_random_recording(
                correct_scient,
                settings.get("record_type", "Call"),
                settings.get("sex_type", ""),
                settings.get("lifestage_type", "")
            )

            #Hier werden die Bilder geladen und lokal gespeichert
            print(settings.get("image"))
            if settings.get("image") == 1:
                cache_bird_images(canonical_species)

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
                    blank_button = tb.Button(media_frame, bootstyle="light-link") #Placeholder, damit Button nicht springen
                    blank_button.grid(row=1, column=0, padx=5, pady=2, sticky="w")
                else:
                    sonogram_label.config(image="")

                if settings.get("spectrogram") == 0 and settings.get("image") == 0:
                    show_placeholder(sonogram_label)

                #Aktualisiere den Tooltip mit den kombinierten Infos:
                info_text = current_round["recording"].get("copyright_info", "Keine Info verfügbar")
                update_info_tooltip(game_window.info_button, info_text)

            game_window.after(0, lambda: update_ui(rec_local))

        threading.Thread(target=load_recording, daemon=True).start()


        # Starte das Prefetching für die nächste Runde
        prefetch_next_round()


    # --- Angepasste next_round() ---
    def next_round():
        hide_copyright_button()  # Button ausblenden, bevor das nächste Bild kommt

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

        # Aktiviere den SKIP Button
        skip_button.config(state="normal")

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

        if settings.get("spectrogram") == 0 and settings.get("image") == 0: #Placeholder einbauen in Media Frame
            show_placeholder(sonogram_label)

        species = current_round["species"]


    def skip_round():
        if current_round["audio_player"]:
            current_round["audio_player"].stop()

        species = current_round["species"]
        if species not in game_window.species_stats:
            game_window.species_stats[species] = {"correct": 0, "wrong": 0}

        # Ermittle, in welcher Sprache der eingegebene Name gefunden wurde
        display_language = canonical_species[species].get("display_language", "Deutsch")
        correct_text = canonical_species[species][display_language]

        feedback_label.config(text=f"Übersprungen! Richtig war: {correct_text}")

        # Bild anzeigen, falls aktiviert
        if settings.get("image") == 1:
            sonogram_label.config(image="")  # Spektrogram rauslöschen
            try:
                latin_name = canonical_species[species]["Wissenschaftlich"]
                image_data = fetch_bird_image_from_commons(latin_name)  # Holt Bild & Metadaten
                photo = image_data.get("photo")
                # Bildinfo aktualisieren
                create_or_update_copyright_button(media_frame, image_data)

                if photo:
                    game_window.image_label.config(image=photo)
                    game_window.image_label.image = photo  # Referenz speichern
                    print("Bild wurde erfolgreich gesetzt.")  # Debugging

                    # Falls der Button zuvor versteckt war, wieder anzeigen
                    if hasattr(media_frame, "copyright_button"):
                        media_frame.copyright_button.grid()

                else:
                    print(f"No Wikimedia image found for '{latin_name}'.")
                    if hasattr(media_frame, "copyright_button"):
                        media_frame.copyright_button.grid_remove()  # Button verstecken, falls kein Bild

            except Exception as e:
                print(f"Error fetching Wikimedia image for {species}: {e}")

        if settings.get("spectrogram") == 0 and settings.get("image") == 0: #Placeholder einbauen in Media Frame
            show_placeholder(sonogram_label)

        for btn in species_buttons:
            btn.config(state=DISABLED)

        audio_progress.stop()

        next_button.config(state="normal")

    # Frame für Steuerungs-Buttons (SKIP, NEXT)
    control_frame = tb.Frame(game_window)
    control_frame.pack(pady=10, fill=X, padx=50)
    control_frame.grid_columnconfigure(0, weight=1)
    control_frame.grid_columnconfigure(1, weight=1)

    skip_button = tb.Button(control_frame, text="SKIP", bootstyle="success-outline", command=skip_round)
    skip_button.grid(row=0, column=0, padx=10, sticky="ew")

    next_button = tb.Button(control_frame, text="NEXT", state="disabled", bootstyle="success", command=next_round)
    next_button.grid(row=0, column=1, padx=10, sticky="ew")

    #Frame für end_back_button
    end_back_frame = tb.Frame(game_window)
    end_back_frame.pack(pady=20, fill=X, padx=600)


    # Back to Settings
    backset_button = tb.Button(end_back_frame, text="Zurück zu Einstellungen", bootstyle="secondary",
                               command=lambda: back_to_settings(game_window))
    backset_button.pack(side=LEFT, padx=5, pady=10)

    # Der End-Game-Button stoppt zusätzlich das laufende Audio
    endgame_button = tb.Button(end_back_frame, text="Spiel beenden", bootstyle="secondary",
                               command=lambda: end_game(game_window))
    endgame_button.pack (side=RIGHT, padx=5, pady=10)


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

    #Erstelle das Matrix-Bild bevor es geladen wird
    plot_final_stats_matrix(final_stats_matrix, save_path="matrix_plot.png")

    # Neues Fenster für die Gesamtergebnisse
    results_window = tb.Toplevel(root)
    results_window.title("Gesamtergebnisse")
    results_window.state("zoomed")


    header_label = tb.Label(
        results_window,
        text="Gesamtstatistik",
        font=("Helvetica", 16, "bold")
    )
    header_label.pack(pady=10)  # Überschrift mit Abstand nach unten

    # Erstelle ein Frame für Gesamt Label und Meter
    total_frame = tb.Frame(results_window)
    total_frame.pack(pady=20)

    # Gesamtübersicht schriftlich
    total_score_label = tb.Label(
        total_frame,
        text=(f"Richtige Antworten: {correct_total}\n"
              f"Falsche Antworten: {wrong_total}"),
        font=("Helvetica", 10),
        anchor="w"
    )
    total_score_label.pack(side="left", padx=20)

    total_attempts_gesamt = correct_total + wrong_total
    percentage_gesamt = round((correct_total / total_attempts_gesamt) * 100) if total_attempts_gesamt > 0 else 0

    meter_gesamt = tb.Meter(
        total_frame,
        bootstyle="warning",
        amountused=percentage_gesamt,
        amounttotal=100,
        metersize=150,
        textright="%",
        subtext="Gesamt Richtig"
    )
    meter_gesamt.pack(side="right", padx=20)

    # **Notebook mit Tabs erstellen**
    Visualisierung_tabs = tb.Notebook(results_window, bootstyle="dark")
    Visualisierung_tabs.pack(pady=10, fill="both", expand=True)


    # **Tab 1: Info Text**
    tab_info = tb.Frame(Visualisierung_tabs)
    Visualisierung_tabs.add(tab_info, text="Informationen")

    # Jetzt das Bild in den Tab laden
    tab_info_label = tb.Label(tab_info, text="Gucke doch mal an, wie gut du warst!")
    tab_info_label.pack(pady=20)

    # Tab 2: Prozent pro Art
    tab_prozent = tb.Frame(Visualisierung_tabs)
    Visualisierung_tabs.add(tab_prozent, text="Prozent pro Art")

    # Erstelle einen Canvas, der als Container für den inneren Frame dient.
    # Hier gibst du dem Canvas oben und unten etwas mehr Padding, damit der Inhalt nicht direkt am Rand klebt.
    canvas = tk.Canvas(tab_prozent, borderwidth=0, highlightthickness=0)
    canvas.pack(fill="both", expand=True, padx=10, pady=(80, 20))

    # Erstelle einen horizontalen Scrollbar mit dunklem Bootstyle (verwende tb.Scrollbar statt tk.Scrollbar)
    h_scrollbar = tb.Scrollbar(tab_prozent, orient="horizontal", command=canvas.xview, bootstyle="light")
    h_scrollbar.pack(fill="x", side="bottom")
    canvas.configure(xscrollcommand=h_scrollbar.set)

    # Erstelle einen inneren Frame, der im Canvas platziert wird.
    species_frame = tb.Frame(canvas)
    canvas.create_window((0, 0), window=species_frame, anchor="nw")

    # Aktualisiere die Scrollregion, wenn sich die Größe des species_frame ändert.
    def on_frame_configure(event):
        canvas.configure(scrollregion=canvas.bbox("all"))

    species_frame.bind("<Configure>", on_frame_configure)

    # Erstelle die Meter-Widgets in einer einzigen horizontalen Reihe.
    meter_widgets = []
    species_list = sorted(game_window.canonical_species.items(), key=lambda x: x[1]["Deutsch"])

    for species_lower, mapping in species_list:
        stats = game_window.species_stats.get(species_lower, {"correct": 0, "wrong": 0})
        total_attempts = stats["correct"] + stats["wrong"]
        percentage = round((stats["correct"] / total_attempts) * 100) if total_attempts > 0 else 0
        label_text = f"{stats['correct']} korrekt / {total_attempts} Audios"
        stats_label = tb.Label(species_frame, text=label_text, font=("Arial", 8))
        meter = tb.Meter(
            species_frame,
            bootstyle="success",
            amountused=percentage,
            amounttotal=100,
            metersize=150,
            textright="%",
            subtext=mapping["Deutsch"]
        )
        meter_widgets.append((stats_label, meter))

    # Platziere alle Meter-Widgets in einer einzigen Zeile:
    def arrange_meters():
        for i, (s_label, meter) in enumerate(meter_widgets):
            # Mehr Padding oben und unten, damit die Meter etwas mittiger erscheinen.
            s_label.grid(row=0, column=i, padx=10, pady=(20, 0), sticky="w")
            meter.grid(row=1, column=i, padx=10, pady=(0, 20), sticky="nsew")

    arrange_meters()

    # **Tab 3: Confusion-Matrix**
    tab_matrix = tb.Frame(Visualisierung_tabs)
    Visualisierung_tabs.add(tab_matrix, text="Confusion-Matrix")

    # Erstelle einen übergeordneten Layout-Frame in tab_matrix, der den gesamten Platz füllt
    layout_frame = tb.Frame(tab_matrix)
    layout_frame.pack(fill="both", expand=True, padx=10, pady=10)

    # Konfiguriere 2 Spalten und 1 Zeile; die Zeile soll sich vertikal ausdehnen
    layout_frame.columnconfigure(0, weight=1)
    layout_frame.columnconfigure(1, weight=1)
    layout_frame.rowconfigure(0, weight=1)

    # --------------------------
    # Links: Matrix-Bild-Container
    # --------------------------
    img_container = tb.Frame(layout_frame)
    img_container.grid(row=0, column=0, sticky="nsew", padx=(100, 5), pady=5)
    img_container.columnconfigure(0, weight=1)
    img_container.rowconfigure(0, weight=1)
    # Lade das Matrix-Bild in diesen Container
    load_matrix_image(img_container)

    # --------------------------
    # Rechts: Container für Beschreibungstext und Vollbild-Button
    # --------------------------
    right_container = tb.Frame(layout_frame)
    right_container.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
    right_container.columnconfigure(0, weight=1)
    # Die erste Zeile (Beschreibung) soll den verfügbaren Platz einnehmen:
    right_container.rowconfigure(0, weight=1)
    # Die zweite Zeile (Button) soll nicht expandieren:
    right_container.rowconfigure(1, weight=0)

    # Beschreibungstext im oberen Bereich
    desc_container = tb.Frame(right_container)
    desc_container.grid(row=0, column=0, sticky="nsew", padx=(5, 15), pady=5)
    desc_label = tb.Label(desc_container, text="Hier steht der Beschreibungstext für die Matrix", anchor="center")
    desc_label.pack(fill="both", expand=True)

    # Vollbild-Button im unteren Bereich
    btn_container = tb.Frame(right_container)
    btn_container.grid(row=1, column=0, sticky="nsew", padx=(5, 15), pady=5)
    full_button = tb.Button(btn_container, text="Vollbild", bootstyle="success",
                            command=lambda: open_fullscreen_image(Image.open("matrix_plot.png")))
    full_button.pack()

    # **Schließen-Button**
    close_button = tb.Button(results_window, text="Fenster schließen", command=results_window.destroy, bootstyle="success")
    close_button.pack(pady=20, anchor="center")

    # Game_Window automatisch schließen
    game_window.destroy()




root.mainloop()
