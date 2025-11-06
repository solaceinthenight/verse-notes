import requests
import os
from dotenv import load_dotenv
import pyperclip
import sys
import json
import shlex
import codecs
from prompt_toolkit import prompt
from prompt_toolkit.history import FileHistory
import re
from pathlib import Path

def get_app_data_dir():
    """
    Gets the standard, OS-specific data directory.
    Creates it if it doesn't exist.
    """
    app_name = "verse_notes" # This will be the folder name

    # macOS: ~/Library/Application Support/<app_name>
    if sys.platform == "darwin":
        data_dir = Path.home() / "Library" / "Application Support" / app_name
    
    # Linux (XDG Standard): ~/.local/share/<app_name>
    elif sys.platform == "linux":
        # Use XDG_DATA_HOME if set, otherwise default
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            data_dir = Path(xdg_data) / app_name
        else:
            data_dir = Path.home() / ".local" / "share" / app_name
    
    # Fallback (Windows, etc.): ~/.<app_name>
    # Your original method is a good fallback.
    else:
        data_dir = Path.home() / f".{app_name}_data"

    # Create the directory if it doesn't exist
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        # If it fails for any reason, fall back to the current directory
        data_dir = Path(".")

    return data_dir

# Version Number
CURRENT_VERSION = "1.0.0"

bible_notes = {}


app_data_dir = get_app_data_dir()
os.makedirs(app_data_dir, exist_ok=True)
NOTES_FILENAME = "bible_notes.json"
NOTES_FILE_PATH = app_data_dir / NOTES_FILENAME 
DOTENV_FILE_PATH = app_data_dir / ".env"
HISTORY_FILE_PATH = app_data_dir / ".verse_repl_history"

# --- .env Loading ---
if os.path.exists(DOTENV_FILE_PATH):
    load_dotenv(dotenv_path=DOTENV_FILE_PATH)
else:
    print(f"Error: .env file not found. Please place it in the directory: {DOTENV_FILE_PATH}")
    sys.exit(1)

# --- API Configuration ---
API_URL = os.getenv("API_URL")
HEADERS = {"Accept": "application/json", "Authorization": os.getenv("API_KEY")}
BASE_PARAMS = {"file": os.getenv("FILE"), "Out": "json", "Lang": "eng"}

def load_notes():
    """Loads notes from the JSON file into the global bible_notes dictionary."""
    global bible_notes
    if not os.path.exists(NOTES_FILE_PATH):
        bible_notes = {}
        return
    try:
        with open(NOTES_FILE_PATH, 'r') as f:
            bible_notes = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"⚠️ Warning: Could not load notes file. Starting fresh. Error: {e}")
        bible_notes = {}

def save_notes():
    """Saves the current bible_notes dictionary to the JSON file."""
    try:
        with open(NOTES_FILE_PATH, 'w') as f:
            json.dump(bible_notes, f, indent=4)
    except IOError as e:
        print(f"❌ Error: Could not save notes to file. Error: {e}")

def parse_reference(ref_string):
    """
    Parses a Bible reference string into its components.
    Returns a tuple: (book, chapter, verse_key)
    
    Examples:
    - "John 3:16"    -> ("John", "3", "16")
    - "John 3:16-17" -> ("John", "3", "16-17")
    - "John 3"       -> ("John", "3", None)
    - "John"         -> ("John", None, None)
    - "1 John 3:16"  -> ("1 John", "3", "16")
    """
    ref_string = ref_string.strip()
    
    # Pattern to capture (Book) (Chapter) (Verse)
    # Allows for "1 John" or "Song of Solomon"
    # (?:\s*(\d+))? - Optional chapter number
    # (?::\s*([\d\-,]+))? - Optional verse key
    pattern = re.compile(
        r"^((\d\s)?[A-Za-z\s]+?)\s*"  # Group 1: Book name (e.g., "1 John", "John")
        r"(\d+)?"                     # Group 3: Chapter (optional)
        r"(?::\s*([\d\-,]+))?$"        # Group 4: Verse key (optional)
        , re.IGNORECASE
    )

    match = pattern.match(ref_string)

    if not match:
        # Simple case: just a book name like "Genesis"
        if re.fullmatch(r"^((\d\s)?[A-Za-z\s]+)$", ref_string, re.IGNORECASE):
             return (ref_string.title(), None, None)
        return (None, None, None) # Invalid format

    # Clean up the matched groups
    book = match.group(1).strip().title()
    chapter = match.group(3)
    verse_key = match.group(4)

    return (book, chapter, verse_key)

