# Vaatimusmäärittely: Liikuntapäiväkirja

## 1. Tausta ja tavoite

Sovellus, johon käyttäjät kirjaavat lukemiaan kirjoja, liittävät niihin kommenttej, ja näkevät toistensa kirjauksia sekä kommentoivat ja peukuttavat niitä. Toimii useamman käyttäjän ympäristössä, kirjautuminen keskitetyn auth-ratkaisun (Authelia) kautta — ks. erillinen auth-vaatimusmäärittely https://github.com/eerorossi/liikuntapaivakirja 

## 2. Käyttäjät ja kirjautuminen

| # | Vaatimus |
| --- | --- |
| K1 | Kirjautuminen tapahtuu samalla tavalla kuin https://github.com/eerorossi/liikuntapaivakirja sovelluksessa

## 3. Luettujen kirjojen kirjaaminen

| # | Vaatimus |
| --- | --- |
| S1 | Kirja valitaan Kirjan nimen tai kirjoittajan mukaisesta listasta. Lista haetaan ulkoisesta palvelusta (mistä) |
| S11 | Ulkoisesta palvelusta haetaan kansikuva ja muut mahdolliset tiedot, esim kirjailijan esittely ja synopsi | 
| S12 | Em. tiedot näytetään käyttäjälle|
| S2 | Jokaiselle lukukerralle kirjataan päivämäärä sekä vapaamuotoinen kuvaus/muistiinpano. Sama vapaa kuvauskenttä riittää kaikille. |
| S3 | Kirjaan voi liittää arvion: 1 - 5 tähteä. |
| S4 | Käyttäjä voi muokata tai poistaa omia kirjauksiaan. |
| S5 | Kirjaukset listataan aikajärjestyksessä (uusin ensin), kirjan nimen tai kirjailijan mukaan. |


## 5. Sosiaaliset ominaisuudet

| # | Vaatimus |
| --- | --- |
| So1 | Käyttäjät näkevät toistensa kirjaukset syötteessä (feed). |
| So2 | Kirjauksen voi "peukuttaa" (tykätä) — yksi peukutus per käyttäjä per kirjaus, voi perua. |
| So3 | Kirjaukseen voi jättää kommentteja (vapaamuotoinen teksti). |
| So4 | Kirjauksen tekijä näkee, kuka on peukuttanut ja kommentoinut. |
| So5 | Kommentin voi poistaa joko kommentin kirjoittaja tai kirjauksen omistaja. |
| So6 | Kommenteista tai peukutuksista ei lähetetä ilmoituksia toistaiseksi. |



## 8. Ei-toiminnalliset vaatimukset

- Toimii mini-PC -ympäristössä kohtuullisella käyttäjämäärällä (muutamia–kymmeniä käyttäjiä, ei suurta kuormaa).
- Toteutetaan Docker-konttina.
- Mobiilikäyttö todennäköistä (kirjaus treenin jälkeen kännykällä) → responsiivinen käyttöliittymä tai kevyt mobiilioptimointi vähintään.

## 9. Myöhemmin harkittavaa (ei vaatimuksia nyt)

- Käyttäjäkohtainen näkyvyyden rajaus (yksityiset kirjaukset).
- Ilmoitukset kommenteista/peukutuksista.