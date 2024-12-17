import os

# Der Header-Text, den du hinzufügen möchtest
HEADER_TEXT = """\
#
# This file is part of Proto²Testbed.
#
# Copyright (C) 2024 Martin Ottens
# 
# This program is free software: you can redistribute it and/or modify 
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, 
# but WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the 
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License 
# along with this program. If not, see https://www.gnu.org/licenses/.
#
"""

def add_header_to_file(file_path):
    """
    Fügt den Header zu einer Datei hinzu, falls er noch nicht vorhanden ist.
    """
    with open(file_path, 'r+', encoding='utf-8') as f:
        content = f.read()
        # Prüfen, ob der Header schon existiert
        if HEADER_TEXT.splitlines()[1] in content:
            print(f"Header bereits vorhanden: {file_path}")
            return
        
        # Header einfügen
        print(f"Füge Header hinzu: {file_path}")
        f.seek(0, 0)  # Zurück zum Anfang der Datei
        f.write(HEADER_TEXT + "\n" + content)

def process_directory(directory):
    """
    Geht rekursiv durch ein Verzeichnis und fügt den Header zu allen .py-Dateien hinzu.
    """
    for root, _, files in os.walk(directory):
        for file in files:
            if file == "__init__.py":
                continue
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                add_header_to_file(file_path)

if __name__ == "__main__":
    # Wähle das Startverzeichnis (aktuelles Verzeichnis)
    directory = os.getcwd()
    print(f"Starte die Verarbeitung in: {directory}")
    process_directory(directory)
    print("Fertig!")