def get_notes_for_reference(book, chapter, verse_key, note_level):
    """
    Retrieves all relevant notes for a given reference based on the note_level.
    Returns a dictionary of note lists.
    """
    notes = {
        "book": [],
        "chapter": [],
        "group": [],
        "individual": []
    }

    if not book or book not in bible_notes:
        return notes

    # Level 4: Get BOOK notes
    if note_level >= 4:
        notes["book"] = bible_notes[book].get("notes", [])

    if not chapter or chapter not in bible_notes[book].get("chapters", {}):
        return notes

    book_chapters = bible_notes[book]["chapters"]

    # Level 3: Get CHAPTER notes
    if note_level >= 3:
        notes["chapter"] = book_chapters[chapter].get("notes", [])
    
    if not verse_key or not book_chapters[chapter].get("verses", {}):
        return notes
    
    chapter_verses = book_chapters[chapter]["verses"]

    # Level 1 & 2: Get INDIVIDUAL notes
    if note_level >= 1:
        notes["individual"] = chapter_verses.get(verse_key, [])

    # Level 2: Get GROUP notes
    if note_level >= 2:
        # This is more complex: find all group keys (e.g., "16-18")
        # that contain the current verse_key (e.g., "16")
        try:
            current_verse_num = int(verse_key.split('-')[0]) # Get "16" from "16"
            for key, group_notes in chapter_verses.items():
                if '-' not in key or key == verse_key:
                    continue # Skip individual notes or the exact match
                
                parts = key.split('-')
                if len(parts) == 2:
                    start, end = int(parts[0]), int(parts[1])
                    if start <= current_verse_num <= end:
                        notes["group"].extend(group_notes)
        except ValueError:
            pass # Ignore if verse_key isn't a simple number (e.g., "1a")

    return notes

def format_and_print_notes(notes_dict):
    """Prints a formatted block of notes."""
    # Order matters: from broadest (Book) to narrowest (Individual)
    level_map = [
        ("Book", "book"),
        ("Chapter", "chapter"),
        ("Group", "group"),
        ("Individual", "individual")
    ]
    
    has_printed_header = False
    for label, key in level_map:
        notes_list = notes_dict.get(key)
        if notes_list:
            if not has_printed_header:
                print("|| Notes:")
                has_printed_header = True
            
            print(f"  [{label}]")
            for i, note in enumerate(notes_list, 1):
                print(f"    {i}. {note}")


def fetch_and_display_verses(verse_reference, enable_copy=False, note_level=0, enable_spacious=False, joiner=None):
    """
    Fetches verses, prints them, handles notes, and handles copy formatting.
    note_level 0 = no notes
    note_level 1 = individual
    note_level 2 = individual + group (-v default)
    note_level 3 = individual + group + chapter
    note_level 4 = all
    """
    params = BASE_PARAMS.copy()
    params["String"] = verse_reference

    try:
        response = requests.get(API_URL, headers=HEADERS, params=params)
        response.raise_for_status()
        data = response.json()

        if not data or "verses" not in data or not data["verses"]:
            print(f"Verse not found for '{verse_reference}'.")
            return
        
        num_results = len(data["verses"]) 
        text_to_copy = [] 

        print("-" * 40)
        for verse in data["verses"]:
            reference = verse.get("ref", "No Reference")
            text = verse.get("text", "No Text").strip()
            
            print(f"\n{reference}")
            print(text)

            if note_level > 0:
                # Parse the *specific* verse reference from the API response
                book, chapter, verse_key = parse_reference(reference)
                if book:
                    notes_dict = get_notes_for_reference(book, chapter, verse_key, note_level)
                    format_and_print_notes(notes_dict)

            text_to_copy.append(f'{reference} {text}')

        print("\n" + "-" * 40)
        
        print(f"Found {num_results} verse(s).") 
        
        if enable_copy:
            final_joiner = "\n" # Default
            if joiner is not None:
                final_joiner = joiner
            elif enable_spacious:
                final_joiner = "\n\n"
            
            pyperclip.copy(final_joiner.join(text_to_copy))
            print("✅ Verses copied to clipboard.")

    except requests.exceptions.RequestException as e:
        print(f"\n❌ Network or API error: {e}")
    except ValueError:
        print("\n❌ Could not parse the response from the server.")

