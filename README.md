# Triki Controller — instrukcja użytkownika

Triki Controller łączy nakładkę Triki CAP001 przez Bluetooth Low Energy (BLE) i zamienia jej ruch na **Kierownicę**, **AirMouse**, **Joystick** albo **Multimedia**. Interfejs to aplikacja desktopowa Tkinter/CustomTkinter, nie strona WWW. CLI służy także do diagnostyki i zapisu surowych próbek.

> **Zakres tej instrukcji:** bieżący kod dla wydania v0.1.4 i pakiety zbudowane z niego. Wersja v0.1.4 porządkuje ekran sterowania, przypisania i diagnostykę; wcześniejsze v0.1.3 zawiera ulubiony cel startowy, ale nie ma nowego układu ani poprawek Stop/Wznów. Aktualizacja README nie oznacza, że funkcje przeszły QA na fizycznej nakładce lub na wszystkich systemach.
>
> Obsługa CAP001 nadal używa parsera `reference-hypothesis` opartego na TrikiScope. Format ramek i przeliczniki 2048 LSB/g oraz 131 LSB/(°/s) nie są pełną akceptacją protokołu HOM-27. Syntetyczne testy i podgląd nie zastępują pomiarów sprzętowych.

## Spis treści

- [Instalacja i uruchomienie](#instalacja-i-uruchomienie)
- [Możliwości i wymagania systemów](#możliwości-i-wymagania-systemów)
- [Pierwsze połączenie i bezpieczny start](#pierwsze-połączenie-i-bezpieczny-start)
- [Menu główne i ekran urządzenia](#menu-główne-i-ekran-urządzenia)
- [Cztery tryby sterowania](#cztery-tryby-sterowania)
- [Ulubiony odtwarzacz startowy](#ulubiony-odtwarzacz-startowy)
- [Własne przypisania przycisku i kierunków](#własne-przypisania-przycisku-i-kierunków)
- [Konfigurator krok po kroku](#konfigurator-krok-po-kroku)
- [Zapis ustawień](#zapis-ustawień)
- [Skróty i zasobnik systemowy](#skróty-i-zasobnik-systemowy)
- [CLI i diagnostyka](#cli-i-diagnostyka)
- [Rozwiązywanie problemów](#rozwiązywanie-problemów)
- [Budowanie i weryfikacja dla programistów](#budowanie-i-weryfikacja-dla-programistów)
- [Ikona, struktura i licencje](#ikona-struktura-i-licencje)

## Instalacja i uruchomienie

### Gotowy pakiet desktopowy

Wybierz archiwum dla swojego systemu i architektury. Nie uruchamiaj programu bezpośrednio z podglądu ZIP i **nie kopiuj samego pliku wykonywalnego**: potrzebne są biblioteki, zasoby i cały katalog aplikacji.

| System | Archiwum / zawartość | Uruchomienie |
| --- | --- | --- |
| Linux | `TrikiController-linux-<arch>.tar.gz`, katalog `TrikiController/` z plikiem `TrikiController` i `_internal/` | Rozpakuj cały katalog; uruchom `./TrikiController` z tego katalogu. |
| Windows | `TrikiController-win32-<arch>.zip`, katalog `TrikiController/` z `TrikiController.exe` i zależnościami | Wypakuj wszystko; uruchom `TrikiController.exe`. |
| macOS | `TrikiController-darwin-<arch>.zip`, pakiet `TrikiController.app` | Wypakuj całą aplikację; uruchom `.app`. Dostępny pakiet `darwin-arm64` jest dla Apple Silicon, nie jest uniwersalnym buildem dla Intel. |

Uruchomienie gotowego programu bez argumentów otwiera menu główne. Na Linuksie, jeśli archiwum nie zachowało prawa wykonania, nadaj je **własnej rozpakowanej kopii**:

```bash
chmod +x ./TrikiController
./TrikiController
```

**Zaufanie do pakietu:** proces budowania nie zapewnia zaufanego podpisu Windows ani podpisu Developer ID/notaryzacji macOS. macOS używa domyślnego podpisywania ad-hoc PyInstallera; to nie jest certyfikat zaufanej dystrybucji, a poprawność końcowego podpisu wymaga osobnej kontroli. System może zablokować uruchomienie. Sprawdź pochodzenie pakietu i informacje wydania; nie wyłączaj ochrony systemu ani nie obchodź jej poleceniami z internetu. Uprawnienia do sterowania myszą/odtwarzaczem są osobną sprawą od podpisu aplikacji.

Po rozpakowaniu umieść program w docelowym katalogu **przed** tworzeniem skrótów. Przeniesienie go później może zerwać ścieżki skrótów.

### Uruchomienie z kodu źródłowego

Wymagany jest Python **3.11 lub nowszy**. Poniższe polecenia wykonuj w katalogu repozytorium. Instalacja rdzenia nie wymaga bibliotek zewnętrznych; GUI, BLE i wyjście systemowe mają dodatkowe zależności.

Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e .
.venv/bin/triki-controller gui
```

Windows — PowerShell, bez konieczności aktywowania skryptu środowiska:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\triki-controller.exe gui
```

`requirements.txt` instaluje CustomTkinter, Pillow, Bleak i — tylko na Linuksie — `evdev`/`pywayland`. **Nie instaluje natywnego audio Windows/macOS ani opcjonalnego zasobnika.** Dla pełnego stosu desktopowego na danym systemie można dodatkowo użyć:

```bash
# Linux/macOS
.venv/bin/python -m pip install -r packaging/requirements-desktop.txt
```

```powershell
# Windows
.\.venv\Scripts\python.exe -m pip install -r packaging/requirements-desktop.txt
```

Ten plik zawiera także PyInstaller (potrzebny do budowania, nie do zwykłego uruchomienia). Zależności natywne są wybierane znacznikami systemu: Windows — `pycaw`, `comtypes`, `psutil`; macOS — PyObjC Cocoa, ScriptingBridge i Quartz. Zainstaluj je na docelowym systemie, nie na Linuksie w celu „udawania” Windows/macOS.

Na Linuksie potrzebny jest również systemowy Tk: np. `python3-tk` na Debian/Ubuntu albo `tk` na Arch/CachyOS. BLE wymaga działającego Bluetooth/BlueZ i D-Bus. Narzędzia `playerctl` oraz `pactl` do audio nie są dostarczane przez pip. Ulubiony cel startowy MPRIS dodatkowo wymaga `busctl` (narzędzie systemd), dostępnej magistrali sesji D-Bus i poprawnego `DesktopEntry` odtwarzacza. Brak tych zależności daje komunikat i blokuje zastępcze sterowanie innym celem.

Alternatywnie instaluj tylko wybrane extras:

```bash
.venv/bin/python -m pip install -e '.[gui,ble]'
# Tylko Linux: dodatkowo wyjście przez uinput
.venv/bin/python -m pip install -e '.[uinput]'
```

Bez instalacji samego pakietu, z katalogu repozytorium na Linux/macOS:

```bash
PYTHONPATH=src .venv/bin/python -m triki_controller.cli.main --help
PYTHONPATH=src .venv/bin/python -m triki_controller.cli.main gui
```

W dalszych przykładach `triki-controller` oznacza polecenie z zainstalowanego środowiska; bez aktywacji używaj jego pełnej ścieżki, np. `.venv/bin/triki-controller`.

## Możliwości i wymagania systemów

| Funkcja Live | Linux | Windows | macOS |
| --- | --- | --- | --- |
| AirMouse, kliknięcia i własne klawisze | `evdev` / `/dev/uinput` | Natywny `SendInput` | Natywne zdarzenia Quartz; uprawnienie Accessibility |
| Analogowa kierownica, gaz/hamulec i joystick | Wirtualne urządzenie uinput | **Brak wirtualnego HID/gamepada** | **Brak wirtualnego HID/gamepada** |
| Kierownica/Joystick z własnymi przypisaniami klawiatury lub przycisków myszy | Przypisania obok dotychczasowego wyjścia | Tryb samych przypisań, po wybraniu co najmniej jednej konkretnej akcji | Tryb samych przypisań, po wybraniu co najmniej jednej konkretnej akcji; Accessibility |
| Multimedia: głośność odtwarzacza | MPRIS / `playerctl`; zależnie od możliwości odtwarzacza | Sesja aplikacji Core Audio | Działające aplikacje Music/Spotify; Automation |
| Multimedia: głośność systemu po odwróceniu | Domyślne wyjście audio przez `pactl` | Domyślne wyjście Core Audio | Adapter systemowy; nie wszystkie urządzenia mają regulowaną głośność |

**Linux:** użytkownik musi mieć uprawnienia do `/dev/uinput`. Jeśli urządzenia brak, administrator powinien sprawdzić moduł `uinput` i reguły dostępu właściwe dla dystrybucji. Nie rozwiązuj tego przez uruchamianie całego GUI jako root lub udostępnianie urządzenia wszystkim. Absolutny kursor w trybie Joystick dodatkowo wymaga obsługiwanych protokołów kompozytora Wayland; sam uinput nie zapewnia tej funkcji. Okno Tk pod Wayland może wymagać XWayland.

**Windows:** `SendInput` podlega ograniczeniom UIPI/poziomu integralności. Sterowanie aplikacją uruchomioną z wyższymi uprawnieniami może nie działać. Odbiór zdarzeń przez grę/aplikację trzeba sprawdzić osobno; wysłanie zdarzenia nie jest dowodem, że cel je zaakceptował.

**macOS:** w ustawieniach prywatności systemu przyznaj **Dostępność (Accessibility)** procesowi wysyłającemu zdarzenia oraz **Automatyzację (Automation)** dla sterowania Music/Spotify, gdy system o to poprosi. Zgoda dla uruchomienia z Pythona/terminala nie jest automatycznie zgodą dla spakowanej `.app`. Audio przeglądarki ani dowolna karta WWW nie są obsługiwanym odtwarzaczem macOS.

**Próbne / dry-run** działa bez wysyłania wejścia do systemu. Podgląd analogowej osi na Windows/macOS nie tworzy kontrolera rozpoznawanego przez grę. Brak uprawnień lub nieobsługiwane wyjście daje komunikat, nie przełączenie na backend innego systemu.

## Pierwsze połączenie i bezpieczny start

1. Włącz Bluetooth. Zamknij TrikiScope i inne programy korzystające z tej samej nakładki.
2. Uruchom menu i wybierz **Konfigurator**, jeśli chcesz najpierw sprawdzić ruch bez sterowania komputerem.
3. W **Podgląd** lub **Konfiguracja** kliknij **Połącz**. Podczas skanowania naciśnij **raz** fizyczny przycisk Triki, aby obudzić nakładkę. Domyślne okno skanowania wynosi 30 s.
4. Poczekaj na strumień próbek. Trzymaj nakładkę spokojnie w pozycji neutralnej: aplikacja ustala początek ruchu po krótkim rozruchu strumienia.
5. Wybierz zakładkę profilu w **Konfiguracja**, obejrzyj czujniki i mapowanie. Użyj **Próbne**, aby sprawdzić wyjście bez zdarzeń systemowych.
6. Dopiero potem użyj **Na żywo**. Mysz może zacząć poruszać kursorem, własne przypisania mogą przytrzymywać klawisze, a Multimedia zmieniać audio. Zacznij od niskiej głośności i neutralnej pozycji.
7. **Stop** / **Zatrzymaj** wyłącza wyjście, ale nie rozłącza BLE. **Rozłącz** kończy połączenie i zatrzymuje wyjście.

**Uwaga na szybki start:** przycisk **Otwórz** na karcie urządzenia oraz komendy `mouse`, `wheel`, `music` łączą BLE i automatycznie uzbrajają **Live**, gdy pojawi się strumień. Konfigurator nie uzbraja Live automatycznie — może jednak wysyłać zdarzenia po świadomym kliknięciu **Na żywo**. CLI `gui --dry-run` pozwala uruchomić panel z szybkim startem w trybie próbnym.

Po utracie połączenia wyjście jest zatrzymywane. **Połącz** ponawia próbę po rozłączeniu/błędzie; ponownie obudź Triki jednym naciśnięciem. Szybkie tryby mogą po nowym strumieniu ponownie uzbroić wyjście. **Zatrzymaj** jest dostępne także podczas oczekującego automatycznego startu i anuluje ten zamiar. Po zatrzymaniu przy zachowanym strumieniu użyj **Wznów** lub **Wznów próbne** — bez ponownego łączenia, z zachowaniem ostatniego działającego trybu. **Połącz ponownie** w Diagnostyce wymusza nową sesję BLE. W konfiguratorze wybierz tryb wyjścia jawnie.

**Zmiana funkcji nie wymaga ponownego połączenia.** Na ekranie urządzenia użyj listy **Funkcja** albo wróć do **Menu** i uruchom inny profil. Istniejąca sesja BLE i strumień pozostają te same; aplikacja zwalnia stare wejścia i przełącza mapowanie/wyjście. Podczas trwającego skanowania lub łączenia nowa funkcja użyje już rozpoczętej próby, bez drugiego połączenia. Błąd przełączenia zatrzymuje wyjście i zgłasza problem — nie wymusza rozłączenia BLE. **Połącz ponownie** jest naprawą połączenia, nie standardowym sposobem zmiany funkcji.

Normalne zatrzymanie, zmiana profilu, rozłączenie i zamknięcie zwalniają przytrzymywane wejścia oraz neutralizują osie. Błędy czyszczenia są zgłaszane. Nie jest to gwarancja zwolnienia wejścia po wymuszonym ubiciu procesu lub awarii systemu. Zatrzymanie nie służy do przywracania wcześniejszej głośności systemu.

## Menu główne i ekran urządzenia

### Menu główne

| Element | Jak używać |
| --- | --- |
| **Kierownica → Otwórz** | Pionowo trzymana nakładka: skręt, gaz i hamulec. Rozpoczyna BLE + Live. |
| **AirMouse → Otwórz** | Poziomo trzymana nakładka: prędkość kursora i kliknięcia. Rozpoczyna BLE + Live. |
| **Joystick → Otwórz** | Poziome, utrzymywane wychylenie drążka. Rozpoczyna BLE + Live, z ograniczeniami platformy. |
| **Multimedia → Otwórz** | Pokrętło głośności i sterowanie odtwarzaniem. Rozpoczyna BLE + Live. Nazwa komendy CLI to `music`. |
| **Konfigurator** | Otwiera edytor mapowania, progów i podgląd w tym samym procesie; zatrzymuje dotychczasowe wyjście. |
| **Utwórz skróty** | Zapisuje skróty uruchamiania w katalogach użytkownika; to nie zapis ustawień profilu. |

### Ekran wybranego urządzenia

- **Stan urządzenia:** połączenie BLE, tryb sterowania, przycisk, bateria/RSSI (jeżeli dostępne), liczba próbek i szczegóły błędu. **Hz** to częstotliwość otrzymywanych próbek, nie liczba FPS gry.
- **Funkcja:** przełącza Kierownicę, AirMouse, Joystick i Multimedia bez rozłączania urządzenia. W menu także widać stan zachowanego połączenia.
- **Wartości profilu:** kierownica w stopniach i pedały w %, prędkość kursora w px/s, wychylenie joysticka X/Y albo głośność z mapowania. To podgląd obliczeń, nie potwierdzenie reakcji zewnętrznej aplikacji.
- **Sterowanie / Przypisania / Diagnostyka:** podstawowe zadanie, własne klawisze i dane techniczne są rozdzielone. Multimedia pokazują wybór odtwarzacza i ulubionego; gesty rozwija się osobno. Diagnostyka zawiera szczegóły błędów, ponowne połączenie i rozłączanie. Długie komunikaty mają niezależne przewijanie, a dolne akcje pozostają dostępne.
- **Zapisz:** utrwala aktualne ustawienia; sama zmiana listy lub przełącznika działa w sesji, bez zapisu pliku.

| Przycisk | Działanie |
| --- | --- |
| **Połącz ponownie** | Rozłącza trwającą sesję, jeżeli trzeba, i uruchamia nowy skan BLE. |
| **Zatrzymaj** | Zatrzymuje i neutralizuje wyjście lub anuluje oczekujący start; zostawia połączenie BLE. |
| **Rozłącz** | Kończy BLE i wyjście. |
| **Menu** | Pyta o niezapisane zmiany, zatrzymuje sterowanie i wraca do menu głównego, **zachowując BLE**. Uruchomienie innej funkcji wykorzysta to połączenie. Anulowanie pytania pozostawia bieżący ekran i sterowanie bez zmian. |
| **Zamknij** | Kończy aplikację, z pytaniem o niezapisane zmiany. |

Przyciski menu/ekranu urządzenia można wybierać Tab i uruchamiać Enter/Spacją. Nowe listy w **Opcje sterowania** reagują także na strzałki. Nie są to globalne skróty do gry — działają na kontrolkach aplikacji mających fokus.

## Cztery tryby sterowania

Poniższe wartości to **domyślne ustawienia kodu**. Wcześniej zapisany `gui-settings.json` może je nadpisywać.

### Kierownica (`steering`, szybka komenda `wheel`)

Trzymaj nakładkę **pionowo**. Obracaj ją jak koło kierownicy. W domyślnym mapowaniu koło korzysta z **roll**, ze znakiem odwróconym (`wheel_sign=-1`), a nie z yaw.

| Ruch | Domyślny efekt |
| --- | --- |
| Skręt pionowo trzymanej nakładki | Kierownica; martwa strefa 10°, pełny skręt przy 90°. |
| Pochylenie do przodu — ujemny pitch | Gaz; martwa strefa 8°, pełny gaz przy 40°. |
| Pochylenie do tyłu — dodatni pitch | Hamulec; martwa strefa 8°, pełne hamowanie przy 40°. |
| Naciśnięcie fizycznego przycisku | Ustawia aktualną pozycję jako neutralną dla sterowania, o ile trzymanie przycisku pozostało **Domyślne**. |

Gaz i hamulec współdzielą pitch, ale mają **osobne** martwe strefy i zakresy. Można wyłączyć oś gazu lub hamulca w konfiguracji. Linux tworzy urządzenie `Triki Steering`; przypisanie jego osi w grze wykonaj w ustawieniach tej gry. Windows/macOS nie tworzą analogowej kierownicy — użyj własnych klawiszy opisanych niżej.

### AirMouse (`mouse`)

Trzymaj nakładkę **poziomo**. Pochylenie osi urządzenia X (pitch / akcelerometr X) porusza kursorem lewo/prawo; pochylenie Y (roll / akcelerometr Y) — góra/dół. **Nie jest to mysz sterowana samą prędkością żyroskopu.**

- Utrzymywane pochylenie powoduje ciągły ruch kursora. Powrót do neutralnej pozycji zatrzymuje ruch.
- Domyślnie: martwa strefa 10°, pełna prędkość przy 100°, prędkości X i Y po 1400 px/s; regulujesz je niezależnie.
- Jedno kliknięcie fizycznego przycisku → lewy przycisk myszy; dwa → prawy. Rozpoznawanie następuje po oknie ciszy wielokliku (domyślnie 0,40 s), więc reakcja nie musi być natychmiastowa.
- Własne przypisania trzymania/kliknięć mogą zastąpić te zachowania. Zmiana przypisania kierunku nie wyłącza sama w sobie analogowego ruchu kursora.

### Joystick (`plane`)

Trzymaj nakładkę **poziomo**. X korzysta z pitch, Y z roll. Wychylenie **pozostaje**, dopóki nie wrócisz do neutralnej pozycji; zatrzymanie ruchu ręki nie centruje drążka.

- Domyślnie: martwa strefa 6°, pełne wychylenie / krawędź ekranu przy 90°.
- Przy około 45° wychylenie jest mniej więcej w połowie zakresu.
- Fizyczny przycisk jest domyślnie przytrzymywanym spustem.
- Linux tworzy `Triki Joystick`. Osie ustaw w grze; dodatkowy absolutny kursor wymaga obsługi Wayland i ustawia pozycję względem środka wybranego ekranu.
- Windows/macOS mogą wysyłać wyłącznie jawnie ustawione klawisze/przyciski myszy w tym profilu. Nie powstaje joystick HID ani odpowiednik linuxowego absolutnego kursora.

W źródłowym CLI nie ma osobnej komendy `plane`: wybierz **Joystick** w GUI albo `emulate --profile plane`. Pakiet desktopowy ma dodatkowy szybki alias `TrikiController plane`.

### Multimedia (`media`, szybka komenda `music`)

Nakładka jest **pozioma**; działa jak bezkońcowe pokrętło. Przekręcanie yaw zmienia głośność od bieżącego poziomu odtwarzacza. Zakres jest ograniczony do 0–100%: nadmiar obrotu przy końcu zakresu nie tworzy „długu” — obrót w przeciwną stronę reaguje bez długiego odkręcania. Domyślny **Zakres głośności** to 40° dla zmiany o pełen zakres.

| Gest | Działanie |
| --- | --- |
| Obrót w prawo/lewo, blisko pozycji poziomej | Głośność odtwarzacza; samo przechylenie względem grawitacji nie jest pokrętłem yaw. |
| Jeden klik | Play/pause. |
| Dwa kliki | Następny utwór. |
| Trzy kliki | Poprzedni utwór. |
| Odwrócenie na drugą stronę i krótkie przytrzymanie | Wycisza odtwarzacz; obrót odwróconej nakładki reguluje **głośność systemu**. |
| Odwrócenie z powrotem | Przywraca zapamiętaną głośność odtwarzacza i wraca do jego sterowania; nie cofa ustawionej głośności systemu. |
| Potrząśnięcie | Zmienia odtwarzacz w trybie **Automatycznie**, jeśli włączono **Potrząśnięcie zmienia odtwarzacz**. To rozpoznanie ruchu żyroskopu X/Y, nie zwykły obrót pokrętła Z. |

Domyślne czasy: wieloklik 0,40 s, odwrócenie 0,11 s, przerwa między zmianami odtwarzacza 1,55 s. Potrząśnięcie jest domyślnie włączone. **Wyłączenie tego przełącznika wyłącza tylko zmianę odtwarzacza potrząśnięciem** — pokrętło, kliknięcia i odwrócenie pozostają aktywne.

#### Wybór odtwarzacza

1. Uruchom odtwarzacz; na Windows musi istnieć jego sesja audio.
2. W **Opcje sterowania → Odtwarzacz (wybór ręczny)** kliknij **Odśwież**.
3. Wybierz aplikację albo pozostaw **Automatycznie** (ustawienie domyślne).
4. Sprawdź komunikat i głośność przy małym ruchu. Kliknij **Zapisz**, jeśli chcesz zachować wybór i przełącznik potrząśnięcia.

Lista przechowuje identyfikator backendu, nie tylko nazwę widoczną na ekranie. **Odśwież** jedynie odczytuje listę: nie wybiera innego celu, nie zapisuje ustawień, nie włącza Live i nie ustawia głośności. Ręcznie wybrany cel pozostaje wybrany także po zniknięciu z listy — pojawi się jako **(niedostępny)**. W takim przypadku nie jest zastępowany innym odtwarzaczem ani głośnością systemu. Uruchom go ponownie, wybierz inny lub świadomie wróć do **Automatycznie**. Identyfikator może przestać pasować po ponownym uruchomieniu procesu/sesji audio.

Do zmiany celu potrząśnięciem używaj trybu **Automatycznie**. **Wybór ręczny blokuje zmianę gestem**: przełącznik potrząśnięcia jest wtedy nieaktywny, a GUI wyświetla wyjaśnienie. Po powrocie do **Automatycznie** wraca wcześniej ustawiona wartość przełącznika; nadal możesz wyłączyć gest. Automatyczny wybór zależy od backendu, nie od tego, którą kartę WWW aktualnie oglądasz.

#### Ulubiony odtwarzacz startowy

1. Uruchom aplikację multimedialną i wybierz ją na liście **Odtwarzacz (wybór ręczny)**.
2. Kliknij przycisk z **gwiazdką**. Stan **Ulubiony** oraz opis **Start: …** oznaczają wybrany cel startowy.
3. Kliknij **Zapisz**. Dopiero zapis utrwala gwiazdkę na kolejne uruchomienie Triki Controller; sama gwiazdka jest zmianą roboczą.
4. Po ponownym uruchomieniu Triki Controller zapisany ulubiony ma pierwszeństwo przed wcześniejszym ręcznym wyborem/Automatycznie.

W jednej konfiguracji jest **jeden ulubiony**. Wybranie gwiazdki przy innej aplikacji zastępuje poprzednią preferencję. **Usuń ulubiony** usuwa gwiazdkę także wtedy, gdy program nie jest aktualnie dostępny; zapisz tę zmianę, aby utrwalić usunięcie. Trybu **Automatycznie** nie można oznaczyć gwiazdką.

Ulubiony rozpoznawany jest po trwałej tożsamości aplikacji: ścieżce pliku wykonywalnego na Windows, identyfikatorze bundle na macOS lub `DesktopEntry` MPRIS na Linuxie — nie tylko po PID albo nazwie wyświetlanej. Brak takiej tożsamości daje komunikat zamiast zgadywania. Brak programu lub kilka pasujących instancji nie powodują sterowania innym odtwarzaczem; aplikacja zachowuje preferencję i ponawia rozpoznanie, gdy cel stanie się dostępny. Gwiazdka nie uruchamia samego programu multimedialnego.

Podczas bieżącej sesji możesz jawnie wybrać inny odtwarzacz albo **Automatycznie**, nie usuwając ulubionego. To nadpisanie działa do następnego uruchomienia Triki Controller. Sama zmiana gwiazdki nie przełącza bieżącego celu ani nie włącza Live. Priorytet startowy blokuje zmianę potrząśnięciem do czasu jawnego wyboru innego trybu/celu.

#### Różnice audio między systemami

- **Linux:** transport odtwarzania preferuje MPRIS i może używać globalnych klawiszy uinput jako rezerwy. Brak ręcznie wybranego odtwarzacza nie uruchamia zastępczego sterowania innym celem. Głośność wymaga zapisywalnego MPRIS albo obsługi strumienia **tej samej aplikacji** w adapterze; brak odpowiedniego celu jest zgłaszany, bez zmiany głośności innego programu. Dla Pear Desktop komunikaty wskazują włączenie **Plugins → Shortcuts (& MPRIS)**. Odwrócona nakładka używa osobnego adaptera `pactl` dla domyślnego wyjścia systemowego.
- **Windows:** głośność/wyciszenie wybranego procesu korzystają z Core Audio. W zwykłym trybie play/pause/next/previous są **globalnymi klawiszami multimedialnymi Windows**; ich odbiorca nie musi być tym samym procesem co ręcznie wybrana sesja głośności. Przy aktywnym priorytecie ulubionego globalny transport jest celowo blokowany: backend nie potrafi adresować tych komend do konkretnej aplikacji. Gwiazdka nie dodaje tej obsługi; głośność pozostaje adresowana do ulubionej aplikacji.
- **macOS:** sterowanie odtwarzaczem dotyczy uruchomionych Music/Spotify i wymaga Automation. Nie obiecuje obsługi innych aplikacji ani kart przeglądarki. Systemowe urządzenie o stałej głośności może odmówić regulacji.

## Własne przypisania przycisku i kierunków

Dla **Kierownicy**, **AirMouse** i **Joysticka** dostępne są oddzielne mapy w ekranie urządzenia oraz w odpowiedniej zakładce Konfiguratora. Multimedia mają własne gesty, nie tę mapę.

| Źródło w GUI | Sposób działania |
| --- | --- |
| **Przycisk (trzymanie)** | Trzyma wybrany klawisz/przycisk myszy do puszczenia fizycznego przycisku. |
| **Jedno kliknięcie / Dwa kliknięcia / Trzy kliknięcia** | Wysyła krótką akcję po rozpoznaniu liczby kliknięć i upływie okna ciszy. |
| **Ruch w lewo / Ruch w prawo** | Trzyma akcję przy wychyleniu koła, AirMouse lub drążka w odpowiednią stronę. |
| **Ruch do przodu / Ruch do tyłu** | Kierownica: gaz/hamulec. AirMouse/Joystick: odpowiedni kierunek osi Y. |

Wybierasz **Domyślne**, **Wyłączone**, **Mysz: lewy/prawy/środkowy** albo pojedynczy klawisz: A–Z, 0–9, strzałki, Spacja, Enter, Esc, Shift, Ctrl, Alt, Tab lub Backspace. Nie jest to edytor dowolnych makr ani wpisywania całych kombinacji jako tekstu.

- **Domyślne** zachowuje dotychczasową akcję; dla kierunków nie dodaje klawisza. Puste mapy również zachowują działanie profilu.
- **Wyłączone** tłumi przypisanie danego źródła. Dla trzymania przycisku wyłącza także jego domyślne zachowanie; dla kierunku **nie usuwa samej osi ani ruchu kursora**.
- Własne trzymanie przycisku (także **Wyłączone**) ma pierwszeństwo przed niejawnie dodawanymi kliknięciami AirMouse i zerowaniem Kierownicy. **Jawne** przypisania kliknięcia/dwukliku/trzykliku mogą mimo to współistnieć z własnym trzymaniem.
- Kierunek aktywuje akcję przy **20% przeliczonego wychylenia**, po istniejącej martwej strefie/kształtowaniu osi. Zwalnia ją przy spadku do **15% lub mniej**. To nie jest próg 20°.
- Zmiana mapy działa od razu i może ponownie otworzyć aktywne wyjście. Edytuj przy zatrzymanym sterowaniu i w neutralnej pozycji, potem sprawdź wynik w **Próbne** i zapisz jawnie.

**Przykład do gry obsługującej klawiaturę:** ustaw lewo → `Klawisz: A`, prawo → `Klawisz: D`, przód → `Klawisz: W`, tył → `Klawisz: S`; trzymanie → `Klawisz: Spacja`. W grze przypisz te same klawisze. Jeżeli dodatkowo ustawisz jedno kliknięcie → Enter, po puszczeniu Spacji i zamknięciu okna wielokliku może wystąpić także Enter.

**Windows/macOS:** w Kierownicy/Joysticku wybierz przynajmniej jedną konkretną akcję klawisza lub przycisku myszy. Same **Domyślne/Wyłączone** nie uruchamiają trybu samych przypisań. Natywny backend wysyła wtedy wyłącznie te wejścia, nie analogowe osie. Domyślny spust Joysticka jest w tym trybie nieaktywny — jeśli chcesz używać przycisku, przypisz mu jawnie klawisz lub przycisk myszy. Przywrócenie wszystkiego do domyślnych może ponownie dać błąd nieobsługiwanej analogowej kierownicy/joysticka. Na Linuksie przypisania mogą współistnieć z dotychczasowymi osiami.

## Konfigurator krok po kroku

Otwórz **Konfigurator** z menu albo `triki-controller config`. Otwarcie zatrzymuje wcześniejsze wyjście; nie zaczyna automatycznie sterowania systemem. Po lewej stronie są następujące strony:

| Strona | Zastosowanie |
| --- | --- |
| **Podgląd** | Połączenie, przyciski wyjścia oraz karty sensorów, pochylenia i reakcji profilu. Zacznij tu od sprawdzenia strumienia. |
| **Konfiguracja** | Połączenie/wyjście, zakładki czterech profili, mapowanie osi, progi, własne opcje, zapis, zerowanie i kalibracja. Niżej podgląd mapowania i szczegółowe kanały czujników. |
| **Profile** | Wybór aktywnego profilu sesji. Zakładki edytora konfiguracji również przełączają profil używany w podglądzie. |
| **Ustawienia** | Ścieżka pliku ustawień, informacja o niezapisanych zmianach, tworzenie skrótów oraz połączenie. |
| **Informacje** | Wersja aplikacji i krótki opis potoku; nie jest to raport akceptacji sprzętu. |
| **← Menu główne** | Powrót do menu (w panelu otwartym przez `gui`), z pytaniem o niezapisane zmiany. |

### Mapowanie i progi

1. Wybierz zakładkę **Kierownica**, **AirMouse**, **Joystick** lub **Multimedia**. Zmiana zakładki stosuje szkic do sesji/podglądu.
2. Wybierz źródła osi. Pitch to pochylenie, roll to przechył, yaw to względny obrót. W AirMouse/Joysticku etykiety **Oś X (lewo/prawo)** i **Oś Y (przód/tył)** odpowiadają pitch/roll.
3. Dostosuj parametry w małych krokach. Większa martwa strefa tłumi drobne drżenie, większy pełny zakres wymaga większego wychylenia. Martwa strefa musi być mniejsza od odpowiadającego jej pełnego zakresu; błędna kombinacja daje komunikat.
4. Sprawdź wynik na kartach/mapowaniu. Dopiero potem przejdź do Live i użyj **Zapisz**.

| Zakładka | Pola i ich znaczenie |
| --- | --- |
| **Kierownica** | **Oś kierownicy**, **Oś gazu**, **Oś hamulca** wybierają pitch/roll/yaw (pedały również **Wyłączone**). **Kierunek kierownicy/gazu/hamulca** zmienia znak. Osobne suwaki **Strefa martwa…** i **Pełny skręt/Pełny gaz/Pełne hamowanie** ustawiają trzy niezależne zakresy. |
| **AirMouse** | **Kursor lewo/prawo**, **Kursor przód/tył** wybierają źródła. **Strefa martwa pochylenia**, **Pełne pochylenie** kształtują prędkość; **Prędkość X/Y** podaje maksymalną prędkość w px/s; **Znak X/Y** odwraca kierunek. |
| **Joystick** | **Lewo/prawo**, **Przód/tył** wybierają źródła. **Strefa martwa**, **Krawędź ekranu** określają wychylenie; **Znak X/Y** odwraca kierunek. |
| **Multimedia** | **Oś głośności**, **Kierunek głośności**, **Zakres głośności** ustawiają pokrętło. **Okno wielokliku** to czas rozróżniania kliknięć; **Czas odwrócenia** zabezpiecza przed krótkim przypadkowym odwróceniem; **Przerwa między zmianą odtwarzacza** ogranicza częstość potrząśnięć. Niżej jest ręczny odtwarzacz/przełącznik gestu. |

**Odwróć pitch / Odwróć roll** u góry odwracają znak na poziomie profili. Znak konkretnej osi jest dodatkowym odwróceniem — nie zmieniaj obu naraz, jeśli próbujesz ustalić właściwy kierunek. Dane akcelerometru w zliczeniach i m/s² oraz żyroskopu w zliczeniach, rad/s i °/s służą diagnostyce; listy mapowania bieżącego GUI wybierają pochylenia, nie surowe zliczenia.

### Zapis, domyślne, zerowanie i kalibracja

| Przycisk | Działanie i instrukcja |
| --- | --- |
| **Zapisz** | Waliduje i zapisuje ustawienia wszystkich profili z formularza; aktywny profil odpowiada wybranej zakładce. |
| **Domyślne tego profilu** | Przywraca źródła osi, znaki osi i suwaki wybranej zakładki w szkicu; nie zapisuje automatycznie. Nie jest resetem całego pliku ani nowo dodanych przypisań/wyboru odtwarzacza — te przywróć osobno. |
| **Wyzeruj pozycję** | Przy połączonym strumieniu ustawia bieżącą pozycję jako punkt odniesienia. Najpierw ustaw rękę/nakładkę w zamierzonym położeniu neutralnym. |
| **Kalibruj żyroskop** | Przy połączonym BLE zbiera około 1,5 s nieruchomych próbek do oszacowania biasu. Połóż nakładkę stabilnie i nie ruszaj nią. Zbyt mało próbek/ruch powoduje odrzucenie i zachowanie poprzedniego biasu. |

Kalibracja usuwa stały błąd żyroskopu w sesji; **nie jest tym samym co zerowanie pozycji** i nie jest zapisywana w pliku ustawień jako trwała kalibracja sprzętu. Sześcioosiowa IMU nie dostarcza absolutnego kierunku świata: yaw jest względny i może dryfować. Pitch/roll korzystają z grawitacji. Zerowanie i kalibracja nie zamieniają urządzenia w kompas.

Orientacja montażu w bieżącym GUI jest wymuszana przez profil: Kierownica pionowo, pozostałe poziomo. Nie szukaj w formularzu dawnej listy obrotu montażu. Parametr CLI `emulate --orientation` / `--rotation` obsługuje `horizontal`, `yaw_90`, `yaw_180`, `yaw_270`, `vertical`, `vertical_180` (aliasy `poziomo`, `pionowo`, `90`, `180`, `270`); jest ignorowany dla media/mouse/steering i może służyć do diagnostycznego remapowania profilu plane. Remapowanie występuje przed filtrem, niezależnie od odwracania znaków.

## Zapis ustawień

Domyślna ścieżka to:

```text
~/.config/triki-controller/gui-settings.json
```

Jeżeli ustawiono `XDG_CONFIG_HOME`, aplikacja używa `<XDG_CONFIG_HOME>/triki-controller/gui-settings.json`. Ten sam mechanizm `Path.home()/.config` jest stosowany także w źródłowym uruchomieniu Windows/macOS; dokładną ścieżkę zobaczysz w **Ustawienia**. Możesz wskazać własny plik, np.:

```bash
triki-controller gui --settings ./moje-ustawienia.json
```

- Zmiana osi, suwaka, przypisania, przełącznika lub ręcznego celu działa **natychmiast w sesji**, lecz plik jest utrwalany wyłącznie przez **Zapisz**.
- Sam wybór szybkiego profilu, odświeżenie odtwarzaczy, połączenie, Stop czy stworzenie skrótu nie zapisują konfiguracji.
- Zamknięcie / powrót do menu z niezapisanymi zmianami pyta o potwierdzenie. Nie traktuj tego pytania jako automatycznego zapisania ani cofnięcia zmian już zastosowanych w sesji.
- Zapisywane są profil, orientacja, odwrócenia, mapy osi/progi, przypisania, włączenie potrząśnięcia, identyfikator ręcznego odtwarzacza i trwała tożsamość ulubionego celu startowego. **Połączenie i stan Live nie są zapisywane.** Szybkie komendy uruchamiają Live z własnej logiki, nie z pliku.
- Starsze poprawne ustawienia są nakładką na domyślne wartości; dawne źródła `gyro_*` myszy/joysticka są migrowane na pochylenia X/Y. Zachowane niestandardowe wartości mogą różnić się od tabeli domyślnych.
- Niepoprawny plik w uruchomieniu GUI daje informację o pominięciu i start z domyślnymi wartościami. Zrób kopię przed ręczną edycją; nie nadpisuj bez namysłu pliku, który został pominięty.

## Skróty i zasobnik systemowy

### Skróty uruchamiania

**Utwórz skróty** w menu oraz **Utwórz skróty pulpitu** w Ustawieniach kierują do bieżącej instalacji. Wersja źródłowa tworzy panel, AirMouse, Kierownicę i Multimedia; pakiet desktopowy dodatkowo Konfigurator, Plane i Tray.

```bash
# Wersja źródłowa / instalacja pip
triki-controller shortcuts --dry-run
triki-controller shortcuts
# Opcjonalnie: wszystkie skróty w jednym wskazanym katalogu
triki-controller shortcuts --dest ./skroty
```

| System | Lokalizacja i typ |
| --- | --- |
| Linux | `~/.local/share/applications` i pulpit z `XDG_DESKTOP_DIR` w `user-dirs.dirs` (w przeciwnym razie `~/Desktop`); pliki `.desktop`. |
| Windows | Pulpit i menu Start użytkownika; źródłowo `.bat` oraz `.lnk`, gdy utworzy go PowerShell; pakiet desktopowy tworzy `.lnk`. |
| macOS | Pulpit i `~/Applications`; wykonywalne pliki `.command`. |

Skróty źródłowe wskazują używany Python i w checkoutcie ustawiają `PYTHONPATH=src`. Skróty pakietu wskazują bezpośrednio jego plik wykonywalny. Ikona Linux `.desktop` korzysta z PNG; Windows z ICO, `.app` macOS z ICNS. Środowisko Linux może wymagać **Zezwól na uruchamianie** dla lokalnego skrótu.

Pakiet ma osobne polecenie z jawnym katalogiem docelowym (przykład Linux, z katalogu rozpakowanego programu):

```bash
./TrikiController install-shortcuts --dest "$HOME/.local/share/applications"
```

`install-shortcuts` i `--tray` należą do wejścia pakietu desktopowego, nie zwykłego `triki-controller` z pip.

### Zasobnik (tray)

Szybkie komendy okienkowe próbują uruchomić opcjonalny zasobnik. Okno chowa się dopiero, gdy backend potwierdzi działającą ikonę. Jeżeli `pystray`, wymagane biblioteki lub host zasobnika są niedostępne, **okno pozostaje widoczne**. Linux wymaga AppIndicator i działającego StatusNotifierWatcher; obsługa zależy od środowiska pulpitu.

Menu ikony zawiera **Pokaż okno**, **Ukryj okno**, **Zakończ**. Ukrycie okna **nie zatrzymuje sterowania**. Krzyżyk w szybkim oknie chowa je do działającego zasobnika; przy niedostępnym zasobniku kończy aplikację. Przycisk **Zamknij** i menu **Zakończ** kończą ją normalnie, z pytaniem o niezapisane zmiany.

W pakiecie można także uruchomić panel z zasobnikiem:

```bash
./TrikiController gui --tray
```

Nie łącz `--tray` z `--no-window`. Gdy program zniknął z ekranu, najpierw sprawdź ikonę zasobnika, zamiast uruchamiać drugą instancję łączącą się z tą samą nakładką.

## CLI i diagnostyka

### Panel i szybkie tryby

```bash
triki-controller gui
triki-controller config
triki-controller gui --transport ble --connect --dry-run
triki-controller mouse
triki-controller wheel
triki-controller music
triki-controller mouse --dry-run
triki-controller mouse --dry-run --no-window
```

`--connect` rozpoczyna łączenie po otwarciu panelu/konfiguratora. `gui --live` i `gui --dry-run` uzbrajają wybrany tryb po strumieniu; wzajemnie się wykluczają. Szybkie komendy domyślnie łączą BLE + Live, `--dry-run` to zmienia, a `--no-window` drukuje stan w konsoli (zakończ Ctrl+C). Dostępne są też wejścia `triki-controller-gui`, `triki-controller-config`, `triki-controller-mouse`, `triki-controller-wheel`, `triki-controller-music`.

### RAW: monitor i zapis

Offline, bez BLE i bez sterowania systemem:

```bash
PYTHONPATH=src python3 -m triki_controller.cli.main monitor --transport fake --samples 8
PYTHONPATH=src python3 -m triki_controller.cli.main record --transport fake --samples 8 --out recordings/demo
PYTHONPATH=src python3 -m triki_controller.cli.main monitor --transport fake --samples 8 --reconnect-after 4 --malformed --split-frames
```

Z fizycznej nakładki (podczas skanu naciśnij raz przycisk):

```bash
triki-controller monitor --transport ble --samples 50 --scan-timeout 30
triki-controller record --transport ble --samples 50 --out recordings/triki
```

`record` zapisuje `raw_samples.csv` i `session.json` w podanym katalogu; używaj nowego katalogu, aby nie zastąpić wcześniejszego nagrania. `--samples 0` dla BLE oznacza pracę bez limitu próbek do zakończenia połączenia/przerwania. `--session-id` nadaje identyfikator sesji. `--reconnect-after`, `--malformed`, `--split-frames` służą tylko transportowi fake.

**Fake jest dostępny w monitor/record, nie jako źródło w głównym GUI.** Offline działa syntetyczny protokół `synthetic-v0`; BLE używa parsera CAP001 `reference-hypothesis`.

### Emulacja w konsoli

```bash
# BLE + ślad mapowania; bez zdarzeń systemowych
triki-controller emulate --profile steering --transport ble --samples 50
triki-controller emulate --profile plane --transport ble --samples 50
# BLE + rzeczywiste wyjście platformy — tylko po przygotowaniu uprawnień
triki-controller emulate --profile mouse --transport ble --live
triki-controller emulate --profile media --transport ble --live
```

`emulate` wymaga BLE; bez `--live` używa śladu dry-run. `--invert-pitch` i `--invert-roll` zmieniają znaki. Domyślnie odczytuje istniejący plik GUI dla progów i mapowania osi; `--settings` wskazuje konkretny plik. **Bieżąca ścieżka `emulate` nie przekazuje nowych przypisań `control_bindings`, wyboru `media_player` ani przełącznika `media_gestures_enabled` do runtime.** Do tych opcji używaj GUI lub szybkich komend sesji (`mouse`, `wheel`, `music`; Plane przez GUI/pakiet). Jawnie wskazany błędny/brakujący plik `emulate` daje błąd zamiast poprawnej emulacji.

### Co oznacza potok

```text
RAW → FILTERED → PROFILE MAPPING → FINAL OUTPUT
```

| Etap | Co sprawdzasz |
| --- | --- |
| **RAW** | Odebrane i sparsowane zliczenia akcelerometru/żyroskopu, przycisk, identyfikatory próbek/ramek i dostępne metadane. |
| **FILTERED** | Przeliczone jednostki, orientację montażu, filtrowane pochylenie i względną orientację po uwzględnieniu biasu. |
| **PROFILE MAPPING** | Jak wybrany profil zamienił ruch na osie, delty kursora, trzymane wejścia i impulsy. |
| **FINAL OUTPUT** | Wynik zastosowania mapowania przez backend; w dry-run to ślad, a w Live próba wyjścia systemowego. |

`monitor`/`record` udostępniają RAW, a dalsze etapy pozostawiają niedostępne. GUI może pokazywać ruch/mapowanie bez uzbrojonego wyjścia; **Stop** wyłącza wysyłanie, nie sam odbiór BLE. `emulate` uruchamia cały potok. `OUT applied=True` w dry-run ani poprawny wykres nie są dowodem wejścia do gry. W Live przeczytaj również błędy backendu i sprawdź aplikację docelową. Brak baterii, RSSI, ticka czy kwaternionu pozostaje **niedostępne**, a nie wymyślonym zerem.

## Rozwiązywanie problemów

| Objaw | Co sprawdzić |
| --- | --- |
| Nakładka nie znaleziona / timeout | Bluetooth włączony, pojedyncze naciśnięcie podczas skanu, zasięg, zamknięty TrikiScope/inne instancje. Użyj **Połącz ponownie**; CLI pozwala zwiększyć `--scan-timeout`. |
| Połączenie jest, lecz brak reakcji systemu | Czy **Sterowanie** jest Live, a nie Próbne/Wyłączone? Czy masz wymagane uprawnienia? W grze skonfiguruj odbiór właściwych osi/klawiszy. |
| Po Stop nie można wznowić z szybkiego ekranu | **Połącz ponownie**, ponownie obudź Triki; albo **Menu → Uruchom**. W konfiguratorze wybierz **Na żywo** przy działającym strumieniu. |
| Linux: odmowa dostępu/brak `/dev/uinput` | Sprawdź moduł i reguły dostępu z administratorem; instalacja pip nie nadaje uprawnień urządzenia. |
| Joystick porusza osią, ale nie absolutnym kursorem Linux | Sprawdź status Wayland i obsługę protokołów przez kompozytor; uinput joystick i absolutny kursor są różnymi ścieżkami. |
| Windows: sterowanie nie trafia do podwyższonej aplikacji | Możliwe ograniczenie UIPI. Sprawdź poziom uprawnień celu; nie traktuj uruchamiania wszystkiego jako administrator jako domyślnego rozwiązania. |
| macOS: mysz lub odtwarzacz odmawia działania | Sprawdź Accessibility/Automation dla faktycznie uruchomionego procesu/.app; uruchom Music/Spotify. Zgoda nie wynika z samego podpisu/pakietu. |
| Windows/macOS: Kierownica/Joystick odrzucony | Nie ma analogowego wirtualnego HID. Ustaw konkretną własną akcję w **Opcje sterowania** i użyj trybu samych przypisań lub Próbne. |
| Głośność nie działa / cel **(niedostępny)** | Uruchom wybrany odtwarzacz/sesję audio, odśwież listę i odczytaj błąd. Wybierz nowy cel jawnie; nie oczekuj automatycznej podmiany ręcznie przypiętego celu. |
| Windows: głośność jednego programu, play/pause innego | Klawisze transportu są globalne i nie są przypięte do wybranej sesji Core Audio. |
| Linux: MPRIS bez zapisywalnej głośności | Sprawdź obsługę odtwarzacza i `playerctl`; ewentualny strumień musi należeć do tej samej aplikacji. Dla Pear włącz wskazany plugin MPRIS. |
| Systemowe audio nie reaguje po odwróceniu | Linux: `pactl` i domyślne wyjście; Windows: endpoint Core Audio; macOS: urządzenie o regulowanej głośności. Brak player volume nie jest automatycznym przejściem do system volume. |
| Przypadkowa zmiana odtwarzacza | Wyłącz **Potrząśnięcie zmienia odtwarzacz** albo zwiększ przerwę między zmianami; kliknij **Zapisz**. |
| Przycisk przestał zerować / klikać jak wcześniej | Sprawdź przypisanie **Przycisk (trzymanie)** i jawne kliknięcia. Własne trzymanie ma pierwszeństwo przed domyślnymi akcjami. |
| Kliknięcie reaguje z opóźnieniem | Rozpoznanie wielokliku czeka na okno ciszy. Sprawdź jego wartość i przypisania. |
| Koło/kursor ma zły kierunek lub dryf | Sprawdź fizyczny montaż, źródła i znaki, wyzeruj pozycję; skalibruj żyroskop na nieruchomej nakładce. Yaw nie jest kierunkiem świata. |
| Zmiany znikają po ponownym starcie | Użyj **Zapisz** i sprawdź ścieżkę/komunikat zapisu. Sama edycja i wybór profilu nie utrwalają pliku. |
| Brak okna / CustomTkinter / DISPLAY | Sprawdź środowisko Pythona, zależności GUI, systemowy Tk i sesję graficzną. `mouse/wheel/music --no-window` to alternatywa konsolowa; nadal używa BLE. |
| Aplikacja znika, ale nadal steruje | Sprawdź zasobnik: ukrycie nie zatrzymuje wyjścia. **Pokaż okno → Zatrzymaj sterowanie** albo **Zakończ**. |
| Skrót po przeniesieniu programu nie działa | Odtwórz skróty po umieszczeniu całego pakietu w finalnym katalogu; nie usuwaj `_internal/`. |
| System blokuje pobrany pakiet | Sprawdź pochodzenie, architekturę i informacje o podpisie; skontaktuj się z wydawcą. Nie wyłączaj mechanizmów bezpieczeństwa. |

## Budowanie i weryfikacja dla programistów

PyInstaller buduje **na systemie docelowym**, nie jest kompilatorem skrośnym. Linux nie tworzy działającego `.exe`/`.app` dla innych systemów. Z katalogu repozytorium, po instalacji `packaging/requirements-desktop.txt`:

```bash
# Linux
.venv/bin/python tools/build_desktop.py --target linux
# macOS, na macOS
.venv/bin/python tools/build_desktop.py --target darwin
# Podgląd komendy bez budowania/zapisu, dla systemu gospodarza
.venv/bin/python tools/build_desktop.py --command-only
```

```powershell
# Windows, na Windows
.\.venv\Scripts\python.exe tools/build_desktop.py --target win32
```

Dodaj `--smoke` tylko na komputerze z sesją graficzną. Smoke uruchamia próbki fake i okno dry-run w izolowanym środowisku; **nie certyfikuje BLE, fizycznego kontrolera, zasobnika, audio ani uprawnień natywnych**. `--console` na Windows/macOS zachowuje konsolę do diagnostyki; na macOS tworzy diagnostyczny plik wykonywalny zamiast domyślnej `.app`.

| System | Wynik w `packaging/dist/` |
| --- | --- |
| Linux | `TrikiController/TrikiController` + `_internal/`, archiwum `TrikiController-linux-<arch>.tar.gz` |
| Windows | `TrikiController/TrikiController.exe` + zależności, archiwum `TrikiController-win32-<arch>.zip` |
| macOS | `TrikiController.app`, archiwum `TrikiController-darwin-<arch>.zip` |

Raport budowania jest w `packaging/build/build-report.json`. Dystrybuuj **całe archiwum**, nie sam bootloader. Budowanie nie wykonuje notaryzacji, nie przyznaje uprawnień i nie zapisuje preferencji użytkownika.

Bez fizycznego BLE można sprawdzić CLI zbudowanego pakietu Linux:

```bash
packaging/dist/TrikiController/TrikiController --help
packaging/dist/TrikiController/TrikiController monitor --transport fake --samples 4
```

Testy programistyczne:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Testy syntetyczne używają sztucznych ramek, testy natywnych adapterów używają również atrap/inertnych adapterów. Ich powodzenie nie dowodzi działania SendInput/Core Audio/Quartz/AppleEvents ani prawdziwej gry/odtwarzacza. Testy fizycznego wyjścia i narzędzia acceptance wymagają **jawnej zgody/opt-in** na docelowym hoście — nie uruchamiaj ich jako niewinnego testu dokumentacji. Przed uznaniem wydania za zaakceptowane sprawdź osobno BLE, montaż, osie, własne przypisania, docelowe audio, zwalnianie wejść oraz uprawnienia na każdym systemie.

Szczegóły implementacji i budowania: [native-output-platforms](docs/native-output-platforms.md), [native-desktop-build](docs/native-desktop-build.md), [desktop-distribution](docs/desktop-distribution.md). Starsze raporty są zapisem konkretnego etapu prac, nie automatyczną gwarancją dla bieżących opcji; bieżące możliwości opisuje kod i ta instrukcja (np. nowy tryb samych przypisań nie oznacza wsparcia analogowego HID Windows/macOS).

## Ikona, struktura i licencje

Oficjalna ikona to neonowy, low-poly emblemat kontrolera ze znakiem Y. Źródło i wygenerowane warianty znajdują się w `src/triki_controller/gui/assets/app_icon/`:

| Plik | Zastosowanie |
| --- | --- |
| `source.jpg` | Oryginalny emblemat 1024×1024 |
| `triki-controller.png` | PNG 512×512: okno Tk, zasobnik, `Icon=` skrótów Linux |
| `triki-controller-<size>.png` | Warianty 16, 24, 32, 48, 64, 128, 256 i 1024 |
| `triki-controller.ico` | Skróty i pakiet Windows |
| `triki-controller.icns` | Ikona pakietu `.app` macOS |

Po wymianie źródła można wygenerować warianty poleceniem `python3 tools/render_app_icon.py`. Tk używa `iconphoto` (Windows dodatkowo `iconbitmap`); ELF Linux nie ma osadzonej ikony jak pakiet Windows/macOS — korzysta z PNG w skrótach.

| Katalog | Rola |
| --- | --- |
| `src/triki_controller/core` | Modele danych |
| `protocol`, `transport`, `recording` w pakiecie | Parsery synthetic-v0/CAP001, transport fake/Bleak BLE, RAW CSV i metadane sesji |
| `motion`, `profiles`, `runtime` | Orientacja/filtr, profile i przypisania, potok i cykl życia wyjścia |
| `output` | Ślad dry-run, uinput, natywne wejście/audio Windows/macOS |
| `gui`, `cli` | Okna, konfigurator, ustawienia, zasobnik, skróty i polecenia |
| `packaging`, `tools` | Zależności/build desktopowy oraz narzędzia weryfikacji |

Projekt deklaruje licencję **Proprietary**. Fragmenty transportu BLE i parsera CAP001 pochodzą z TrikiScope na licencji MIT; wymagane informacje zachowano w [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Zasoby ikon interfejsu Phosphor mają własną [licencję](src/triki_controller/gui/assets/phosphor/LICENSE) i metadane źródła w tym samym katalogu. Nie należy utożsamiać licencji zależności z licencją całego projektu.
