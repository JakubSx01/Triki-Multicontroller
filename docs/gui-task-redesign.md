# Przebudowa GUI — hierarchia zadań i bezpieczna weryfikacja

## Zakres i wynik

Przebudowany natywny shell CustomTkinter: menu funkcji, ekran sterowania i dodatkowe opcje. Nie zmieniono BLE, sesji, profili/mapowania, audio, adapterów wyjścia ani formatu zapisanych ustawień. Nie instalowano pakietów, nie zmieniano konfiguracji Niri, nie wykonano commit/push/release.

Oryginalny konfigurator, jego pola, walidatory, mapowania, kalibracja, kolekcje formularza i globalny jasny motyw pozostają chronione. Ciemne kolory są lokalne dla nowego shella. `ControlOptions(compact=True)` jest stosowane tylko na ekranie sterowania; domyślne oryginalne `_build()` w konfiguratorze pozostaje bez zmian.

## Uzasadnienie projektowe i źródła

Źródła zostały odczytane online, nie tylko przywołane z pamięci. Badanie rodzica poprzedziło edycje; wykonawca dodatkowo odczytał Apple przed pierwszą edycją oraz NN/g i W3C podczas prac. Lokalna baza ui-ux-pro-max zwróciła niepasujący wzorzec landing page; nie zastosowano go. Zastosowano jej ogólne reguły desktopowe jako jawny fallback, nie jako dopasowanie do CustomTkinter.

