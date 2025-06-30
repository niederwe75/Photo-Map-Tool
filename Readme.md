# **Photo Map Tool v1.2.2**

Ein einfaches, aber leistungsstarkes Desktop-Tool zur Visualisierung von Fotos mit GPS-Daten auf einer interaktiven Karte. Das Tool liest EXIF-Daten aus Bilddateien, ruft über Nominatim die entsprechenden Ortsnamen ab und stellt die Fotos als gruppierte Cluster auf einer Karte dar.

## **Features**

* **Automatische GPS-Extraktion:** Liest Breiten- und Längengrade direkt aus den EXIF-Daten von .jpg, .jpeg, .tiff, .heic und weiteren Formaten.  
* **Geolokalisierung:** Wandelt GPS-Koordinaten mithilfe der [Nominatim API (OpenStreetMap)](https://www.google.com/search?q=https://nominatim.openstreetmap.org/) in lesbare Ortsnamen (Land, Stadt) um.  
* **Interaktive Karte:** Zeigt Fotos als klickbare Cluster auf einer Karte an. Ein Klick auf einen Cluster enthüllt die enthaltenen Fotos.  
* **Effizientes Caching:**  
  * Ein intelligentes Zwei-Ebenen-Cache-System verhindert unnötige Analysen und API-Abfragen.  
  * **Level 1:** Pro Unterordner wird eine .csv-Cache-Datei angelegt, die GPS- und Ortsdaten speichert.  
  * **Level 2:** Eine combined\_geodata.parquet-Datei im Hauptordner fasst alle Daten für einen blitzschnellen Start zusammen.  
* **Vorschau-Funktion:** Zeigt eine Liste der Fotos im ausgewählten Cluster an und bietet eine Vorschau beim Anklicken.  
* **Konfigurierbarkeit:** Über einen Einstellungsdialog können wichtige Parameter wie die Cluster-Distanz und der User-Agent angepasst werden.  
* **Zustandsspeicherung:** Merkt sich die Fenstergröße, \-position und die Aufteilung der Bereiche für den nächsten Start.

## **Anleitung**

1. **Anwendung starten:** Führe die Photo Map Tool.exe (nach dem Kompilieren) oder das main.py Skript aus.  
2. **Hauptordner laden:** Gehe im Menü auf Datei \-\> Foto-Hauptordner laden... und wähle das Hauptverzeichnis aus, das deine Foto-Unterordner enthält.  
3. **Analyse (optional):** Das Tool erkennt automatisch Ordner, die noch nicht analysiert wurden, und fragt, ob es dies tun soll. Alternativ kann eine manuelle Analyse über Datei \-\> Unterordner analysieren... gestartet werden.  
4. **Ordner auswählen:** Wähle auf der linken Seite einen der gefundenen Unterordner aus. Die Karte wird automatisch mit den Clustern dieses Ordners aktualisiert.  
5. **Cluster erkunden:** Klicke auf einen der Marker (Cluster) auf der Karte.  
6. **Fotos ansehen:** Auf der rechten Seite erscheint nun eine Liste aller Fotos in diesem Cluster. Klicke auf einen Dateinamen, um eine Vorschau anzuzeigen. Ein Doppelklick öffnet die Datei im Standard-Bildbetrachter deines Systems.

## **Installation & Ausführung aus dem Quellcode**

Um das Tool aus dem Quellcode auszuführen oder selbst zu kompilieren, befolge diese Schritte.

### **1\. Voraussetzungen**

* Python 3.x  
* Die in requirements.txt aufgeführten Python-Bibliotheken.

### **2\. Abhängigkeiten installieren**

Erstelle eine Datei namens requirements.txt mit folgendem Inhalt:

pandas  
folium  
PyQt6  
PyQt6-WebEngine  
Pillow  
requests  
pyarrow

Installiere diese Abhängigkeiten mit pip:

pip install \-r requirements.txt

### **3\. Anwendung kompilieren (optional)**

Um eine eigenständige .exe-Datei für Windows zu erstellen, kannst du PyInstaller verwenden. Führe den folgenden Befehl im Terminal aus (im selben Verzeichnis wie main.py):

python \-m PyInstaller \--onedir \--windowed \--name="Photo Map Tool" main.py

Die fertige Anwendung findest du im neu erstellten dist/Photo Map Tool-Ordner.

## **Konfiguration**

Unter Extras \-\> Einstellungen... können folgende Parameter angepasst werden:

* **Cluster-Distanz:** Der maximale Radius in Metern, in dem Fotos zu einem einzigen Cluster zusammengefasst werden.  
* **Nominatim User-Agent:** Der User-Agent, der bei Anfragen an die Nominatim-API gesendet wird. Es ist guter Stil, hier eine Information zu deinem Projekt anzugeben (z.B. "PhotoMapTool/1.2, https://www.google.com/search?q=github.com/DeinUsername/DeinRepo").

## **Das Cache-System**

* **.exif\_tool\_cache.csv:** Wird in jedem analysierten Unterordner erstellt. Sie enthält die extrahierten GPS-Daten und die von Nominatim abgerufenen Ortsnamen. Das verhindert, dass bei wiederholten Analysen desselben Ordners erneut API-Anfragen gestellt werden müssen.  
* **combined\_geodata.parquet & cache\_manifest.json:** Diese Dateien liegen im Foto-Hauptordner. Die .parquet-Datei ist eine binäre, spaltenorientierte und hoch-performante Zusammenfassung aller .csv-Dateien. Sie ermöglicht das fast sofortige Laden aller Daten beim Programmstart. Die .json-Datei prüft, ob sich die .csv-Dateien geändert haben, um zu entscheiden, ob der .parquet-Cache neu gebaut werden muss.  
* **Gesamt-Cache neu erstellen:** Diese Menüfunktion löscht nur die .parquet- und .json-Dateien und zwingt das Programm, die Daten aus den vorhandenen .csv-Dateien neu zusammenzusetzen. Nützlich, wenn Ordner manuell gelöscht wurden.

## **Lizenz**

Dieses Projekt steht unter der [MIT License](https://www.google.com/search?q=LICENSE).