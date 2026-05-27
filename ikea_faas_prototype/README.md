# IKEA FaaS Prototype

Webbaseret prototype til Furniture as a Service (FaaS) hos IKEA. Den lader en kunde
oprette en lejeaftale på et IKEA-møbel, beregner en estimeret CO2e-besparelse i forhold
til engangskøb, og giver IKEA et internt dashboard til at administrere aftaler og
registrere returneringer.

## Forudsætninger

- Python 3.11 eller nyere
- MySQL 8.0 eller nyere (med MySQL Workbench eller `mysql` CLI)
- Git

## Installation

### Trin 1: Klargøring af miljø

Klon repository, opret et virtual environment og installer Python-afhængighederne.

**macOS / Linux:**

```bash
git clone <REPO_URL> ikea_faas_prototype
cd ikea_faas_prototype
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**

```powershell
git clone <REPO_URL> ikea_faas_prototype
cd ikea_faas_prototype
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Trin 2: Database-opsætning

Du har to muligheder for at få databasen op at køre:

**A. Trin-for-trin (skema og data hver for sig)**

1. Åbn MySQL Workbench (eller en `mysql`-CLI-session som root).
2. Kør `database/schema.sql` — opretter databasen `ikea_faas` og alle 9 tabeller.
3. Kør `database/seed.sql` — fylder produkter, møbel-assets og demo-kunder ind.

**B. Komplet reset i én kommando (anbefales til hurtig demo)**

```bash
mysql -u root -p < database/reset.sql
```

`database/reset.sql` dropper alle tabeller, genopretter skemaet, seeder testdata og
kører tre `SELECT`-verifikationer til sidst. Brug den når databasen er i en
inkonsistent tilstand, eller når du vil starte fra præcis samme udgangspunkt som under
udvikling. Den er destruktiv — alle eksisterende kontrakter og returneringer slettes.

**Konfigurér forbindelsen**

Kopiér `.env.example` til `.env` og ret feltværdierne, hvis dine MySQL-credentials
afviger fra standarden:

```env
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=din_adgangskode_her
DB_NAME=ikea_faas
DB_PORT=3306
```

### Trin 3: Opstart af applikationen

```bash
python IKEAFaaS.py
```

Flask starter på `http://127.0.0.1:5000` i debug-mode (auto-reload ved kodeændringer).

Hvis du foretrækker at sætte miljøvariabler direkte fra terminalen i stedet for via
`.env`, kan du i stedet køre Flask via dens CLI:

**macOS / Linux:**

```bash
export FLASK_APP=IKEAFaaS.py
export FLASK_ENV=development
flask run
```

**Windows (PowerShell):**

```powershell
$env:FLASK_APP = "IKEAFaaS.py"
$env:FLASK_ENV = "development"
flask run
```

### Trin 4: Tilgang til brugerfladerne

| Sti | Metode | Beskrivelse |
| --- | --- | --- |
| `/` | GET | Auth-gate: redirecter til `/home` (logget ind) eller `/login` |
| `/login`, `/signup/business`, `/logout` | GET/POST | Login og erhvervsregistrering (werkzeug scrypt-hashing) |
| `/home` | GET | Webshop-forside (kræver login) |
| `/product/<id>` | GET | Produktdetalje med "Køb" og "IKEA ReSpace"-bokse |
| `/cart`, `/cart/add`, `/cart/remove/<i>`, `/checkout` | GET/POST | Kurv og checkout (session-baseret kurv) |
| `/new-contract`, `/create-contract` | GET/POST | Alternativ FaaS-formular og bagvedliggende oprettelse |
| `/impact/<contract_id>` | GET | Kvitteringsside med CO2e-visualisering for en specifik aftale |
| `/customer/<customer_id>` | GET | Kundeprofil med samlet CO2e-effekt, breakdown og aftaletabel |
| `/pickup-request/<contract_id>` | GET, POST | **Kundens** anmodning om afhentning. Ingen DB-persistens — IKEA tager over og laver den autoritative returregistrering. |
| `/admin` | GET | Internt IKEA-dashboard med aftaler, assets og returneringer |
| `/return/<contract_id>` | GET, POST | **IKEA-intern** returregistrering. Stand, transportafstand, køretøjstype og skadenoter vurderes/registreres af IKEA-personale efter afhentning. Kun tilgået fra `/admin`. |
| `/api/products`, `/api/dashboard` | GET | JSON-endpoints (integrationspunkter) |

## Projektstruktur

