import sys
import os
import pandas as pd
import folium
import json
import io
import html
import time
import csv
import requests
import logging
import traceback
import re
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2
from urllib.parse import parse_qs

from PyQt6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QWidget,
                             QMessageBox, QSplitter, QListWidget, QListWidgetItem,
                             QLabel, QRadioButton, QButtonGroup, QScrollArea,
                             QFileDialog, QProgressDialog, QDialog, QFormLayout,
                             QSpinBox, QLineEdit, QDialogButtonBox, QComboBox)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEnginePage
from PyQt6.QtCore import QUrl, Qt, QSettings, QCoreApplication
from PyQt6.QtGui import QPixmap, QImage, QAction
from PIL import Image, ImageOps, ExifTags

# --- Konstanten & Versionierung ---
APP_VERSION = "2.1.8"
SUPPORTED_EXTENSIONS = ('.jpg', '.jpeg', '.tif', '.tiff', '.heic', '.heif')
CSV_CACHE_FILENAME = ".exif_tool_cache.csv"
APP_CACHE_FILENAME = "combined_geodata.parquet"
MANIFEST_FILENAME = "cache_manifest.json"
CSV_FIELDNAMES = ['filepath', 'latitude', 'longitude', 'country', 'city', 'datetime_original']


# --- Logging-Konfiguration ---
def setup_logging():
    """Konfiguriert das Logging, um Fehler in eine Datei zu schreiben."""
    base_path = os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else sys.argv[0])
    log_file = os.path.join(base_path, 'error.log')
    
    if os.path.exists(log_file) and os.path.getsize(log_file) > 1024 * 1024: # 1 MB
        os.rename(log_file, log_file + '.old')

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - In %(funcName)s: %(message)s',
        filemode='a',
        encoding='utf-8'
    )
    logging.getLogger('PIL').setLevel(logging.WARNING)
    handler = logging.FileHandler(log_file, 'a', 'utf-8')
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - In %(funcName)s: %(message)s')
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.DEBUG)


