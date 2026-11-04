"""English for rgbman's Polish UI text, keyed by the Polish original.

One table for both sides: Python translates what it produces (effect names and
descriptions, notices, tray menu), the panel fetches the same table for its own text.
A missing key just shows the Polish text."""

EN = {
    # ---- effects
    "Statyczny": "Static",
    "Gradient": "Gradient",
    "Tęcza": "Rainbow",
    "Cykl kolorów": "Color cycle",
    "Oddech": "Breathe",
    "Bicie serca": "Heartbeat",
    "Fala": "Wave",
    "Przepływ": "Flow",
    "Zorza": "Aurora",
    "Kometa": "Comet",
    "Pościg": "Chase",
    "Iskry": "Twinkle",
    "Ogień": "Fire",
    "Burza": "Storm",
    "Puls muzyki": "Music pulse",
    "Spektrum": "Spectrum",
    "Wskaźnik VU": "VU meter",
    "Beat": "Beat",
    "Ambilight": "Ambilight",
    "Podstawowe": "Basic",
    "Ruch": "Motion",
    "Klimat": "Mood",
    "Reaktywne": "Reactive",
    "Prędkość": "Speed",
    "Czułość": "Sensitivity",
    "Nasycenie": "Saturation",
    "Jeden kolor na wszystkim, bez ruchu.": "One color on everything, no motion.",
    "Płynne przejście od pierwszego do drugiego koloru wzdłuż każdego paska.":
        "A smooth blend from the first to the second color along each strip.",
    "Wszystko naraz zmienia kolor po kolei przez całą tęczę.":
        "Everything changes color together, through the whole rainbow.",
    "Kolor powoli rozjaśnia się i gaśnie, jak oddech.": "The color slowly brightens and fades, like breathing.",
    "Podwójne uderzenie światła w rytmie serca, potem chwila przerwy.":
        "A double beat of light like a heartbeat, then a short pause.",
    "Tęcza przesuwająca się wzdłuż pasków i wentylatorów.": "A rainbow moving along the strips and fans.",
    "Fala jasności biegnąca wzdłuż paska w jednym kolorze.": "A wave of brightness running along the strip in one color.",
    "Dwa kolory płynnie przelewające się wzdłuż paska.": "Two colors flowing smoothly along the strip.",
    "Jasna głowa komety z gasnącym ogonem okrąża każdą strefę; drugi kolor to tło.":
        "A bright comet head with a fading tail circles each zone; the second color is the background.",
    "Co trzeci LED świeci pierwszym kolorem i wszystkie przesuwają się jak w neonie.":
        "Every third LED lights in the first color and they all march along like a neon sign.",
    "Spokojne tło (drugi kolor) i pojedyncze iskry pierwszego koloru zapalające się losowo.":
        "A calm background (second color) with single sparks of the first color lighting up at random.",
    "Wolne, falujące smugi dwóch kolorów, jak zorza polarna.": "Slow, rippling streaks of two colors, like the northern lights.",
    "Płomienie wędrujące od początku paska: żółć i pomarańcz u podstawy, czerwień wyżej.":
        "Flames rising from the start of the strip: yellow and orange at the base, red higher up.",
    "Ciemne, płynące chmury i co kilka sekund błyskawica na wszystkich urządzeniach naraz.":
        "Dark drifting clouds and, every few seconds, lightning on all devices at once.",
    "Jasność podąża za basem w muzyce, od drugiego koloru do pierwszego.":
        "Brightness follows the bass in the music, from the second color to the first.",
    "Korektor graficzny: bas na początku paska, wysokie tony na końcu.":
        "A graphic equalizer: bass at the start of the strip, treble at the end.",
    "Pasek rośnie od środka razem z głośnością, kolor przechodzi w drugi na końcach.":
        "The bar grows from the middle with the volume, turning into the second color at the ends.",
    "Na każde uderzenie basu nowy kolor, który rozbłyska i wygasa.": "A new color on every bass kick, flashing and fading out.",
    "Kolory z ekranu: każdy LED pokazuje swój fragment obrazu od lewej do prawej.":
        "Colors from the screen: each LED shows its part of the picture, left to right.",
    "Reaguje na dźwięk z domyślnego wyjścia audio Windows.": "Reacts to sound from the default Windows audio output.",
    "Kolory z głównego ekranu, od lewej do prawej. Gry w pełnym ekranie (exclusive) mogą dawać czarny obraz: przełącz je na okno bez ramki.":
        "Colors from the main screen, left to right. Exclusive-fullscreen games may capture black: switch them to borderless windowed.",
    "Drugi kolor to niebo (czarny = granat), pierwszy barwi błyskawice.":
        "The second color is the sky (black = navy), the first tints the lightning.",

    # ---- notices from the engine
    "Windows nie dał zgody, autostart bez zmian.": "Windows didn't allow it, autostart unchanged.",
    "Windows nie dał zgody na uruchomienie OpenRGB.": "Windows didn't allow starting OpenRGB.",
    "OpenRGB działa, ale serwer SDK nie odpowiada. Włącz go w OpenRGB: zakładka SDK Server → Start Server.":
        "OpenRGB is running but its SDK server doesn't answer. Turn it on in OpenRGB: SDK Server tab → Start Server.",
    "nie znaleziono OpenRGB.exe, wskaż ścieżkę w ustawieniach": "OpenRGB.exe not found, set its path in the settings",
    "Rozmiar strefy: {msg}.": "Zone size: {msg}.",
    "Rozmiar strefy: nie można zapisać config.json ({msg}).": "Zone size: can't save config.json ({msg}).",
    "urządzenie zniknęło, skanuj ponownie": "the device is gone, rescan",
    "trwa skanowanie, spróbuj za chwilę": "a scan is running, try again in a moment",
    "{zone}: dozwolone {lo}-{hi} LED": "{zone}: {lo}-{hi} LEDs allowed",

    # ---- tray
    "Pokaż": "Show",
    "Światła włączone": "Lights on",
    "Efekt": "Effect",
    "Profil": "Profile",
    "Brak profili": "No profiles",
    "Ustawienia": "Settings",
    "Zakończ": "Quit",
    " (wyłączone)": " (off)",

    # ---- panel
    "Łączenie…": "Connecting…",
    "Skanuj ponownie": "Rescan",
    "Wyłącz światła": "Lights off",
    "Włącz światła": "Lights on",
    "Kolor": "Color",
    "Kolory": "Colors",
    "Główny": "Main",
    "Drugi": "Second",
    "Zamień kolory": "Swap colors",
    "Czarny (brak)": "Black (none)",
    "Wybierz kolor": "Pick a color",
    "Kolor w zapisie HEX": "Color as HEX",
    "Drugi kolor": "Second color",
    "Wybierz drugi kolor": "Pick the second color",
    "Drugi kolor w zapisie HEX": "Second color as HEX",
    "Jasność": "Brightness",
    "Profile": "Profiles",
    "Zapisane profile": "Saved profiles",
    "Zastosuj": "Apply",
    "Usuń": "Delete",
    "Nazwa profilu": "Profile name",
    "Nazwa nowego profilu": "New profile name",
    "Zapisz profil": "Save profile",
    "Gotowe": "Done",
    "Uruchamianie": "Startup",
    "Uruchamiaj z Windows": "Start with Windows",
    "Po zalogowaniu rgbman startuje w zasobniku. Windows poprosi o zgodę administratora przy zmianie, żeby rgbman mógł potem sam uruchamiać OpenRGB.":
        "After you sign in, rgbman starts in the tray. Windows asks for admin consent when you change this, so rgbman can then start OpenRGB on its own.",
    "Po zalogowaniu rgbman startuje w zasobniku i sam uruchamia OpenRGB, jeśli to włączysz niżej.":
        "After you sign in, rgbman starts in the tray and starts OpenRGB itself if you turn that on below.",
    "Jest stary autostart z wiersza poleceń (stały profil „default”). Włączenie tej opcji go zastąpi.":
        "There's an old command-line autostart (fixed profile “default”). Turning this on replaces it.",
    "Czekam na zgodę Windows…": "Waiting for Windows consent…",
    "Uruchamiaj OpenRGB, jeśli nie działa": "Start OpenRGB if it isn't running",
    "Z serwerem SDK, zminimalizowany do zasobnika.": "With its SDK server, minimized to the tray.",
    "Ścieżka do OpenRGB.exe": "Path to OpenRGB.exe",
    "Animacja": "Animation",
    "Płynność animacji": "Animation smoothness",
    "Ile klatek na sekundę liczy rgbman. Więcej to płynniejszy ruch i trochę więcej pracy dla CPU i USB. Wolniejsze urządzenia możesz ograniczyć osobno w „Dostosuj”. Najrówniej wychodzą limity, które dzielą tę wartość (np. 15 przy 30 albo 60).":
        "How many frames per second rgbman renders. More is smoother motion and a bit more work for the CPU and USB. Slower devices can be capped separately under “Customize”. Caps that divide this value are the most even (e.g. 15 at 30 or 60).",
    "20 kl./s": "20 fps",
    "30 kl./s": "30 fps",
    "45 kl./s": "45 fps",
    "60 kl./s": "60 fps",
    "Zachowanie": "Behavior",
    "Zamknięcie okna chowa program do zasobnika": "Closing the window hides rgbman in the tray",
    "Wyłączone: zamknięcie okna kończy program.": "Off: closing the window quits rgbman.",
    "Wyłączaj światła po zablokowaniu komputera": "Turn the lights off when the PC is locked",
    "Win+L i ekran blokady. Włączają się po odblokowaniu.": "Win+L and the lock screen. They come back on when you unlock.",
    "Wyłączaj światła przy zamykaniu programu": "Turn the lights off when rgbman quits",
    "Wyłączone: zostaje ostatni kolor, animacje się zatrzymują.": "Off: the last color stays, animations stop.",
    "Harmonogram": "Schedule",
    "Codziennie o podanej godzinie rgbman włącza wybrany profil. Jeśli komputer był wtedy wyłączony, po starcie włącza ostatni zaplanowany.":
        "Every day at the given time rgbman applies the chosen profile. If the PC was off then, it applies the latest scheduled one at startup.",
    "Dodaj godzinę": "Add a time",
    "Brak zaplanowanych zmian.": "Nothing scheduled.",
    "Godzina": "Time",
    "Co włączyć": "What to apply",
    " (usunięty)": " (deleted)",
    "Złącza ARGB": "ARGB headers",
    "Liczba LED-ów podłączonych do złącza. Wentylatory na rozgałęźniku liczysz raz, bo każdy dostaje ten sam sygnał.":
        "How many LEDs are connected to the header. Fans on a splitter count once, since each gets the same signal.",
    "Język": "Language",
    "Szukam urządzeń…": "Looking for devices…",
    "Skanowanie…": "Scanning…",
    "Nie widzę żadnych urządzeń. Sprawdź, czy serwer OpenRGB działa, i kliknij „Skanuj ponownie”.":
        "No devices found. Check that the OpenRGB server is running, then click “Rescan”.",
    "Dostosuj": "Customize",
    "Własny kolor": "Own color",
    "Własny kolor urządzenia": "The device's own color",
    "Układ": "Layout",
    "Po strefach": "Per zone",
    "Jeden kolor na całym urządzeniu": "One color on the whole device",
    "Wyprzedzenie": "Lead",
    "Maks. klatek/s": "Max fps",
    "Jak wszystkie": "Same as all",
    "Auto": "Auto",
    "Podświetlenie: ": "Lighting: ",
    ", tylko kolor statyczny": ", static color only",
    "Błąd: ": "Error: ",
    "własny kolor": "own color",
    "jeden kolor": "one color",
    "kl./s": "fps",
    "Kolor #": "Color #",
    "Błąd przechwytywania: ": "Capture error: ",
    "Błąd panelu: ": "Panel error: ",
    "Brak połączenia z silnikiem rgbman. Uruchom program ponownie.": "Lost connection to the rgbman engine. Restart the app.",
    "Usunąć profil „{name}”?": "Delete profile “{name}”?",
    "Brak profili.": "No profiles.",
}