```
ikea_faas_prototype/
├── IKEAFaaS.py             # Flask-applikationen (routes, beregninger, DB-helpers)
├── README.md               # Denne fil
├── requirements.txt        # Python-afhængigheder (Flask, mysql-connector, dotenv)
├── .env.example            # Skabelon til DB-konfiguration
├── .env                    # Faktiske credentials (commit IKKE denne)
├── ER-diagram.png          # ER-diagram eksporteret fra MySQL Workbench
├── database/
│   ├── schema.sql          # Tabel-definitioner (CREATE TABLE-statements)
│   ├── seed.sql            # Testdata (produkter, assets, demo-kunder)
│   └── reset.sql           # Komplet rebuild i én fil — drop + schema + seed
├── static/
│   └── style.css           # Al styling (Chart.js loades via CDN i templates)
└── templates/
    ├── base.html                    # Legacy layout-skabelon (kun brugt af enkelte ældre sider)
    ├── auth_base.html               # Minimal layout brugt af alle IKEA-stil sider
    ├── _ikea_logo.html              # Partial: CSS-baseret IKEA-logo
    ├── _ikea_topbar.html            # Partial: hvid topbar med søgebar, profil, kurv, log ud
    ├── login.html                   # /login
    ├── signup_business.html         # /signup/business
    ├── home.html                    # /home — webshop-forside
    ├── product.html                 # /product/<id> — produktdetalje
    ├── cart.html, checkout_success.html  # Kurv og ordrebekræftelse
    ├── index.html                   # /new-contract — alternativ FaaS-formular
    ├── impact.html                  # /impact/<id> — kvittering for en FaaS-aftale
    ├── customer.html                # /customer/<id> — kundeprofil med breakdown og chart
    ├── pickup_request.html          # /pickup-request/<id> — KUNDENS anmodning om afhentning
    ├── pickup_request_success.html  # Kundens bekræftelsesside efter anmodning
    ├── return.html                  # /return/<id> — IKEA-intern returregistrerings-formular
    ├── return_success.html          # Bekræftelse efter IKEAs returregistrering
    └── admin.html                   # /admin — IKEA-dashboard
```

Hele Python-koden lever i ét modul (`IKEAFaaS.py`) — der er ikke en `utils/`-mappe
eller separate filer pr. lag. Filen er internt grupperet i sektioner (Jinja-filtre,
database-helpers, CO2e-beregninger, web-routes, JSON API-endpoints, fejlhåndtering),
markeret med kommentar-divisorer.

Chart.js loades via CDN direkte i de templates der bruger det (`impact.html` og
`customer.html`), så der er ingen separat JavaScript-mappe under `static/`.

## Retur-flow: to adskilte handlinger

Retur er bevidst delt i to ruter, der afspejler ansvarsfordelingen i FaaS-modellen:

1. **Kunden** klikker "Anmod om afhentning" på sin profil (`/customer/<id>`). Det
   åbner `/pickup-request/<contract_id>`, hvor kunden kan tilføje en valgfri
   fritekstbemærkning om observerede skader og indsende anmodningen. Anmodningen
   skrives **ikke** til databasen — den ender på en bekræftelsesside, der
   forklarer at IKEA tager over. Kontraktens status forbliver `active`.
2. **IKEA-personale** registrerer den faktiske retur via det interne dashboard:
   `/admin` -> "Registrer retur"-link åbner `/return/<contract_id>`. Her
   indtaster IKEA den autoritative stand, transportafstand og køretøjstype.
   POST'en opretter `return_cases`, `refurbishment_activities` og
   `transport_events`, beregner transport-CO2e, genberegner aftalens
   `co2e_saved_kg` og sætter kontraktens status til `returned`.

Begrundelse: kunden kan hverken kende afstanden til nærmeste IKEA-hub eller
autoritativt vurdere stand. Det er IKEAs ansvar. Den kundevendte flade siger
derfor kun "vi henter snart møblet".

## Platformsspecifikke noter

### macOS / Linux

- Brug `python3` og `pip3` (på macOS peger `python` ofte på system-Python 2).
- Aktivér virtual environment med `source .venv/bin/activate`.
- MySQL installeres typisk via Homebrew: `brew install mysql` efterfulgt af
  `brew services start mysql`.

### Windows

- Brug `python` (peger på Python 3 i moderne installationer fra python.org).
- Aktivér virtual environment med `.venv\Scripts\Activate.ps1` (PowerShell) eller
  `.venv\Scripts\activate.bat` (cmd).
- Hvis PowerShell blokerer aktiverings-scriptet, kør én gang som administrator:
  `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`.
- MySQL CLI ligger som regel på `C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe`
  og er typisk ikke på PATH. Tilføj den til PATH eller kald `mysql.exe` med fuld sti.
- Sti-separator i kommandoer er backslash (`\`), men `mysql.exe -e "source path"`
  accepterer også fremad-slash (`/`).

## Testdata

Efter `seed.sql` eller `reset.sql` er kørt, indeholder databasen:

- **4 produkter** — LAGKAPTEN Skrivebord (99 DKK/mdr), MARKUS Kontorstol (149 DKK/mdr),
  KALLAX Reol (79 DKK/mdr), POÄNG Lænestol (119 DKK/mdr). Hver har `baseline_co2e_kg`
  og `expected_lifespan_years` udfyldt.
- **8 møbel-assets** — 2 pr. produkt, fordelt på `condition_grade` A og B med
  varierende `lifecycle_count`.
- **2 demo-kunder** — Nordic Office ApS (CVR 12345678) og Green Workspace ApS
  (CVR 87654321). De forbliver "orphan" indtil der oprettes en aftale på deres CVR via
  forsiden.

**Designinspiration**
Prototypens brugergrænseflade er udviklet med inspiration fra eksisterende B2B-leasingplatforme og webshops, herunder IKEAs egen erhvervsside og Proshops produktoversigt. Specifikt er card-baseret produktvisning, statusfarvning af aftaler (active, returned, refurbishment) og det opdelte navigationsmønster mellem kundevendt og intern visning adopteret fra disse referencer. Farveval-get følger IKEAs brand-identitet (blå, gul og hvid) for at signalere visuel sammenhæng med en eventuel fremtidig integration i IKEAs øvrige digitale touchpoints.

Testdataen er ikke officielle IKEA-tal — den eksisterer kun for at demonstrere
prototypens dataflows og UI.