def uncaught_exception_handler(exc_type, exc_value, exc_traceback):
    """Fängt unbehandelte Ausnahmen ab, loggt sie und zeigt eine Meldung an."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    logging.critical("Unbehandelte Ausnahme aufgetreten!", exc_info=(exc_type, exc_value, exc_traceback))
    
    error_message = (
        "Ein unerwarteter Fehler ist aufgetreten und das Programm muss beendet werden.\n\n"
        f"Bitte überprüfen Sie die Datei 'error.log' im Programmverzeichnis für technische Details.\n\n"
        f"Fehler: {exc_value}"
    )
    QMessageBox.critical(None, "Kritischer Fehler", error_message)


# --- Hilfsfunktionen ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = radians(lat1), radians(lat2)
    delta_phi = radians(lat2 - lat1)
    delta_lambda = radians(lon2 - lon1)
    a = sin(delta_phi / 2)**2 + cos(phi1) * cos(phi2) * sin(delta_lambda / 2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

def extract_exif_data(image_path):
    try:
        img = Image.open(image_path)
        exif_data = img._getexif()
        if not exif_data:
            return {'lat': None, 'lon': None, 'datetime': None}

        datetime_original = None
        for tag, value in exif_data.items():
            decoded = ExifTags.TAGS.get(tag, tag)
            if decoded == "DateTimeOriginal":
                datetime_original = value
                break

        gps_info = {}
        for tag, value in exif_data.items():
            decoded = ExifTags.TAGS.get(tag, tag)
            if decoded == "GPSInfo":
                for t in value:
                    sub_decoded = ExifTags.GPSTAGS.get(t, t)
                    gps_info[sub_decoded] = value[t]
                break
        
        lat, lon = None, None
        if all(k in gps_info for k in ['GPSLatitude', 'GPSLatitudeRef', 'GPSLongitude', 'GPSLongitudeRef']):
            def convert_dms_to_decimal(dms, ref):
                degrees = dms[0]; minutes = dms[1] / 60.0; seconds = dms[2] / 3600.0
                dec = degrees + minutes + seconds
                if ref in ['S', 'W']: dec = -dec
                return dec
            lat = convert_dms_to_decimal(gps_info['GPSLatitude'], gps_info['GPSLatitudeRef'])
            lon = convert_dms_to_decimal(gps_info['GPSLongitude'], gps_info['GPSLongitudeRef'])
        
        return {'lat': lat, 'lon': lon, 'datetime': datetime_original}
    except Exception as e:
        logging.warning(f"Konnte EXIF-Daten für {image_path} nicht lesen: {e}")
        return {'lat': None, 'lon': None, 'datetime': None}

def fetch_location_from_nominatim(latitude, longitude, user_agent):
    headers = {'User-Agent': user_agent}
    url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={latitude}&lon={longitude}&addressdetails=1&accept-language=de,en"
    country, city = None, None
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        address = data.get('address', {})
        if address:
            country = address.get('country')
            city_candidates = ['city', 'town', 'village', 'hamlet', 'municipality', 'county', 'state_district']
            for key in city_candidates:
                if address.get(key):
                    city = address.get(key)
                    break
            if not city:
                city = address.get('state', "Unbekannter Ort")
    except Exception as e:
        logging.error(f"Fehler bei Nominatim-Anfrage für {latitude},{longitude}: {e}")
    return country, city

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        layout = QFormLayout(self)
        
        self.grouping_mode = QComboBox()
        self.grouping_mode.addItems(["Ordner", "Jahr", "Jahr & Monat"])
        layout.addRow("Gruppieren nach:", self.grouping_mode)

        self.cluster_distance = QSpinBox()
        self.cluster_distance.setRange(50, 10000)
        self.cluster_distance.setSingleStep(50)
        self.cluster_distance.setSuffix(" m")
        layout.addRow("Cluster-Distanz:", self.cluster_distance)
        
        self.user_agent = QLineEdit()
        layout.addRow("Nominatim User-Agent:", self.user_agent)
        
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addRow(self.buttons)

class CustomWebEnginePage(QWebEnginePage):
    def __init__(self, parent_window=None):
        super().__init__(parent_window)
        self._main_window = parent_window

    def acceptNavigationRequest(self, url, _type, isMainFrame):
        if url.scheme() == 'app' and url.host() == 'show_cluster' and 'id' in parse_qs(url.query()):
            cluster_id = parse_qs(url.query())['id'][0]
            if self._main_window:
                self._main_window.display_photos_for_cluster(cluster_id)
            return False
        return super().acceptNavigationRequest(url, _type, isMainFrame)

class PhotoMapApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self._load_settings()

        self.setWindowTitle(f"Photo Map Viewer v{APP_VERSION}")
        self.setGeometry(100, 100, 1600, 900)

        self.photo_root_path = None
        self.clusters_data = []
        self.master_df = pd.DataFrame()
        self.nominatim_api_cache = {}

        self._create_menu_bar()
        self._create_ui()
        self._load_window_state()
        self.clear_all_views(is_startup=True)

    def _load_settings(self):
        self.settings = QSettings()
        self.grouping_mode = self.settings.value("groupingMode", "Ordner", type=str)
        self.cluster_distance = self.settings.value("clusterDistance", 1000, type=int)
        self.nominatim_user_agent = self.settings.value("nominatimUserAgent", f"PhotoMapTool/{APP_VERSION} (DesktopApp)")

    def _load_window_state(self):
        try:
            if self.settings.value("geometry"):
                self.restoreGeometry(self.settings.value("geometry"))
            if self.settings.value("splitterState"):
                self.main_splitter.restoreState(self.settings.value("splitterState"))
        except Exception as e:
            logging.warning(f"Fensterstatus konnte nicht geladen werden: {e}")

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitterState", self.main_splitter.saveState())
        super().closeEvent(event)

    def _create_menu_bar(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("Datei")
        
        load_root_action = QAction("Foto-Hauptordner laden...", self)
        load_root_action.triggered.connect(self.select_and_load_root_folder)
        file_menu.addAction(load_root_action)

        analyze_action = QAction("Unterordner analysieren...", self)
        analyze_action.triggered.connect(self.run_manual_exif_analysis)
        file_menu.addAction(analyze_action)
        
        rebuild_cache_action = QAction("Gesamt-Cache neu erstellen", self)
        rebuild_cache_action.triggered.connect(self.force_rebuild_cache)
        file_menu.addAction(rebuild_cache_action)

        file_menu.addSeparator()
        exit_action = QAction("Beenden", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        tools_menu = menu_bar.addMenu("Extras")
        settings_action = QAction("Einstellungen...", self)
        settings_action.triggered.connect(self.open_settings_dialog)
        tools_menu.addAction(settings_action)

    def _create_ui(self):
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        top_layout = QVBoxLayout(self.main_widget)
        
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        
        self.folder_sidebar = QWidget()
        folder_layout = QVBoxLayout(self.folder_sidebar)
        self.folder_label = QLabel("Gruppierte Ansicht:")
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.radio_button_container = QWidget()
        self.radio_button_layout = QVBoxLayout(self.radio_button_container)
        self.radio_button_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.radio_button_container)
        self.folder_button_group = QButtonGroup(self)
        self.folder_button_group.setExclusive(True)
        self.folder_button_group.buttonClicked.connect(self.on_folder_selected)
        folder_layout.addWidget(self.folder_label)
        folder_layout.addWidget(self.scroll_area)
        self.main_splitter.addWidget(self.folder_sidebar)
        
        self.web_view = QWebEngineView()
        self.web_view.setPage(CustomWebEnginePage(self))
        self.main_splitter.addWidget(self.web_view)

        self.photo_sidebar = QWidget()
        photo_sidebar_layout = QVBoxLayout(self.photo_sidebar)
        self.sidebar_label = QLabel()
        self.photo_list_widget = QListWidget()
        self.photo_list_widget.itemClicked.connect(self.display_preview)
        self.photo_list_widget.itemDoubleClicked.connect(self.open_photo_from_sidebar)
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(200, 200)
        self.preview_label.setStyleSheet("border: 1px solid #555; background-color: #282828;")
        photo_sidebar_layout.addWidget(self.sidebar_label)
        photo_sidebar_layout.addWidget(self.photo_list_widget)
        photo_sidebar_layout.addWidget(self.preview_label)
        photo_sidebar_layout.setStretchFactor(self.photo_list_widget, 1)
        photo_sidebar_layout.setStretchFactor(self.preview_label, 1)
        self.main_splitter.addWidget(self.photo_sidebar)
        
        self.main_splitter.setStretchFactor(0, 1); self.main_splitter.setStretchFactor(1, 4); self.main_splitter.setStretchFactor(2, 2)
        top_layout.addWidget(self.main_splitter)

    def open_settings_dialog(self):
        dialog = SettingsDialog(self)
        dialog.grouping_mode.setCurrentText(self.grouping_mode)
        dialog.cluster_distance.setValue(self.cluster_distance)
        dialog.user_agent.setText(self.nominatim_user_agent)
        
        if dialog.exec():
            self.grouping_mode = dialog.grouping_mode.currentText()
            self.cluster_distance = dialog.cluster_distance.value()
            self.nominatim_user_agent = dialog.user_agent.text()
            self.settings.setValue("groupingMode", self.grouping_mode)
            self.settings.setValue("clusterDistance", self.cluster_distance)
            self.settings.setValue("nominatimUserAgent", self.nominatim_user_agent)
            QMessageBox.information(self, "Gespeichert", "Einstellungen wurden gespeichert und die Ansicht aktualisiert.")
            self.populate_folder_list()

    def select_and_load_root_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Foto-Hauptordner auswählen")
        if not folder_path: return
        
        self.photo_root_path = folder_path
        self.setWindowTitle(f"Photo Map Viewer v{APP_VERSION} - [{self.photo_root_path}]")
        
        self.check_and_update_folders()
        self.load_data_and_display_ui()

    def run_manual_exif_analysis(self):
        start_dir = self.photo_root_path if self.photo_root_path else ""
        folder_path = QFileDialog.getExistingDirectory(self, "Zu analysierenden Unterordner auswählen", start_dir)
        if folder_path:
            if self.photo_root_path and not folder_path.startswith(self.photo_root_path):
                QMessageBox.warning(self, "Falscher Ordner", "Bitte einen Ordner innerhalb des geladenen Hauptordners auswählen.")
                return
            
            self.process_image_folder(folder_path)
            
            if self.photo_root_path:
                self.load_data_and_display_ui()

    def force_rebuild_cache(self):
        if not self.photo_root_path:
            QMessageBox.warning(self, "Kein Ordner", "Bitte zuerst einen Foto-Hauptordner laden.")
            return

        reply = QMessageBox.question(self, "Cache neu erstellen?", 
                                     f"Soll der Gesamt-Cache ('{APP_CACHE_FILENAME}') wirklich neu erstellt werden? Dies kann je nach Anzahl der Fotos dauern.",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            cache_path = os.path.join(self.photo_root_path, APP_CACHE_FILENAME)
            manifest_path = os.path.join(self.photo_root_path, MANIFEST_FILENAME)
            try:
                if os.path.exists(cache_path): os.remove(cache_path)
                if os.path.exists(manifest_path): os.remove(manifest_path)
                QMessageBox.information(self, "Erfolgreich", "Cache wurde gelöscht und wird jetzt neu aufgebaut.")
                self.load_data_and_display_ui()
            except Exception as e:
                QMessageBox.critical(self, "Fehler", f"Cache konnte nicht gelöscht werden: {e}")
                logging.error("Fehler beim Löschen des Gesamt-Caches", exc_info=True)

    def check_and_update_folders(self):
        if not self.photo_root_path: return
        
        folders_to_update = self._find_folders_to_update()
        
        if not folders_to_update:
            return
            
        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Icon.Question)
        msg_box.setText("Analyse erforderlich")
        msg_box.setInformativeText(f"Es wurde(n) {len(folders_to_update)} Ordner mit neuen Fotos oder veralteten Daten gefunden. Sollen diese jetzt analysiert/aktualisiert werden?")
        msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg_box.setDefaultButton(QMessageBox.StandardButton.Yes)
        
        if msg_box.exec() == QMessageBox.StandardButton.Yes:
            for folder in folders_to_update:
                self.process_image_folder(folder)
    
    def _find_folders_to_update(self):
        folders_needing_update = []
        try:
            for item in os.listdir(self.photo_root_path):
                dir_path = os.path.join(self.photo_root_path, item)
                if os.path.isdir(dir_path):
                    try:
                        has_images = any(f.lower().endswith(SUPPORTED_EXTENSIONS) for f in os.listdir(dir_path) if os.path.isfile(os.path.join(dir_path, f)))
                        if not has_images: continue
                    except OSError:
                        continue 

                    csv_path = os.path.join(dir_path, CSV_CACHE_FILENAME)
                    if not os.path.exists(csv_path):
                        folders_needing_update.append(dir_path)
                    else:
                        try:
                            with open(csv_path, 'r', newline='', encoding='utf-8') as f:
                                reader = csv.reader(f)
                                header = next(reader, None)
                                if 'datetime_original' not in header:
                                    folders_needing_update.append(dir_path)
                        except Exception:
                            folders_needing_update.append(dir_path)
        except Exception as e:
            logging.error("Fehler beim Suchen nach zu aktualisierenden Ordnern", exc_info=True)
        return folders_needing_update

    def load_data_and_display_ui(self):
        if not self.photo_root_path:
            self.clear_all_views(is_startup=True)
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        
        try:
            cache_path = os.path.join(self.photo_root_path, APP_CACHE_FILENAME)
            manifest_path = os.path.join(self.photo_root_path, MANIFEST_FILENAME)
            
            found_csvs = { os.path.join(root, CSV_CACHE_FILENAME): os.path.getmtime(os.path.join(root, CSV_CACHE_FILENAME))
                          for root, _, files in os.walk(self.photo_root_path) if CSV_CACHE_FILENAME in files }
            
            rebuild_cache = True
            if os.path.exists(cache_path) and os.path.exists(manifest_path):
                try:
                    with open(manifest_path, 'r') as f: manifest_data = json.load(f)
                    if all(p in manifest_data and manifest_data[p] == mt for p, mt in found_csvs.items()) and \
                       all(p in found_csvs for p in manifest_data.keys()):
                        self.master_df = pd.read_parquet(cache_path)
                        rebuild_cache = False
                except Exception:
                    logging.warning("Manifest-Datei konnte nicht gelesen werden, Cache wird neu gebaut.", exc_info=True)

            if rebuild_cache:
                logging.info("Gesamt-Cache wird neu erstellt.")
                all_dfs = []
                for csv_path in found_csvs:
                    try:
                        df = pd.read_csv(csv_path, keep_default_na=False)
                        csv_dir = os.path.dirname(csv_path)
                        df['SourceFolder'] = os.path.relpath(csv_dir, self.photo_root_path)
                        df['filepath'] = df['filepath'].apply(lambda p: os.path.join(csv_dir, p))
                        all_dfs.append(df)
                    except Exception:
                        logging.error(f"Fehler beim Lesen der CSV-Datei: {csv_path}", exc_info=True)
                
                if all_dfs:
                    self.master_df = pd.concat(all_dfs, ignore_index=True)
                    # --- START of the fix ---
                    # Datentypen VOR dem Speichern bereinigen
                    if 'latitude' in self.master_df.columns:
                        self.master_df['latitude'] = pd.to_numeric(self.master_df['latitude'], errors='coerce')
                    if 'longitude' in self.master_df.columns:
                        self.master_df['longitude'] = pd.to_numeric(self.master_df['longitude'], errors='coerce')
                    if 'datetime_original' in self.master_df.columns:
                        self.master_df['datetime_original'] = pd.to_datetime(self.master_df['datetime_original'], errors='coerce', format='%Y:%m:%d %H:%M:%S')
                    
                    self.master_df.to_parquet(cache_path)
                    # --- END of the fix ---
                    with open(manifest_path, 'w') as f: json.dump(found_csvs, f)
                else:
                    self.master_df = pd.DataFrame()
            
            if not self.master_df.empty:
                # Sicherstellen, dass die Typen auch korrekt sind, wenn aus dem Cache geladen wird
                if 'latitude' in self.master_df.columns:
                    self.master_df['latitude'] = pd.to_numeric(self.master_df['latitude'], errors='coerce')
                if 'longitude' in self.master_df.columns:
                    self.master_df['longitude'] = pd.to_numeric(self.master_df['longitude'], errors='coerce')
                if 'datetime_original' in self.master_df.columns and not pd.api.types.is_datetime64_any_dtype(self.master_df['datetime_original']):
                     self.master_df['datetime_original'] = pd.to_datetime(self.master_df['datetime_original'], errors='coerce')

            self.populate_folder_list()
        
        except Exception as e:
            logging.critical("Kritischer Fehler beim Laden der Daten", exc_info=True)
            QMessageBox.critical(self, "Fehler beim Laden", f"Ein Fehler ist beim Laden der Daten aufgetreten. Details in 'error.log'.\n\n{e}")
            self.master_df = pd.DataFrame()
            self.populate_folder_list()
        finally:
            QApplication.restoreOverrideCursor()

    def populate_folder_list(self):
        try:
            for button in self.folder_button_group.buttons():
                self.folder_button_group.removeButton(button); button.deleteLater()

            if self.master_df.empty:
                self.folder_label.hide(); self.scroll_area.hide()
                return

            self.folder_label.show(); self.scroll_area.show()
            
            df_for_list = self.master_df.copy()
            
            group_counts = None
            if self.grouping_mode == "Ordner":
                group_counts = df_for_list.groupby('SourceFolder').size()
            else:
                if 'datetime_original' not in df_for_list.columns or df_for_list['datetime_original'].isnull().all():
                     QMessageBox.warning(self, "Fehlende Daten", "Für die Gruppierung nach Datum müssen die Ordner neu analysiert werden, um die Aufnahmedaten zu erfassen.")
                     group_counts = df_for_list.groupby('SourceFolder').size()
                else:
                    df_with_date = df_for_list.dropna(subset=['datetime_original']).copy()
                    
                    if self.grouping_mode == "Jahr":
                        df_with_date['group'] = df_with_date['SourceFolder'] + " / " + df_with_date['datetime_original'].dt.year.astype(int).astype(str)
                    elif self.grouping_mode == "Jahr & Monat":
                        df_with_date['group'] = df_with_date['SourceFolder'] + " / " + df_with_date['datetime_original'].dt.strftime('%Y-%m')
                    
                    group_counts = df_with_date.groupby('group').size()

            group_counts = group_counts.sort_index()

            for group_name, count in group_counts.items():
                label = f"{group_name} ({count})"
                radio_button = QRadioButton(label)
                self.radio_button_layout.addWidget(radio_button)
                self.folder_button_group.addButton(radio_button)
            
            if self.folder_button_group.buttons():
                self.folder_button_group.buttons()[0].setChecked(True)
                self.on_folder_selected(self.folder_button_group.buttons()[0])
            else:
                self.clear_all_views()
        except Exception as e:
            logging.critical("Fehler beim Erstellen der Ordnerliste", exc_info=True)
            QMessageBox.critical(self, "UI Fehler", f"Ein Fehler ist beim Erstellen der Ordnerliste aufgetreten. Details in 'error.log'.\n\n{e}")

    def on_folder_selected(self, selected_button):
        try:
            full_label = selected_button.text()
            virtual_folder = re.sub(r'\s\(\d+\)$', '', full_label)

            if not virtual_folder or self.master_df.empty:
                return

            df_to_display = self.master_df.copy()
            
            if self.grouping_mode == "Ordner":
                df_to_display = df_to_display[df_to_display['SourceFolder'] == virtual_folder]
            else:
                parts = virtual_folder.rsplit(" / ", 1)
                if len(parts) != 2:
                    logging.warning(f"Konnte den virtuellen Ordner nicht aufteilen: {virtual_folder}")
                    return
                
                source_folder, date_part = parts
                
                df_to_display = df_to_display[df_to_display['SourceFolder'] == source_folder]
                
                if self.grouping_mode == "Jahr":
                    df_to_display = df_to_display[df_to_display['datetime_original'].dt.year == int(date_part)]
                elif self.grouping_mode == "Jahr & Monat":
                    df_to_display = df_to_display[df_to_display['datetime_original'].dt.strftime('%Y-%m') == date_part]

            self.display_map_from_dataframe(df_to_display)
        except Exception as e:
            logging.error("Fehler bei der Auswahl einer Gruppe", exc_info=True)
            QMessageBox.warning(self, "Filter Fehler", f"Beim Filtern der Fotos ist ein Fehler aufgetreten. Details in 'error.log'.\n\n{e}")

    def display_map_from_dataframe(self, df):
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.sidebar_label.setText("Kein Cluster ausgewählt")
        self.photo_list_widget.clear()
        self.preview_label.clear(); self.preview_label.setText("")
        
        df_clean = df.copy().dropna(subset=['latitude', 'longitude', 'filepath'])
        if df_clean.empty:
            self.web_view.setHtml("<html><body>Keine Fotos mit GPS-Daten in dieser Gruppe gefunden.</body></html>")
            QApplication.restoreOverrideCursor(); return
        
        self._perform_clustering(df_clean)
        
        if not self.clusters_data:
            self.web_view.setHtml("<html><body>Keine Cluster gebildet.</body></html>")
            QApplication.restoreOverrideCursor(); return

        map_center = [self.clusters_data[0]['centroid_lat'], self.clusters_data[0]['centroid_lon']]
        m = folium.Map(location=map_center, zoom_start=10)

        for cluster in self.clusters_data:
            count_text = f"{cluster['photo_count']} Foto(s)"
            popup_html = f"<div style='font-family: sans-serif;'><a href='app://show_cluster?id={cluster['id']}' style='text-decoration:none; color:black;'>{html.escape(count_text)}</a></div>"
            folium.Marker(location=[cluster['centroid_lat'], cluster['centroid_lon']],
                          popup=folium.Popup(popup_html, max_width=300),
                          tooltip=count_text).add_to(m)

        data = io.BytesIO(); m.save(data, close_file=False)
        self.web_view.setHtml(data.getvalue().decode())
        QApplication.restoreOverrideCursor()

    def _perform_clustering(self, df):
        self.clusters_data.clear()
        processed_indices = set()
        df_reset = df.reset_index(drop=True)
        for i, point1 in df_reset.iterrows():
            if i in processed_indices: continue
            
            cluster_points = [{'filepath': point1['filepath'], 'latitude': point1['latitude'], 'longitude': point1['longitude']}]
            processed_indices.add(i)
            sum_lat, sum_lon = point1['latitude'], point1['longitude']
            
            for j, point2 in df_reset.iloc[i+1:].iterrows():
                if j in processed_indices: continue
                if haversine(point1['latitude'], point1['longitude'], point2['latitude'], point2['longitude']) <= self.cluster_distance:
                    cluster_points.append({'filepath': point2['filepath'], 'latitude': point2['latitude'], 'longitude': point2['longitude']})
                    processed_indices.add(j)
                    sum_lat += point2['latitude']; sum_lon += point2['longitude']
            
            count = len(cluster_points)
            self.clusters_data.append({ 'id': len(self.clusters_data), 'points': cluster_points,
                'centroid_lat': sum_lat / count, 'centroid_lon': sum_lon / count, 'photo_count': count })

    def display_photos_for_cluster(self, cluster_id_str):
        try:
            cluster_id = int(cluster_id_str)
            cluster = next((c for c in self.clusters_data if c['id'] == cluster_id), None)
            if cluster:
                self.sidebar_label.setText(f"Cluster mit {cluster['photo_count']} Foto(s)")
                self.photo_list_widget.clear()
                for point in cluster['points']:
                    item = QListWidgetItem(os.path.basename(point['filepath']))
                    item.setData(Qt.ItemDataRole.UserRole, point['filepath'])
                    self.photo_list_widget.addItem(item)
                if self.photo_list_widget.count() > 0:
                     self.photo_list_widget.setCurrentRow(0)
                     self.display_preview(self.photo_list_widget.item(0))
        except (ValueError, TypeError) as e:
            logging.warning("Fehler bei der Cluster-Auswahl", exc_info=True)

    def display_preview(self, item):
        if not item:
            self.preview_label.clear(); self.preview_label.setText("")
            return
        
        filepath = item.data(Qt.ItemDataRole.UserRole)
        if filepath and os.path.exists(filepath):
            try:
                pil_image = Image.open(filepath)
                pil_image_oriented = ImageOps.exif_transpose(pil_image)
                pil_image_rgba = pil_image_oriented.convert("RGBA")
                data = pil_image_rgba.tobytes("raw", "RGBA")
                qimage = QImage(data, pil_image_rgba.width, pil_image_rgba.height, QImage.Format.Format_RGBA8888)
                pixmap = QPixmap.fromImage(qimage)
                
                if pixmap.isNull():
                    self.preview_label.setText("Vorschau nicht verfügbar")
                    return
                scaled_pixmap = pixmap.scaled(self.preview_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.preview_label.setPixmap(scaled_pixmap)
            except Exception as e:
                self.preview_label.clear()
                self.preview_label.setText("Fehler beim Laden")
                logging.warning(f"Vorschau-Fehler für {filepath}", exc_info=True)
        else:
            self.preview_label.clear()
            self.preview_label.setText("Bildpfad ungültig.")

    def open_photo_from_sidebar(self, item):
        filepath = item.data(Qt.ItemDataRole.UserRole)
        if filepath and os.path.exists(filepath):
            try: os.startfile(filepath)
            except Exception as e: QMessageBox.warning(self, "Fehler", f"Datei konnte nicht geöffnet werden:\n{e}")

    def clear_all_views(self, is_startup=False):
        self.master_df = pd.DataFrame()
        self.populate_folder_list()
        
        if is_startup:
            m = folium.Map(location=[51.1657, 10.4515], zoom_start=6, tiles="CartoDB positron")
            html_text = """
            <div style="font-family: Arial; color: #333; font-size: 16px; text-align: center; border: 2px solid #555; background-color: rgba(255,255,255,0.75); padding: 10px; border-radius: 5px; box-shadow: 3px 3px 5px rgba(0,0,0,0.3);">
                <b>Willkommen beim Photo Map Viewer!</b><br>
                Bitte laden Sie einen Ordner über das Menü<br>
                <i>Datei &rarr; Foto-Hauptordner laden...</i>
            </div>
            """
            folium.Marker(
                location=[51.3, 10.45],
                icon=folium.features.DivIcon(icon_size=(350,100), icon_anchor=(175,50), html=html_text)
            ).add_to(m)
            data = io.BytesIO(); m.save(data, close_file=False)
            self.web_view.setHtml(data.getvalue().decode())
        
        self.sidebar_label.setText("")
        self.photo_list_widget.clear()
        self.preview_label.clear()
        self.preview_label.setText("")

    def process_image_folder(self, folder_path):
        cache_file_path = os.path.join(folder_path, CSV_CACHE_FILENAME)
        cached_data = self._load_csv_cache(cache_file_path)
        
        all_file_data = cached_data.copy()
        image_files = [os.path.join(r, f) for r, _, fs in os.walk(folder_path) for f in fs if f.lower().endswith(SUPPORTED_EXTENSIONS)]
        
        if not image_files:
            QMessageBox.information(self, "Keine Bilder", f"Keine unterstützten Bilddateien in {os.path.basename(folder_path)} gefunden.")
            return

        progress = QProgressDialog(f"Analysiere '{os.path.basename(folder_path)}'...", "Abbrechen", 0, len(image_files), self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        self.nominatim_api_cache.clear()

        for i, image_path in enumerate(image_files):
            progress.setValue(i); QApplication.processEvents()
            if progress.wasCanceled(): break
            
            relative_path = os.path.relpath(image_path, folder_path)
            progress.setLabelText(f"Verarbeite: {os.path.basename(image_path)}")
            
            if relative_path in all_file_data and all_file_data[relative_path].get('datetime_original'):
                continue

            exif = extract_exif_data(image_path)
            lat, lon, dt = exif['lat'], exif['lon'], exif['datetime']
            
            if relative_path not in all_file_data or not all_file_data[relative_path].get('country'):
                if lat is not None and lon is not None:
                    nominatim_key = (round(lat, 2), round(lon, 2))
                    if nominatim_key in self.nominatim_api_cache:
                        country, city = self.nominatim_api_cache[nominatim_key]
                    else:
                        country, city = fetch_location_from_nominatim(lat, lon, self.nominatim_user_agent)
                        self.nominatim_api_cache[nominatim_key] = (country, city)
                        time.sleep(1.1)
                    
                    all_file_data[relative_path] = {"lat": lat, "lon": lon, "country": country, "city": city, "datetime": dt}
                else:
                    all_file_data[relative_path] = {"lat": None, "lon": None, "country": None, "city": None, "datetime": dt}
            else:
                all_file_data[relative_path]['datetime_original'] = dt

        progress.setValue(len(image_files))
        if not progress.wasCanceled():
            self._save_csv_cache(cache_file_path, all_file_data)

    def _load_csv_cache(self, cache_file_path):
        if not os.path.exists(cache_file_path): return {}
        cached_data = {}
        try:
            with open(cache_file_path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    cached_data[row['filepath']] = {
                        "latitude": float(row['latitude']) if row.get('latitude') else None,
                        "longitude": float(row['longitude']) if row.get('longitude') else None,
                        "country": row.get('country') or None, 
                        "city": row.get('city') or None,
                        "datetime_original": row.get('datetime_original') or None
                    }
        except Exception:
            logging.error(f"Fehler beim Laden des CSV-Cache: {cache_file_path}", exc_info=True)
        return cached_data

    def _save_csv_cache(self, cache_file_path, data):
        try:
            with open(cache_file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
                writer.writeheader()
                for rel_path, details in data.items():
                    writer.writerow({
                        'filepath': rel_path,
                        'latitude': details.get('lat') or details.get('latitude', ''),
                        'longitude': details.get('lon') or details.get('longitude', ''),
                        'country': details.get('country', ''),
                        'city': details.get('city', ''),
                        'datetime_original': details.get('datetime') or details.get('datetime_original', '')
                    })
        except Exception as e:
            logging.error(f"Fehler beim Speichern des CSV-Cache: {cache_file_path}", exc_info=True)

if __name__ == '__main__':
    setup_logging()
    sys.excepthook = uncaught_exception_handler
    
    app = QApplication(sys.argv)
    QCoreApplication.setOrganizationName("niederwe75")
    QCoreApplication.setApplicationName("PhotoMapTool")
    
    main_window = PhotoMapApp()
    main_window.show()
    
    sys.exit(app.exec())
