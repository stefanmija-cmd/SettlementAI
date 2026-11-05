# Praćenje promena fudbalskih rezultata

## Direktno slanje u Streamlit Community Cloud

Tok podataka: Flashscore kartica → HTTPS prijemnik → Streamlit aplikacija → poređenje sa zalepljenom internom tabelom.

Streamlit Community Cloud ne izlaže naš dodatni HTTP server na javnom URL-u aplikacije. Zato se `flashscore_bridge.py` pokreće kao zaseban web servis. Ovo nije Flashscore API: skripta u vašem browseru šalje učitane rezultate. Ne šaljite POST na adresu `*.streamlit.app`.

### 1. Postavljanje prijemnika

Repozitorijum sadrži `render.yaml` za Render Blueprint: u Render nalogu kreirajte Blueprint iz ovog GitHub repozitorijuma i grane sa ovim izmenama. Kreira se Python web servis koji pokreće `python flashscore_bridge.py`, sluša na platformskom `PORT` i proverava `/health`. Nisu potrebne dodatne Python biblioteke za prijemnik. Konfiguracija koristi free plan; dostupnost zavisi od naloga i ponude provajdera. Besplatni servisi mogu da se uspavaju i kasne pri buđenju; za pouzdano neprekidno praćenje potreban je stalno aktivan servis.

Render generiše `FLASHSCORE_BRIDGE_TOKEN`. U Environment podešavanjima servisa bezbedno preuzmite njegovu vrednost i zabeležite HTTPS URL servisa. Token mora imati najmanje 24 znaka. Nemojte ga stavljati u GitHub, URL, chat ili javni kod. Svi korisnici sa istim tokenom dele jedan feed; koristite jednu Flashscore karticu za slanje po prijemniku. Za odvojene operatere/izvore koristite zasebne instance i tokene.

Prijemnik zadržava samo poslednji validan snimak u memoriji; restart briše feed do sledećeg slanja. Stariji snimak ne može da prepiše noviji. Pogrešan token dobija HTTP 401. Ne objavljujte nezaštićen razvojni HTTP server direktno na Internetu: Render obezbeđuje HTTPS ispred njega; na sopstvenom serveru koristite HTTPS reverse proxy.

### 2. Podešavanje Streamlit aplikacije

U Streamlit Community Cloud → App settings → Secrets dodajte stvarni URL prijemnika i isti token. Ovaj primer sadrži samo oznake za zamenu, ne stvarne vrednosti:

```toml
FLASHSCORE_BRIDGE_URL = "https://VAS-PRIJEMNIK.onrender.com"
FLASHSCORE_BRIDGE_TOKEN = "OVDE-UNESITE-STVARNI-TOKEN-IZ-PODEŠAVANJA-PRIJEMNIKA"
```

Sačuvajte secrets i ponovo pokrenite aplikaciju ako je potrebno. Izaberite **Flashscore → Direktno**, unesite operatera, nalepite internu tabelu i kliknite **Učitaj i proveri**. Uključite **Automatsko** osvežavanje i interval 15 sekundi za periodično poređenje sa novim podacima. Za trenutni alarm postavite toleranciju na 0. Interna tabela se i dalje ne ažurira sama: za novu verziju nalepite novi unos. Vreme u aplikaciji označava browser opažanje, ne potvrdu svežine samog Flashscore izvora.

### 3. Automatsko slanje sa Flashscore stranice

1. Instalirajte Tampermonkey u browser i napravite novu userscript skriptu.
2. Zamenite sav početni sadržaj celim fajlom `tools/flashscore-watch.js`, uključujući `// ==UserScript==` zaglavlje. Sačuvajte.
3. Otvorite ili osvežite `https://www.flashscore.com/football/` i učitajte željene mečeve. Omogućite userscript ako browser traži dozvolu.
4. U Tampermonkey meniju ove skripte izaberite **Poveži SettlementAI prijemnik**. Unesite HTTPS URL prijemnika bez `/snapshot`, pa token. Odobrite pristup tom domenu ako Tampermonkey traži.
5. **Status slanja** pokazuje `lastSentAt` i eventualnu grešku bez prikazivanja tokena. Posle prvog uspešnog slanja aplikacija može da preuzme rezultate. Zatim se stabilne promene šalju automatski (najčešće do nekoliko sekundi), a potvrda veze najmanje svakih 15 sekundi dok kartica radi. **Zaustavi slanje** prekida vezu.

Token ostaje samo u memoriji otvorene userscript kartice. Posle osvežavanja/otvaranja nove stranice ponovo povežite prijemnik. `@connect *` podržava URL koji unesete; nakon izbora servera možete ga suziti u zaglavlju na tačan hostname vašeg prijemnika. Ne pokrećite više pošiljalaca sa različitim listama mečeva na istom prijemniku: svaki snimak zamenjuje prethodni u celosti.

Za konzolu je dostupno `flashscoreWatcher.connect(prompt("HTTPS URL prijemnika:"), prompt("Token:"))`, ali Flashscore CSP pravila mogu blokirati standardni `fetch`; Tampermonkey koristi svoj odobreni mrežni pristup. CORS prijemnika dozvoljava samo `https://www.flashscore.com`; token je obavezan i za čitanje i za pisanje. Browser slanje proverava HTTP odgovor i prikazuje grešku; neuspeh se ponavlja najčešće jednom u 10 sekundi. Direktna veza odbija podatke starije od 45 sekundi i prekida poređenje dok ne stignu novi podaci. Uspavana kartica ili prekid mreže zato ne predstavlja uspešnu proveru rezultata.

Prijemnik je testiran lokalno, ali javni HTTPS servis nije automatski postavljen. Potrebni su njegovo postavljanje i gore navedena podešavanja pre korišćenja iz Community Cloud-a.

## Ručni JSON uvoz (rezervni režim)

1. Pokrenite skriptu na Flashscore fudbalskoj stranici prema koracima ispod.
2. U Console pozovite `flashscoreWatcher.exportSnapshot()` da preuzmete `flashscore-snapshot.json`. Izvoze se svi trenutno učitani numerički rezultati, uključujući mečeve bez promena.
3. U SettlementCheck aplikaciji izaberite **Flashscore → JSON datoteka** i učitajte JSON u levom meniju. API ključ nije potreban.
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

Skripta prati samo mečeve koje stranica učita u DOM. Ne otvara lige, ne skroluje automatski i ne garantuje hvatanje svih međurezultata. Kartica mora ostati otvorena; uspavana ili pozadinska kartica može kasniti ili prestati da dobija ažuriranja. Za istoriju promena i direktno slanje DOM mora biti stabilan najmanje 500 ms; ručni snimak čita trenutno stanje odmah. Status završetka, datum i rezultat posle 90 minuta nisu potvrđeni ovim podacima. Proverite da oba izvora prikazuju isti meč/datum. Prijemnik ne preuzima rezultate sam kada browser ne radi.

Nema dodatnih biblioteka, pozivanja privatnih API ruta ili zaobilaženja CAPTCHA/zaštite. Koristite u skladu sa uslovima sajta. Flashscore može menjati HTML; selektori u `readRow` tada zahtevaju prilagođavanje. **Selektori nisu potvrđeni na živoj stranici iz ovog okruženja zbog blokiranog mrežnog pristupa.** Ako `tracked` ostaje nula iako postoje prikazani rezultati, proverite selektore u DevTools.

Lokalna provera logike (Node.js 18+):

```sh
node tests/flashscore-watch.test.cjs
../settlement-venv/bin/python -m unittest discover -s tests -p 'test_flashscore*.py'
```
