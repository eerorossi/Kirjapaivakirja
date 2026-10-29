# Vaatimusmäärittely: Kirjapäiväkirja

## 1. Tausta ja tavoite

Sovellus, johon käyttäjät kirjaavat lukemiaan kirjoja, liittävät niihin kommentteja, ja näkevät toistensa kirjauksia sekä kommentoivat ja peukuttavat niitä. Toimii useamman käyttäjän ympäristössä, kirjautuminen keskitetyn auth-ratkaisun (Authelia) kautta — ks. [liikuntapaivakirja](https://github.com/eerorossi/liikuntapaivakirja) ja sen Authelia-vaatimusmäärittely.

## 2. Käyttäjät ja kirjautuminen

| # | Vaatimus |
| --- | --- |
| K1 | Kirjautuminen tapahtuu samalla tavalla kuin [liikuntapaivakirja](https://github.com/eerorossi/liikuntapaivakirja)-sovelluksessa: Caddy + Authelia SSO, sovellus lukee käyttäjän tiedot Authelian lähettämistä headereista (`Remote-Email`, `Remote-Name`, `Remote-User`) eikä toteuta omaa salasanakirjautumista. Käyttäjä luodaan automaattisesti ensimmäisellä käynnillä. |

## 3. Luettujen kirjojen kirjaaminen

| # | Vaatimus |
| --- | --- |
| S1 | Kirja valitaan haulla kirjan nimen tai kirjailijan mukaan. Hakutulokset haetaan ulkoisista palveluista: ensisijaisesti Finna (Kansalliskirjasto) ja täydentävästi Open Library. Lähteet on toteutettu vaihdettavan rajapinnan (`BookProvider`) takana. |
| S1a | Jos kirjaa ei löydy haulla, käyttäjä voi lisätä kirjan käsin (nimi ja kirjailija pakollisia). |
| S11 | Valitusta kirjasta haetaan kansikuva ja muut saatavilla olevat tiedot: synopsi, julkaisuvuosi, ISBN ja kirjailijan esittely. Kirjailijan esittely haetaan ensisijaisesti Open Librarysta ja varalla Wikipediasta (suomenkielinen ensin, sitten englanninkielinen). Tiedot ja kansikuva tallennetaan sovelluksen omaan tietokantaan ja levylle. |
| S12 | Em. tiedot näytetään käyttäjälle kirjausta tehtäessä ja kirjan sivulla. |
| S2 | Jokaiselle lukukerralle kirjataan päivämäärä sekä vapaamuotoinen kuvaus/muistiinpano. Sama vapaa kuvauskenttä riittää kaikille. |
| S3 | Lukukerralle (kirjaukselle) voi liittää valinnaisen arvion: 1–5 tähteä. Arvio on kirjauskohtainen, koska sama kirja voidaan lukea useasti. |
| S4 | Käyttäjä voi muokata tai poistaa omia kirjauksiaan. |
| S5 | Kirjaukset listataan aikajärjestyksessä (uusin ensin), kirjan nimen tai kirjailijan mukaan. |

## 4. Sosiaaliset ominaisuudet

| # | Vaatimus |
| --- | --- |
| So1 | Kaikki kirjautuneet käyttäjät näkevät toistensa kirjaukset syötteessä (feed), uusin ensin. |
| So2 | Kirjauksen voi "peukuttaa" (tykätä) — yksi peukutus per käyttäjä per kirjaus, voi perua. |
| So3 | Kirjaukseen voi jättää kommentteja (vapaamuotoinen teksti). |
| So4 | Kirjauksen tekijä näkee, kuka on peukuttanut ja kommentoinut. |
| So5 | Kommentin voi poistaa joko kommentin kirjoittaja tai kirjauksen omistaja. |
| So6 | Kommenteista tai peukutuksista ei lähetetä ilmoituksia toistaiseksi. |

## 5. Ei-toiminnalliset vaatimukset

- Toimii mini-PC / Raspberry Pi -ympäristössä kohtuullisella käyttäjämäärällä (muutamia–kymmeniä käyttäjiä, ei suurta kuormaa).
- Toteutetaan Docker-konttina. Palvelu julkaistaan Caddyn takana polun `/kp` alla, kontin portti 8097. Kontin porttia ei saa avata muille kuin Caddylle, koska sovellus luottaa Authelian headereihin.
- Mobiilikäyttö todennäköistä (kirjaus kännykällä) → responsiivinen käyttöliittymä, mobiili ensin.
- Ulkoisia palveluita kuormitetaan kohtuudella: hakuun debounce, tallennetut kirjatiedot ja kansikuvat käytetään uudelleen, pyynnöissä tunnistettava User-Agent.
- Tietokanta (SQLite) ja kansikuvat sijaitsevat Docker-volumessa ja niistä otetaan varmuuskopio.

## 6. Myöhemmin harkittavaa (ei vaatimuksia nyt)

- Käyttäjäkohtainen näkyvyyden rajaus (yksityiset kirjaukset).
- Ilmoitukset kommenteista/peukutuksista.
