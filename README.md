# rgbman

Jeden program do całego podświetlenia RGB w komputerze z Windows 11. Steruje wszystkim, co widzi [OpenRGB](https://openrgb.org), oraz urządzeniami, których OpenRGB nie obsługuje. Działa w zasobniku systemowym, ma okno z podglądem na żywo i zsynchronizowane efekty, także reagujące na muzykę.

## Co potrafi

- **16 efektów**: statyczny, gradient, tęcza, cykl kolorów, oddech, bicie serca, fala, przepływ, zorza, kometa, pościg, iskry, ogień oraz trzy reagujące na dźwięk z komputera (puls muzyki, spektrum, wskaźnik VU). Mikrofon nie jest potrzebny, bo efekty dźwiękowe słuchają tego, co gra na domyślnym wyjściu audio.
- **Synchronizacja po strefach.** Każda strefa (pasek, łańcuch wentylatorów, pojedynczy LED na karcie) dostaje cały efekt, więc wszystko świeci w fazie.
- **Ustawienia per urządzenie**: własny efekt lub kolor (np. karta statycznie, reszta w ruchu), tryb „jeden kolor” dla urządzeń z poprzestawianą kolejnością LED-ów (np. mysz), wyprzedzenie w ms i limit klatek na sekundę.
- **Profile** zapamiętujące cały układ, łącznie z ustawieniami per urządzenie.
- **Ustawienia aplikacji**: start z Windows, automatyczne uruchamianie OpenRGB, wyłączanie świateł po zablokowaniu komputera albo przy zamykaniu programu, płynność animacji (20–60 kl./s), liczba LED-ów na złączach ARGB.

## Wymagania

- Windows 10 lub 11
- Python 3 (testowane na 3.14)
- [OpenRGB](https://openrgb.org) z włączonym serwerem SDK (zakładka *SDK Server* → *Start Server* albo uruchomienie z `--server`)

## Instalacja

```
git clone https://github.com/Gr0niec/files.git rgbman
cd rgbman
pip install -r requirements.txt
```

Uruchomienie aplikacji okienkowej:

```
pythonw rgbman_app.py
```

Autostart włączysz w aplikacji: *Ustawienia* → *Uruchamiaj z Windows*. Windows raz poprosi o zgodę administratora. Dzięki temu rgbman startuje po zalogowaniu z uprawnieniami, z którymi może sam włączyć OpenRGB.

## Konfiguracja

Aplikacja działa bez pliku konfiguracji. Jeśli chcesz zmienić ustawienia domyślne, skopiuj `config.example.json` do `config.json`:

| Klucz | Znaczenie |
|---|---|
| `openrgb.host`, `openrgb.port` | adres serwera SDK OpenRGB (domyślnie `127.0.0.1:6742`) |
| `openrgb.zone_sizes` | liczba LED-ów podłączonych do złączy ARGB, per urządzenie i strefa. OpenRGB nie wie, co jest podłączone, i zapomina rozmiary po restarcie, więc rgbman ustawia je przy każdym skanowaniu. Wygodniej ustawić je w oknie: *Ustawienia* → *Złącza ARGB*. Wentylatory na rozgałęźniku liczysz raz. |
| `rivalcfg` | myszki SteelSeries przez [rivalcfg](https://github.com/flozz/rivalcfg), gdy nie widzi ich OpenRGB |
| `maono` | mikrofon Maono PD100X (domyślnie włączony) |
| `hid` | własne proste urządzenia HID opisane szablonami pakietów |

Stan okna, profile i log (`gui_state.json`, `profiles.json`, `rgbman.log`) program tworzy sam obok skryptów.

## Wiersz poleceń

`rgbman.py` działa też bez okna:

```
python rgbman.py list                          # wykryte urządzenia
python rgbman.py set rainbow -s 1.5            # efekt na wszystkim
python rgbman.py set static -c ff0040 -d B650  # tylko urządzenia z "B650" w nazwie
python rgbman.py off
python rgbman.py save wieczor --effect aurora -c 2b00eb -c2 00b4ff
python rgbman.py apply wieczor
```

Wersja CLI ma własne polecenie `autostart`, które tworzy to samo zadanie `rgbman` w Harmonogramie zadań co aplikacja. Używaj jednego z nich.

## Maono PD100X

OpenRGB nie obsługuje tego mikrofonu, a jego protokół nie był nigdzie opisany. Odczytałem go z ruchu USB aplikacji Maono Link 3. Każde polecenie to raport HID `0x4B` (64 bajty, reszta wypełniona zerami):

```
4B C4 0B 00 00 03 <parametr> 20 <wartość u16 LE> <suma u16 LE>
suma = 0x10000 - suma bajtów od C4 do końca wartości
```

| Parametr | Znaczenie | Wartości |
|---|---|---|
| `0x36` | światło | 0 wył., 1 wł. |
| `0x37` | jasność | 0–100 |
| `0x38` | kolor z palety | 0 tęcza (wbudowana), 1 czerwony, 2 pomarańczowy, 3 żółty, 4 zielony, 5 cyjan, 6 niebieski, 7 fioletowy, 8 biały |
| `0x39` | tryb | 0 static, 1 pulse |
| `0x22` | gaszenie przy wyciszeniu | 0 / 1 |

Mikrofon nie przyjmuje dowolnego RGB. rgbman dobiera więc najbliższy kolor z palety i ustawia jasność, dzięki czemu oddech czy puls muzyki działają płynnie. Każdy zapis zajmuje port USB mikrofonu na 16 ms, dlatego pakiety wysyła osobny wątek. Gdy używasz rgbman, zamknij Maono Link, bo obie aplikacje nadpisują sobie nawzajem kolor.

## Przetestowany sprzęt

- ASRock Radeon RX 9070 XT Steel Legend Dark (OpenRGB)
- Gigabyte B650 Eagle AX, złącza ARGB z wentylatorami i paskiem (OpenRGB)
- SteelSeries Rival 5 (OpenRGB)
- Maono PD100X (własny sterownik)

## Licencja

[MIT](LICENSE)