- [NN/g: Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/) — podstawowe zadanie na początku, rzadkie funkcje w oznaczonej drugiej warstwie. Przypisania są osobną zakładką, techniczne próbki/RSSI i rozłączanie znajdują się w Diagnostyce; polityka gestów jest rozwijana na żądanie.
- [NN/g: 10 Usability Heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/) — widoczny stan, język użytkownika, rozpoznawalne działania, droga powrotu i wskazówka naprawy błędu. Połączenie i sterowanie są odrębnymi stanami.
- [Apple HIG: Buttons](https://developer.apple.com/design/human-interface-guidelines/buttons), odczyt treści przez [oficjalny JSON](https://developer.apple.com/tutorials/data/design/human-interface-guidelines/buttons.json) — Apple zaleca ograniczenie prominentnych przycisków do jednego lub dwóch. Tutaj preferowana jest jedna akcja zadania: Połącz/Wznów. Zatrzymaj, Rozłącz i Zamknij nie są akcjami głównymi.
- [W3C: Contrast Minimum](https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum.html) — testy sprawdzają co najmniej 4.5:1 dla normalnego tekstu i 3:1 dla ikon/granic na obu ciemnych powierzchniach.
- [W3C: Focus Appearance](https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html) — inspiracja dla widocznych obramowań fokusu; jest to kryterium AAA, nie deklaracja certyfikacji aplikacji. Użyto obramowania 2 px, Tab, Return/Spacja i ujawniania przewiniętego pola przy fokusie.

Nie przeprowadzono badania z reprezentatywnymi użytkownikami. Heurystyczna przebudowa i testy Tk nie są takim badaniem ani audytem zgodności całej aplikacji.

## Nowe przepływy

1. **Wybór funkcji:** opisowe karty; akcent tylko przy bieżącym profilu zamiast czterech równorzędnych niebieskich działań. Konfigurator i skróty nadal są dostępne.
2. **Sterowanie:** stała górna nawigacja Menu/Konfigurator; wybór funkcji bez rozłączenia BLE; zwięzły stan oraz następny krok. Próbki, bateria/RSSI i ponowne łączenie nie zajmują domyślnego widoku.
3. **Połącz / Wznów / Stop:** Połącz używa istniejącego retry tylko w stanie rozłączonym/błędu; podczas łączenia jest nieaktywne. Wznów wymaga STREAMING oraz wyłączonego wyjścia i używa istniejących `_on_dry`/`_on_live`, zachowując ostatni aktywny tryb zamiast wybierać go ponownie z flagi konstruktora. Zatrzymaj jest dostępne dla aktywnego wyjścia **lub oczekującego zamiaru autostartu**, także przy OFF + CONNECTING/SCANNING. Stop anuluje autostart bez rozłączania BLE; późniejsze STREAMING nie uruchamia wyjścia. Zmiana funkcji nadal może ponownie uzbroić wyjście, zgodnie z wcześniejszym kontraktem.
4. **Przypisania:** domyślny widok nie wyświetla ośmiu menu naraz. Oddzielna zakładka dla profili sterowania i jednowierszowe przypisania zamiast ciasnej siatki dwóch par kolumn. Multimedia nie pokazują pustej zakładki przypisań.
5. **Multimedia:** aktualny cel sesji, ręczny wybór/odświeżenie, podpisana gwiazdka i usunięcie ulubionego. „Następny start” pozostaje oddzielony od aktualnej sesji. Polityka gestów jest rozwijana; priorytet ulubionego/ręcznego wyboru, niedostępny odtwarzacz i fail-closed pozostają w istniejącej logice.
6. **Zapis:** stały dolny pasek, zawsze osiągalny; widoczny komunikat o niezapisanych zmianach. Nie dodano autosave. Anulowanie nawigacji do Menu lub Konfiguratora nie zatrzymuje sterowania ani nie rozłącza BLE.

Małe okno celowo przewija drugorzędną treść. Częściowo widoczna kolejna karta/sekcja w obszarze przewijania nie oznacza utraty funkcji: testy fokusu docierają do ostatniej karty menu, ostatniego przypisania i gestów. Zapis/Stop znajdują się poza obszarem przewijania.

## Zmienione pliki

- `src/triki_controller/gui/shell_presentation.py` — architektura zadań, nawigacja, lokalne tokeny, zakładki, stan przycisków, footer i zawijanie tekstu.
- `src/triki_controller/gui/control_options.py` — wyłącznie opcjonalna adaptacja shella: układ pojedynczej kolumny, mniejszy szum wizualny i ujawnianie gestów. Oryginalna budowa i callbacki zachowane.
- `src/triki_controller/gui/desktop.py` — minimalna integracja: minsize 520×600, jawny rodzic edytora zamiast `pack_slaves()[2]`, odświeżanie prezentacji przycisków.
- `tests/test_gui_shell_modern.py` — migracja tylko testu prezentacji sześciu jednoczesnych przycisków do stałego paska i ujawnianej Diagnostyki. Wszystkie guardy hash, fontu, motywu i konfiguratora pozostają nienaruszone.
- `tests/test_gui_task_shell.py` — 18 nowych przypadków rzeczywistego Tk: profile/rozmiary, stateful Stop/Resume, pending connection, klawiatura, fokus, jawny zapis, anulowanie nawigacji i gesty.
- `tests/test_device_switch_ui.py` — harness dla dwóch istniejących testów wymiarów/fokusu; oryginalne asercje zachowane, dodano pomiar żądanego rozmiaru.
- `tests/gui_tk_harness.py` — niezależny controlled client: `overrideredirect(True)` → native settling → żądanie geometrii → settling → dokładny pomiar. Polling wyłącza tylko zegary testowego GUI, nie zmienia konfiguracji Niri.
- `tests/test_gui_review_regressions.py` — 15 regresji realnego Tk: cztery anulowania pending Stop, cztery restart modes, pięć długości feedbacku, czyszczenie trace przy rebuildzie i pełne szczegóły błędu połączenia.
- `docs/gui-task-redesign.md` — niniejszy dokument. Nowe helper/testy i dokument są ignorowane przez reguły repozytorium; należy je uwzględnić jawnie przy ewentualnym późniejszym publikowaniu. Tutaj nic nie staged/commitowano.

## Rzeczywiste wykonanie

Interpreter: projektowe `.venv/bin/python`, `DISPLAY=:0`, `PYTHONPATH=src`. Sugerowany scratch-venv nie istniał. Xvfb i xvfb-run nie są zainstalowane; niczego nie doinstalowywano.

### Regresja końcowa

```sh
DISPLAY=:0 PYTHONPATH=src .venv/bin/python \
  /home/jakub/.hermes/cache/scratch/triki-redesign-test-runner.py \
  -q tests -k 'not test_mouse_steering_and_media_roundtrip and not test_uinput_media_routes_volume_to_mpris and not test_uinput_transport_falls_back_when_mpris_rejects'
```

Wcześniejszy pojedynczy przebieg dał **603 passed, 3 deselected, 89 subtests passed in 98.51s** (`/home/jakub/.hermes/cache/scratch/triki-redesign-full-final.log`). Nie był to wynik bezwarunkowo powtarzalny: niezależny pełny przebieg rodzica dał **2 failed, 601 passed, 3 deselected, 89 subtests passed in 106.96s** (`/home/jakub/.hermes/cache/scratch/triki-redesign-parent-full.log`): fokus zastępczego menu był `None`, a zarządzany klient zamiast 620×700 miał 948×1028.

Po poprawkach niezależnego review i deterministycznym settlingu harnessu końcowe wykonanie powyższej komendy: **618 passed, 3 deselected, 89 subtests passed in 138.75s**, kod wyjścia 0, bez skipów. Pełny log: `/home/jakub/.hermes/cache/scratch/triki-review-full-final.log`. Testy Tk uruchamiano sekwencyjnie, bez równoległych procesów GUI.

Trzy wskazane testy adapterów/hardware zostały wyłączone zgodnie z istniejącą bezpieczną procedurą. Runner globalnie zabrania prawdziwego evdev.UInput i konstruktorów BLE. Dialogi teardown akceptują odrzucenie wyłącznie tymczasowych draftów testowych; testy anulowania ustawiają swoje własne mocki. Pierwszy pełny przebieg z domyślnym anulowaniem teardown pozostawiał korzenie Tk i powodował `pyimage ... doesn't exist`; finalny runner naprawia warunki harnessu, nie kod produkcyjny ani kryteria testów. Zwykłe `pytest` bez ścieżki zbiera także osobny TrikiScope, którego pakiet nie znajduje się na PYTHONPATH; końcowy suite obejmuje właściwe `tests/` projektu.

`git diff --check` oraz `python -m compileall -q src/triki_controller/gui tests/test_gui_task_shell.py` zakończyły się poprawnie. Diff backendów, sesji i ustawień jest pusty. Oryginalne testy ochrony konfiguratora przechodzą bez zmiany digestów.

### Poprawki niezależnego review — red → green

- **P1:** red pokazał disabled Stop dla OFF + CONNECTING/SCANNING. Green: oba stany × dry/live intent; kliknięcie Zatrzymaj wyłącza autostart, dwa późniejsze odświeżenia STREAMING mają `start_calls=[]`, bez disconnectu/zapisu.
- **P2:** red przy 40 powtórzeniach komunikatu odmapował akcje. Feedback jest teraz readonly `CTkTextbox` o wysokości 64 px, z pełnym tekstem, własnym scrollem, Tab/focusem, zaznaczaniem/kopiowaniem i klawiaturowym Ctrl+End. Nie obcina błędów. Trace zmiennej `_status` jest usuwany razem z widgetem przy rebuildzie.
- **Drugi kanał błędów:** 1246 znaków w `_detail` także zasłaniało akcje przez nieograniczony hint u góry; osobny red `/home/jakub/.hermes/cache/scratch/triki-review-detail-red.log` (1 failed) to potwierdził. Krótki hint kieruje teraz do istniejącej, przewijalnej Diagnostyki. Test otwiera ją Return i weryfikuje pełny tekst oraz dostępność jego końca.
- **Restart mode:** Stop zapisuje ostatni nie-OFF tryb w istniejącym `_autostart.live`; Resume i jego etykieta czytają ten zamiar. Cztery kombinacje flagi konstruktora i poprzedniego trybu przechodzą: DRY_RUN zawsze wznawia `live=False`, LIVE zawsze `live=True`. LIVE jest wyłącznie intencją testowej sesji z in-memory sinkiem, bez rzeczywistego hardware/MPRIS.
- **Harness:** krótki rzeczywisty wait + `root.update()` przez 0.25 s pozwala odebrać natywne map/focus events. Remap kończy się **przed** geometry request. Obserwowane rozmiary muszą dokładnie odpowiadać żądanym; oryginalne asercje geometrii i fokusu zastępczego menu pozostały bez osłabienia. Są to controlled Xwayland clients, nie dowód polityki zarządzanego okna Niri ani Xvfb.

Log red `/home/jakub/.hermes/cache/scratch/triki-review-red-final.log`: **12 failed, 2 passed** przed poprawkami produkcyjnymi. Początkowy preparatory run używał TraceOutput, który prawidłowo odrzuca LIVE claims; poprawiono fixture na inert sink i wyłączono autostart przed ręcznym ustawieniem trybu. Pierwszy green ujawnił tylko brak `CTkTextbox.cget('state')`; readonly jest sprawdzane na rzeczywistym wewnętrznym Tk Text, bez osłabienia kryterium.

Końcowe celowane wykonanie: **41 passed in 70.06s**, `/home/jakub/.hermes/cache/scratch/triki-review-green-final.log`. Pomiary przy dokładnym 520×600 dla **37, 161, 316, 626 i 1246 znaków**: feedback **64 px**, wszystkie trzy akcje mapped i wewnątrz klienta, pełny tekst równy wejściu, końcowa linia widoczna po Ctrl+End. Testy obejmują również 4 profile × 3 dokładne rozmiary i oryginalne keyboard/geometry contracts.

### Obraz, geometria i interakcje — wcześniejszy receipt

Poniższe zrzuty pochodzą z przebiegu przed poprawkami niezależnego review; nie przedstawiają nowego scrollowanego feedbacku. Aktualne dowody tych poprawek to wykonane testy Tk i pomiary powyżej.

Harness: `/home/jakub/.hermes/cache/scratch/triki-redesign-capture.py`. Rzeczywiste Tk, inert Catalog/TraceOutput, konstrukcja prawdziwego BLE/evdev zabroniona, zegary UI anulowane. Katalog Spotify/VLC jest **fixture**, a nie dowodem dostępności/połączenia rzeczywistego urządzenia czy programu. Wynik: **11 zrzutów**, bez błędów callbacków, bez zapisów ustawień, bez połączenia BLE.

Geometria oraz prostokąty stałych przycisków: `/home/jakub/.hermes/cache/scratch/triki-redesign-qa/geometry.json`. Log: `/home/jakub/.hermes/cache/scratch/triki-redesign-capture-final.log`.

- Zarządzane Niri menu: żądane 520×600, faktyczne Tk/Niri/PNG **948×1028**. Nie jest to dowód małego okna.
- Zarządzane Niri multimedia: żądane i faktyczne Tk/Niri/PNG **620×700**.
- Kontrolowane klienty Xwayland: tymczasowe `overrideredirect(True)` wyłącznie w harnessie oraz ImageMagick capture konkretnego drawable Tk. Rozmiar PNG porównany z odczytanym winfo i żądaniem: **520×600, 620×700, 1000×800**. Nie jest to izolowany Xvfb ani zmiana konfiguracji kompozytora.
- Testy parametrów obejmują wszystkie cztery profile w trzech dokładnych rozmiarach. Przy każdej zakładce prostokąty stałych akcji i nawigacji mieszczą się w rzeczywistym kliencie. Testy klawiatury sprawdzają efekt callbacku, zachowanie ustawień i widoczny fokus, nie sam zrzut.

Zrzuty (wszystkie w `/home/jakub/.hermes/cache/scratch/triki-redesign-qa/`): `menu-niri.png`, `media-niri.png`, `media-client-520x600.png`, `media-client-620x700.png`, `media-client-1000x800.png`, `media-gestures-client-520x600.png`, `mouse-control-client-520x600.png`, `mouse-bindings-client-520x600.png`, `diagnostics-client-620x700.png`, `menu-client-520x600.png`, `menu-client-1000x800.png`.

## Smells, komentarze i granice Jev

Załadowano ui-ux-pro-max, use-jev wraz z katalogiem, jev-code-smells, jev-comment-review, jev-code-review i skille natywnego desktopu. `TYPESAFE_API_KEY` nie jest dostępny; **realny Jev: unassessed**, nie symulowany. Nie przełączano providera, nie wysyłano prywatnego repozytorium i nie wykonywano płatnego wywołania.

Deterministyczny AST/reference review i lokalne walidacje: `/home/jakub/.hermes/cache/scratch/triki-redesign-qa/static-review.json`, `smell-request.json`, `smell-dry-run.json`, `comment-input.json`, `comment-request.json`. `jev-decide ... --provider typesafe --dry-run` i helper komentarzy `--dry-run` zakończyły się kodem 0: jest to walidacja żądania, nie werdykt semantyczny. Ruff nie jest zainstalowany.

Naprawiono: zależność od pozycji dziecka `pack_slaves()[2]`, duplikację callbacków zawijania tekstu, redundantne rekonfiguracje widgetów przy każdym pollu, zasłonięty fokus w scrollu i wypchnięty poza okno footer przy 520×600. Komentarze wyjaśniają nietrywialne ograniczenia ramek CTk i pułapkę resize-loop.

AST nie znalazł bezpośrednio nieosiągalnych instrukcji. Proste leads „unused import” dla `annotations` są dyrektywami `__future__`, a `customtkinter` w runnerze jest istniejącym sprawdzeniem zależności. Istniejący `virtual_input_note` jest poza zakresem, więc go nie usuwano. Zachowano kompatybilną sygnaturę `title/from_menu` buildera; brak użycia argumentów w nowym układzie nie uzasadnia usunięcia API. Adaptacja starego drzewa widgetów to jawny kompromis utrzymania chronionego konfiguratora; jest testowana, lecz nie jest dowodem zerowego coupling.

Naprawy review mają osobny receipt AST i requesty: `/home/jakub/.hermes/cache/scratch/triki-review-comments.json`, `triki-review-comment-request.json`, `triki-review-smells.json`, `triki-review-smell-dry-run.json`. Sześć aktualnych bloków komentarzy i cztery pliki sparsowane AST; oba końcowe dry-run zakończyły się kodem 0. Ręczna weryfikacja potwierdziła komentarze o pełnym feedbacku, zachowaniu zamiaru, native settlingu i inert LIVE sinku. **Nie jest to realny werdykt Jev** — klucz TypeSafe nadal nieobecny, Ruff nadal niedostępny. Nie usuwano kodu na podstawie nieocenionych smells. Dodatkowe wywołania analizatorów nie instalowały pakietów.

## Pozostałe granice

Brak fizycznego testu BLE, prawdziwych wyjść/audio/odtwarzaczy, testów Windows/macOS, screen readerów i skalowania całego systemu. Screenshoty mają znaczenie pomocnicze. Oryginalny chroniony konfigurator pozostaje jasny i nie jest objęty globalnym redesignem. Rodzic odczytał diff i testy regresji oraz ponownie wykonał pełny bezpieczny suite po naprawach: **618 passed, 3 deselected, 89 subtests passed in 140.18s**, exit 0. Log: `/home/jakub/.hermes/cache/scratch/triki-redesign-parent-complete.log`. Compileall oraz `git diff --check` poprawne; diff backendów, runtime, session i settings pozostaje pusty. Historyczny scratch baseline ustawień nie jest już dostępny, więc końcowego porównania jego SHA-256 nie można potwierdzić. Testy używają tymczasowych ustawień i sprawdzają brak zapisów. Nowe testy/helper i ten dokument nadal są ignorowane przez git; należy je jawnie uwzględnić przy przyszłym commitowaniu. Nie wykonano commit, push ani release.