def print_help():
    print(f"--- Bible Verse Fetcher {CURRENT_VERSION} ---")
    print("Created by: solaceinthenight")
    print("Enter a verse reference (e.g., 'John 3:16').")
    print("Flags (can be placed anywhere):")
    print("  -c : Copy the result to the clipboard.")
    print("  -s : Add a blank line between verses when copying (spacious).")
    print("  -j \"<joiner>\" : Use a custom joiner for copied text (e.g., -j \"\\n--\\n\").")
    print("  -v : View notes (Individual + Group). Alias for '-n 2'.")
    print("  -n <level> : View notes by level:")
    print("     1: Individual only")
    print("     2: Individual + Group (default for -v)")
    print("     3: Individual + Group + Chapter")
    print("     4: All (Book, Chapter, Group, Individual)")
    print("Commands:")
    print("  /help : Show this help message.")
    print("  /addnote \"<reference>\" <note text>")
    print("  /delnote \"<reference>\" <note_number>")
    print("  /allnotes")
    print("Type 'quit' or 'exit' to end the program.")


def start_repl():
    """Main function to run the REPL (Read-Eval-Print Loop)."""
    load_notes()

    repl_history = FileHistory(HISTORY_FILE_PATH)

    print_help()
    
    while True:
        user_input = prompt("\nVERSE_NOTES > ", history=repl_history).strip()
        
        if user_input.lower() in ["quit", "exit"]:
            print("Goodbye!")
            break
        
        if not user_input:
            continue
        
        if user_input.startswith('/'):
            try:
                parts = shlex.split(user_input)
                command = parts[0].lower()

                if command =="/help":
                    print_help()
                    continue

                if command == "/addnote":
                    if len(parts) < 3:
                        print("Usage: /addnote \"<reference>\" <note>")
                        continue
                    ref_string, note_text = parts[1], " ".join(parts[2:])
                    book, chapter, verse_key = parse_reference(ref_string)

                    if not book:
                        print(f"Error: Invalid reference format '{ref_string}'")
                        continue

                    # Ensure path exists
                    if book not in bible_notes:
                        bible_notes[book] = {"notes": [], "chapters": {}}
                    
                    # Case 1: Book-level note (e.g., "John")
                    if not chapter:
                        bible_notes[book]["notes"].append(note_text)
                        print(f"✅ Note added for Book: '{book}'")
                    
                    # Case 2: Chapter-level note (e.g., "John 3")
                    elif chapter and not verse_key:
                        if chapter not in bible_notes[book]["chapters"]:
                            bible_notes[book]["chapters"][chapter] = {"notes": [], "verses": {}}
                        bible_notes[book]["chapters"][chapter]["notes"].append(note_text)
                        print(f"✅ Note added for Chapter: '{book} {chapter}'")

                    # Case 3: Verse-level note (e.g., "John 3:16" or "John 3:16-17")
                    else:
                        if chapter not in bible_notes[book]["chapters"]:
                            bible_notes[book]["chapters"][chapter] = {"notes": [], "verses": {}}
                        if verse_key not in bible_notes[book]["chapters"][chapter]["verses"]:
                            bible_notes[book]["chapters"][chapter]["verses"][verse_key] = []
                        bible_notes[book]["chapters"][chapter]["verses"][verse_key].append(note_text)
                        print(f"✅ Note added for Verse: '{book} {chapter}:{verse_key}'")

                    save_notes()
                    continue

                if command == "/delnote":
                    if len(parts) != 3:
                        print("Usage: /delnote \"<reference>\" <note_number>")
                        continue
                    
                    ref_string, note_num_str = parts[1], parts[2]
                    book, chapter, verse_key = parse_reference(ref_string)

                    if not book:
                        print(f"Error: Invalid reference format '{ref_string}'")
                        continue
                    
                    note_num = int(note_num_str) - 1 # Convert to 0-based index
                    target_list = None
                    ref_name = ""

                    try:
                        # Case 1: Book note
                        if not chapter:
                            target_list = bible_notes[book]["notes"]
                            ref_name = book
                        # Case 2: Chapter note
                        elif chapter and not verse_key:
                            target_list = bible_notes[book]["chapters"][chapter]["notes"]
                            ref_name = f"{book} {chapter}"
                        # Case 3: Verse note
                        else:
                            target_list = bible_notes[book]["chapters"][chapter]["verses"][verse_key]
                            ref_name = f"{book} {chapter}:{verse_key}"

                        if 0 <= note_num < len(target_list):
                            deleted_note = target_list.pop(note_num)
                            print(f"✅ Deleted note #{note_num + 1} for '{ref_name}': '{deleted_note}'")
                            save_notes()
                        else:
                            print(f"Error: Invalid note number. Must be between 1 and {len(target_list)}.")
                    
                    except (KeyError, TypeError):
                        print(f"Error: No notes found for reference '{ref_string}'.")
                    except ValueError:
                         print("Error: Note number must be an integer.")
                    continue

                if command == "/allnotes":
                    if not bible_notes:
                        print("No notes found.")
                        continue
                    
                    print("\n--- All Notes ---")
                    for book, book_data in bible_notes.items():
                        if book_data["notes"]:
                            print(f"\n[{book}]")
                            for i, note in enumerate(book_data["notes"], 1):
                                print(f"  {i}. {note}")
                        
                        for chapter, chap_data in book_data.get("chapters", {}).items():
                            if chap_data["notes"]:
                                print(f"  [{book} {chapter}]")
                                for i, note in enumerate(chap_data["notes"], 1):
                                    print(f"    {i}. {note}")
                            
                            for verse_key, verse_notes in chap_data.get("verses", {}).items():
                                if verse_notes:
                                    print(f"    [{book} {chapter}:{verse_key}]")
                                    for i, note in enumerate(verse_notes, 1):
                                        print(f"      {i}. {note}")
                    print("-----------------")
                    continue
                
                print(f"Unknown command: {command}")
            except Exception as e:
                print(f"Error processing command: {e}")
            continue

        try:
            parts = shlex.split(user_input)
        except ValueError as e:
            print(f"Error: Mismatched quotes in input. {e}")
            continue

        flags = set()
        query_parts = []
        joiner_str = None
        note_level = 0 # Default: no notes
        has_error = False
        
        i = 0
        while i < len(parts):
            part = parts[i]
            if part == '-c':
                flags.add('-c')
                i += 1
            elif part == '-s':
                flags.add('-s')
                i += 1
            elif part == '-v':
                flags.add('-v')
                if note_level == 0: # Don't override a specific -n
                    note_level = 2 
                i += 1
            elif part == '-j':
                if i + 1 < len(parts):
                    joiner_str = codecs.decode(parts[i+1], 'unicode_escape')
                    i += 2 
                else:
                    print("Error: -j flag requires a joiner string argument.")
                    has_error = True
                    break
            elif part == '-n': 
                if i + 1 < len(parts):
                    try:
                        level = int(parts[i+1])
                        if 1 <= level <= 4:
                            note_level = level
                        else:
                            print("Error: -n level must be between 1 and 4.")
                            has_error = True
                            break
                        i += 2
                    except ValueError:
                        print("Error: -n flag requires a number (1-4).")
                        has_error = True
                        break
                else:
                    print("Error: -n flag requires a level number (1-4).")
                    has_error = True
                    break
            else:
                query_parts.append(part)
                i += 1
        
        if has_error:
            continue

        verse_query = " ".join(query_parts)
        enable_copy = '-c' in flags
        enable_spacious = '-s' in flags

        if not verse_query:
            if flags or joiner_str is not None or note_level > 0:
                print("Error: Flags must be used with a verse reference.")
            continue

        fetch_and_display_verses(verse_query, enable_copy, note_level, enable_spacious, joiner_str)

if __name__ == "__main__":
    start_repl()
