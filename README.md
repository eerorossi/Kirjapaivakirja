# Kirjapäiväkirja

Usean käyttäjän päiväkirja luetuille kirjoille: kirjaukset muistiinpanoineen ja arvioineen, kirjatiedot ja kansikuvat ulkoisista lähteistä sekä peukutukset ja kommentit. Kirjautuminen tulee Caddy+Authelia-SSO:lta, sovellus ei toteuta omaa salasanakirjautumista (sama ratkaisu kuin [liikuntapaivakirja](https://github.com/eerorossi/liikuntapaivakirja)).

## Vaatimukset ja suunnitelma

Ks. [Vaatimusmäärittely.md](Vaatimusmäärittely.md).

Toteutusvaiheet:

0. Pohja ja dokumentaatio (valmis)
1. Tietokanta ja kirjaukset (S2–S5)
2. Kirjahaku ja kirjan tiedot (S1, S11, S12)
3. Käyttöliittymä (omat kirjaukset)
4. Sosiaaliset ominaisuudet (So1–So5)
5. Käyttöönotto (Docker, Caddy, varmuuskopiot)

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

## Docker

```
docker compose up -d --build
```

Portti 8097 kuuntelee oletuksena kaikissa osoitteissa. Koska sovellus luottaa `Remote-Email`-headeriin, rajaa portti vain Caddylle (palomuuri tai `BIND_ADDR` ympäristömuuttuja). Caddy-lohkon pohja on tiedostossa `Caddyfile.example`.

## Ympäristömuuttujat

| Muuttuja            | Oletus                          | Kuvaus                                                                                  |
|---------------------|---------------------------------|-----------------------------------------------------------------------------------------|
| `DB_PATH`           | `/app/data/kirjapaivakirja.db`  | SQLite-tietokannan polku                                                                |
| `AUTH_EMAIL_HEADER` | `Remote-Email`                  | Header, josta käyttäjän sähköposti luetaan                                              |
| `AUTH_NAME_HEADER`  | `Remote-Name`                   | Header, josta näyttönimi luetaan (fallback: `Remote-User`, sitten sähköpostin alkuosa)  |
| `AUTH_USER_HEADER`  | `Remote-User`                   | Varanimi näyttönimelle                                                                  |
| `BIND_ADDR`         | `0.0.0.0`                       | Vain docker-compose: osoite, johon portti 8097 sidotaan                                 |
