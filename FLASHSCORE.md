# Praćenje promena fudbalskih rezultata

## Poređenje u SettlementCheck aplikaciji

1. Pokrenite skriptu na Flashscore fudbalskoj stranici prema koracima ispod.
2. U Console pozovite `flashscoreWatcher.exportSnapshot()` da preuzmete `flashscore-snapshot.json`. Izvoze se svi trenutno učitani numerički rezultati, uključujući mečeve bez promena.
3. U SettlementCheck aplikaciji izaberite **Flashscore** kao provajdera i učitajte JSON u levom meniju. API ključ nije potreban.
4. Unesite ime operatera i u **Unos tabele** nalepite tabelu iz vašeg programa kao ranije. Kliknite **Učitaj i proveri**.
5. Aplikacija spaja timove koristeći postojeće nazive, alijase i ručno spajanje i poredi **Tvoj Sistem** sa **Teren / Live Feed**. Dvosmislena poklapanja ostaju bez automatskog spajanja. Za nova Flashscore stanja ponovite izvoz i učitavanje.

Ovo je ručni prenos snimka između browsera i aplikacije. Automatsko osvežavanje aplikacije ne preuzima nove rezultate sa Flashscore stranice. Snimci stariji od 5 minuta se odbijaju. Za trenutno označavanje neslaganja postavite toleranciju kašnjenja na 0 sekundi. Uobičajena tolerancija i dalje važi; status završetka meča nije poznat. Datum i rezultat posle 90 minuta ne mogu se potvrditi ovim snimkom. Uporedite tabelu i Flashscore stranicu za isti datum i takmičenje.

## Pokretanje skripte i istorija promena

1. Otvorite fudbalske rezultate na `https://www.flashscore.com/football/`.
2. Učitajte željene lige/mečeve. Otvorite DevTools (F12), pa Console.
3. Pregledajte i nalepite ceo sadržaj `tools/flashscore-watch.js`, pa pritisnite Enter. Kopirajte i početak `(() => {` i završetak `})();`; nemojte kopirati samo deo fajla ili Markdown oznake. Ako dobijete `Illegal return statement`, proverite da početni omotač nije izostavljen.
4. Posle nekoliko sekundi proverite `flashscoreWatcher.status()`: `tracked` treba da bude veći od nule za mečeve sa numeričkim rezultatom.
5. Izvezite promene komandom `flashscoreWatcher.exportCSV()`.

Ostale komande:

```javascript
flashscoreWatcher.changes()   // kopija zabeleženih promena
flashscoreWatcher.status()    // stanje praćenja i čuvanja
flashscoreWatcher.stop()      // zaustavljanje
```

Prvi viđeni rezultat služi kao početno stanje. Svaka naredna promena oba glavna rezultata, uključujući smanjenje/ispravku, daje jedan CSV red: vreme opažanja u UTC, ID, timovi, prethodni i novi rezultat. Minuti, status i pojedinačni setovi/poluvremena se ne beleže. Vreme opažanja nije zvanično vreme gola.

Podaci ostaju u browser localStorage, posebno za svaku putanju stranice. Posle osvežavanja ponovo pokrenite skriptu; promene nastale tokom pauze mogu se videti samo kao razlika poslednjeg i novog rezultata. Redovno izvozite CSV; ako je skladište puno, skripta upozorava i nastavlja u memoriji. Ponovno pokretanje na istoj stranici zaustavlja prethodnog posmatrača.

Skripta prati samo mečeve koje stranica učita u DOM. Ne otvara lige, ne skroluje automatski i ne garantuje hvatanje svih međurezultata. Kartica mora ostati otvorena; uspavana ili pozadinska kartica može kasniti ili prestati da dobija ažuriranja. Za istoriju promena DOM mora biti stabilan najmanje 500 ms; snimak čita trenutno stanje odmah, pa sačekajte da se rezultat prikaže u celosti pre izvoza. Nema serverskog rada 24/7. Povezivanje sa SettlementCheck aplikacijom radi kroz ručni JSON uvoz opisan iznad.

Nema dodatnih biblioteka, pozivanja privatnih API ruta ili zaobilaženja CAPTCHA/zaštite. Koristite u skladu sa uslovima sajta. Flashscore može menjati HTML; selektori u `readRow` tada zahtevaju prilagođavanje. **Selektori nisu potvrđeni na živoj stranici iz ovog okruženja zbog blokiranog mrežnog pristupa.** Ako `tracked` ostaje nula iako postoje prikazani rezultati, proverite selektore u DevTools.

Lokalna provera logike (Node.js 18+):

```sh
node tests/flashscore-watch.test.cjs
../settlement-venv/bin/python -m unittest discover -s tests -p 'test_flashscore*.py'
```
