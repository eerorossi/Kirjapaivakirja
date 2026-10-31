# Kirjapäiväkirja

Usean käyttäjän päiväkirja luetuille kirjoille: kirjaukset muistiinpanoineen ja arvioineen, kirjatiedot ja kansikuvat ulkoisista lähteistä sekä peukutukset ja kommentit. Kirjautuminen tulee Caddy+Authelia-SSO:lta, sovellus ei toteuta omaa salasanakirjautumista (sama ratkaisu kuin [liikuntapaivakirja](https://github.com/eerorossi/liikuntapaivakirja)).

## Vaatimukset ja suunnitelma

Ks. [Vaatimusmäärittely.md](Vaatimusmäärittely.md).

Toteutusvaiheet:

0. Pohja ja dokumentaatio (valmis)
1. Tietokanta ja kirjaukset (S2–S5) (valmis)
2. Kirjahaku ja kirjan tiedot (S1, S11, S12) (valmis)
3. Käyttöliittymä: haku, uusi kirjaus, omat kirjaukset, muokkaus ja poisto (toteutettu)
4. Sosiaaliset ominaisuudet: syöte, peukutukset, kommentit (So1–So5) (toteutettu)
5. Käyttöönotto: Docker, Caddy, terveystarkistus, varmuuskopiot (toteutettu)

## Kehitys lokaalisti

```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
DB_PATH=./data/kirjapaivakirja.db uvicorn main:app --reload --port 8097
```

Ilman Caddya edessä auth-headeria ei tule, joten lisää se itse testatessa:

```
curl -H "Remote-Email: testi@example.com" -H "Remote-Name: Testi" http://localhost:8097/api/me
```

Testit: `pytest`

## Käyttöliittymä

Mobiili ensin: yksi sarake, alapalkki (Syöte / Kirjaukset / Lisää kirja), 44–48 px kosketusalueet, vaalea ja tumma teema selaimen asetuksen mukaan. Ei build-vaihetta: `static/app.js` on pelkkää ES-moduulia.

- `#/feed` syöte: kaikkien kirjaukset, uusimmin kirjattu ensin; peukutus ja kommentointi suoraan listasta, "Näytä lisää" sivuttaa
- `#/` omat kirjaukset, lajittelu uusin / kirjan nimi / kirjailija (valinta muistetaan selaimessa)
- `#/new` haku (omat tallennetut kirjat + Finna/Open Library) tai kirjan lisäys käsin
- `#/new/<kirja>` uusi kirjaus: lukupäivä, arvio 1–5 (valinnainen), muistiinpano
- `#/entry/<id>` kirjauksen katselu, kommentit ja peukutus; oma kirjaus muokattavissa ja poistettavissa. Kirjauksen tekijä näkee, ketkä ovat peukuttaneet; kommentin voi poistaa sen kirjoittaja tai kirjauksen tekijä

Sovellus toimii myös alipolun alla (esim. `/kp`): palvelin lisää sivulle `<base href>`-tagin `X-Forwarded-Prefix`-headerista, ja kaikki osoitteet ovat suhteellisia. Caddyssä kannattaa lisätä `redir /kp /kp/`, jotta osoite ilman loppukauttaviivaa ohjautuu oikein.

## API

Kaikki reitit vaativat Authelian headerit (muuten 401). Interaktiivinen dokumentaatio: `/docs`.

| Reitti | Kuvaus |
|---|---|
| `GET /api/me` | Kirjautunut käyttäjä |
| `GET /api/books?q=` | Hae omasta tietokannasta nimen tai kirjailijan osalla |
| `POST /api/books` | Lisää kirja käsin (`title`, `author` pakollisia; `year`, `isbn`, `summary` valinnaisia) |
| `GET /api/books/search?q=` | Haku ulkoisista lähteistä (Finna ensin, sitten Open Library). Palauttaa `results` ja `unavailable` (lähteet, jotka eivät vastanneet) |
| `POST /api/books/import` | Tuo haettu kirja: `{"source": "finna", "source_id": "fikka.123"}`. Palvelin hakee tiedot, kirjailijaesittelyn ja kansikuvan itse. 201 uusi, 200 jos kirja oli jo tuotu |
| `GET /api/books/{id}` | Kirjan tiedot (synopsi, kirjailijaesittely ja sen lähde, `has_cover`) |
| `GET /api/feed?before=&limit=` | Kaikkien kirjaukset, uusimmin kirjattu ensin. Vastaus `{entries, next_before}`; seuraava sivu antamalla `before=next_before` (limit 1–50, oletus 20) |
| `PUT /api/entries/{id}/like` | Peukuta (idempotentti, yksi per käyttäjä). Vastaus `{liked, like_count}` |
| `DELETE /api/entries/{id}/like` | Peru peukutus |
| `GET /api/entries/{id}/likes` | Ketkä ovat peukuttaneet: vain kirjauksen tekijälle (muille 403) |
| `GET /api/entries/{id}/comments` | Kirjauksen kommentit vanhin ensin; `can_delete` kertoo, saako katsoja poistaa |
| `POST /api/entries/{id}/comments` | Lisää kommentti `{"body": "..."}` (1–2000 merkkiä) |
| `DELETE /api/comments/{id}` | Poista kommentti: kirjoittaja tai kirjauksen tekijä, muille 403 |
| `GET /api/books/{id}/cover` | Kansikuva (404 jos ei ole) |
| `GET /api/entries?user_id=&book_id=&sort=` | Kirjaukset; `sort` = `newest` (oletus), `title` tai `author` |
| `POST /api/entries` | Uusi kirjaus: `book_id`, `read_on` (YYYY-MM-DD), `note`, `rating` (1–5 tai tyhjä) |
| `GET /api/entries/{id}` | Yksi kirjaus (kaikki käyttäjät näkevät kaikkien kirjaukset) |
| `PUT /api/entries/{id}` | Muokkaa omaa kirjausta (muilta 403) |
| `DELETE /api/entries/{id}` | Poista oma kirjaus (muilta 403); kirja poistuu, kun sen viimeinen kirjaus poistuu |

## Kirjatietojen lähteet

| Lähde | Käyttö |
|---|---|
| [Finna](https://api.finna.fi/v1?swagger) | Ensisijainen: suomalaiset kirjat, synopsi, kansikuva |
| [Open Library](https://openlibrary.org/dev/docs/api/search) | Täydentävä haku, kansikuva ja kirjailijan esittely |
| Wikipedia (fi, sitten en) | Kirjailijan esittely, jos lähde ei tarjoa sitä. Esittely hyväksytään vain, jos kuvaus viittaa kirjoittajaan (estää samannimisen henkilön). Teksti on CC BY-SA, joten lähdeosoite tallennetaan (`author_bio_source`) ja se pitää näyttää käyttöliittymässä |

- Haku tehdään palvelimen kautta, tulokset ovat 10 minuutin välimuistissa, ja lähteet haetaan rinnakkain. Jos yksi lähde ei vastaa, muut näytetään.
- Valittu kirja kopioidaan omaan tietokantaan ja kansikuva levylle (`COVERS_DIR`), joten ulkoisia palveluita ei kuormiteta selatessa.
- Asiakas ei anna palvelimelle kansikuvan osoitetta: se johdetaan lähteen vastauksesta ja ladataan vain sallituilta palvelimilta (`api.finna.fi`, `covers.openlibrary.org`). Kuvan tyyppi tarkistetaan sisällöstä (jpeg/png/webp, enintään 3 MB).
- Käsin lisäys (`POST /api/books`) on varakeino kirjoille, joita lähteistä ei löydy.

**Täydennys tuonnissa.** Finnassa sama teos on usein monena tietueena, joista vain osalla on kansi tai kuvaus. Tuonnissa puuttuva kuvaus ja kansi haetaan saman nimen ja kirjailijan muilta tietueilta, ja kansi lisäksi Open Libraryn ISBN-haulla. Jos Finnasta ei löydy suomenkielistä kuvausta (ruotsin- ja englanninkieliset hylätään kielitunnistuksella), kuvaus haetaan suomenkielisestä Wikipediasta. Artikkeli hyväksytään vain, jos se mainitsee kirjan lajin (romaani, teos…) ja kirjailijan sukunimen; lähde (CC BY-SA) tallennetaan ja näytetään kuvauksen alla. Jo tallennettujen kirjojen puutteet saa täydennettyä: `docker compose exec kirjapaivakirja python scripts/refresh_books.py` (ei muuta olemassa olevia tietoja eikä kirjauksia).

**Savutesti oikeita rajapintoja vastaan.** Automaattitestit käyttävät kiinteitä vastauksia, joten ne eivät huomaa, jos palvelu muuttaa vastaustaan. Aja tämä käsin aina vaiheen jälkeen ja jos haku alkaa tuottaa outoja tuloksia:

```
python scripts/smoke_providers.py "Tuntematon sotilas"
```

## Käyttöönotto

### Docker

```
docker compose up -d --build
docker compose ps        # STATUS näyttää "healthy", kun sovellus vastaa
```

Kontilla on terveystarkistus (`GET /healthz`, ei vaadi kirjautumista eikä paljasta dataa). Lokit pyörivät (3 × 10 Mt). Tiedot ovat hakemistossa `./data` (tietokanta, `covers/`, `backups/`).

Portti 8097 kuuntelee oletuksena kaikissa osoitteissa. Koska sovellus luottaa `Remote-Email`-headeriin, rajaa portti vain Caddylle: aseta `BIND_ADDR` Pin LAN-osoitteeksi tai käytä palomuuria. Muuten Authelian voi ohittaa kutsumalla porttia suoraan.

### Caddy

Toimiva lohko on tiedostossa `Caddyfile.example` (`redir /kp /kp/` + `handle_path /kp/*` + `forward_auth` + `X-Forwarded-Prefix`). `<APP_HOST>` on osoite, josta Caddy tavoittaa sovelluksen: Pin LAN-osoite tai kontin nimi, jos Caddy on samassa Docker-verkossa, ei `localhost`, jos Caddy on kontissa. Virhe 502 tarkoittaa lähes aina, ettei Caddy tavoita tätä osoitetta.

### Varmuuskopiot

`scripts/backup.py` pakkaa tietokannan (SQLiten backup-rajapinnalla, joten kopio on eheä käytön aikana) ja kansikuvat yhteen tiedostoon `data/backups/kirjapaivakirja-PVM-AIKA.tar.gz` ja säilyttää `BACKUP_KEEP` (oletus 14) uusinta.

```
docker compose exec -T kirjapaivakirja python scripts/backup.py backup
```

Ajasta yöllä crontabilla (`crontab -e`):

```
30 3 * * * /home/pi/docker/BuildKirjapaivakirja/scripts/backup-host.sh >> /home/pi/docker/BuildKirjapaivakirja/data/backup.log 2>&1
```

Sama SD-kortti ei suojaa kortin rikkoutumiselta, joten kopioi `data/backups/` myös toiselle koneelle tai levylle (rsync, rclone tai muu käyttämäsi tapa).

**Palautus.** Pysäytä sovellus, palauta ja käynnistä:

```
docker compose stop
docker compose run --rm kirjapaivakirja python scripts/backup.py restore /app/data/backups/kirjapaivakirja-20261031-033000.tar.gz
docker compose start
```

Palautus tarkistaa arkiston (vain odotetut tiedostot, tietokannan eheys) ennen kuin koskee nykyiseen dataan, ja jättää vanhat tiedot talteen nimillä `kirjapaivakirja.db.before-restore` ja `covers.before-restore`. Kokeile palautus kerran ennen kuin tarvitset sitä.

### Päivitys

```
git pull
docker compose up -d --build
```

Tietokannan uudet sarakkeet ja taulut lisätään käynnistyksessä itsestään; tiedot säilyvät.

## Ympäristömuuttujat

| Muuttuja            | Oletus                          | Kuvaus                                                                                  |
|---------------------|---------------------------------|-----------------------------------------------------------------------------------------|
| `DB_PATH`           | `/app/data/kirjapaivakirja.db`  | SQLite-tietokannan polku                                                                |
| `AUTH_EMAIL_HEADER` | `Remote-Email`                  | Header, josta käyttäjän sähköposti luetaan                                              |
| `AUTH_NAME_HEADER`  | `Remote-Name`                   | Header, josta näyttönimi luetaan (fallback: `Remote-User`, sitten sähköpostin alkuosa)  |
| `AUTH_USER_HEADER`  | `Remote-User`                   | Varanimi näyttönimelle                                                                  |
| `BIND_ADDR`         | `0.0.0.0`                       | Vain docker-compose: osoite, johon portti 8097 sidotaan                                 |
| `COVERS_DIR`        | `/app/data/covers`              | Kansikuvien tallennushakemisto (data-volumessa, otettava mukaan varmuuskopioon)         |
| `BACKUP_DIR`        | `/app/data/backups`             | Varmuuskopioiden hakemisto (`scripts/backup.py`)                                        |
| `BACKUP_KEEP`       | `14`                            | Montako uusinta varmuuskopiota säilytetään                                              |
| `HTTP_USER_AGENT`   | `Kirjapaivakirja/1.0 (+https://github.com/eerorossi/Kirjapaivakirja)` | User-Agent ulkoisille pyynnöille. Open Library ja Wikipedia pyytävät tunnistettavaa agenttia; älä laita siihen muiden käyttäjien tietoja |
