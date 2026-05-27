"""
IKEAFaaS.py

Modul: Flask-applikation for IKEA Furniture as a Service-prototypen.

Hele applikationen ligger i denne ene fil. Strukturen er internt grupperet i
fem sektioner, markeret med kommentar-divisorer:

- Jinja-template-filtre (dansk talformatering)
- Database-helpers (forbindelse + fetch_all/fetch_one)
- CO2e-beregninger (kontrakt-impact, transport-emission, reparationsplan)
- Web-routes (HTML-sider)
- JSON API-endpoints + fejlhåndtering

DB-konfiguration læses fra .env via python-dotenv. Se README.md for opsætning.

Forfatter: Gruppe 11A
"""

from datetime import date
from decimal import Decimal, InvalidOperation
import os
import secrets

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
import mysql.connector
from mysql.connector import Error

load_dotenv()

app = Flask(__name__)

# Session-cookie kryptering. I produktion skal FLASK_SECRET_KEY sættes i .env.
# Fallback genererer en tilfældig nøgle pr. proces — fint til lokal udvikling,
# men brugere mister deres session ved hver serverstart.
_secret = os.getenv("FLASK_SECRET_KEY")
if not _secret:
    _secret = secrets.token_hex(32)
    app.logger.warning(
        "FLASK_SECRET_KEY ikke sat i .env — bruger éngangs-nøgle. "
        "Sessions invalideres ved hver serverstart."
    )
app.secret_key = _secret


@app.context_processor
def inject_current_user():
    """Gør den loggede-ind customer_id tilgængelig i alle templates som
    ``current_user_id`` (None hvis ikke logget ind). Bruges af base.html til
    at vise/skjule auth-følsomme nav-links."""
    return {"current_user_id": session.get("customer_id")}


@app.context_processor
def inject_cart_count():
    """Eksponerer antal items i kurven til alle templates som ``cart_count``.
    Bruges af IKEA-topbaren til at vise badge på kurv-ikonet."""
    return {"cart_count": len(session.get("cart", []))}


def cart_get():
    """Returnerer kurven (liste af dicts) fra sessionen."""
    return session.get("cart", [])

def cart_save(items):
    """Persisterer kurven til sessionen."""
    session["cart"] = items
    session.modified = True

def cart_total(items=None):
    """Summerer linjetotalerne i kurven. Køb tæller engangspris;
    lease tæller månedspris × antal måneder."""
    items = items if items is not None else cart_get()
    total = Decimal("0.00")
    for it in items:
        total += Decimal(str(it.get("line_total", 0)))
    return total


# ============ Jinja-template-filtre ============

@app.template_filter("dk_number")
def dk_number(value, decimals=2):
    """Formaterer et tal med dansk decimalseparator (komma).

    Registreret som Jinja-filter, fx ``{{ 38.50|dk_number(2) }}`` → "38,50".
    Bruges konsekvent på tværs af templates til CO2e- og pris-visning.

    Args:
        value: Tallet der skal formateres (Decimal, float, int eller str-konvertibel).
        decimals: Antal decimaler (default 2).

    Returns:
        Streng på formen "38,50". Returnerer "0,00" hvis value er None,
        og den oprindelige value uændret hvis konvertering fejler.
    """
    if value is None:
        return "0,00"

    try:
        number = Decimal(str(value))
        return f"{number:.{decimals}f}".replace(".", ",")
    except (InvalidOperation, ValueError, TypeError):
        return value

# ============ Database-helpers ============

def get_connection():
    """Opretter en ny MySQL-forbindelse via miljø-variabler.

    Læser DB_HOST, DB_USER, DB_PASSWORD, DB_NAME og DB_PORT fra .env
    (med defaults: localhost / root / tom / ikea_faas / 3306). Ingen connection
    pooling — hver request åbner og lukker sin egen forbindelse.

    Returns:
        En åben ``mysql.connector``-forbindelse. Kalderen er ansvarlig for at
        lukke den.
    """
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "ikea_faas"),
        port=int(os.getenv("DB_PORT", "3306"))
    )

def fetch_all(query, params=None):
    """Eksekverer en SELECT-query og returnerer alle rækker som liste af dicts.

    Åbner en ny forbindelse pr. kald og lukker cursor + connection efter
    resultatet er hentet. Cursor er konfigureret med ``dictionary=True``, så
    hver række er en dict keyed på kolonnenavn.

    Args:
        query: SQL-streng med ``%s``-placeholders.
        params: Tuple/liste af parametre, eller None hvis queryen ikke har nogen.

    Returns:
        Liste af dicts. Tom liste hvis ingen rækker.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, params or ())
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

def fetch_one(query, params=None):
    """Eksekverer en SELECT-query og returnerer kun første række som dict.

    Samme adfærd som ``fetch_all``, men kalder ``fetchone()``.

    Args:
        query: SQL-streng med ``%s``-placeholders.
        params: Tuple/liste af parametre, eller None.

    Returns:
        Dict hvis en række findes, ellers None.
    """
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, params or ())
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row

# ============ CO2e-beregninger ============

def calculate_contract_impact(baseline_co2e_kg, expected_lifespan_years, rental_months):
    """
    Tidsproportional amortisering af manufacturing-emission.
    Den cirkulære påvirkning udgør den andel af baseline, som leasen "bruger"
    af produktets forventede levetid. Service overhead og transport er ikke med
    her — transport bogføres separat på transport_events og trækkes fra co2e_saved_kg
    ved retur. Tallet er ikke et officielt IKEA-tal.
    """
    baseline = Decimal(str(baseline_co2e_kg))
    # Konverter forventet levetid til måneder (samme enhed som rental_months).
    # max(..., 1) beskytter mod division med nul ved fejl-data.
    lifespan_months = Decimal(str(max(expected_lifespan_years, 1))) * Decimal("12")
    months = Decimal(str(max(rental_months, 1)))

    # Amortiseret andel: baseline × (lease-tid / total forventet levetid).
    circular_impact = baseline * (months / lifespan_months)
    co2_saved = baseline - circular_impact

    if co2_saved < 0:
        co2_saved = Decimal("0.00")

    return {
        "baseline_co2e_kg": round(baseline, 2),
        "circular_co2e_kg": round(circular_impact, 2),
        "co2e_saved_kg": round(co2_saved, 2)
    }


# Emissionsfaktorer (kg CO2e pr. km) pr. køretøjstype i ENUM'en
# transport_events.vehicle_type. Tallene er prototypeskøn, ikke officielle.
VEHICLE_EMISSION_FACTORS_KG_PER_KM = {
    "electric_van": Decimal("0.05"),
    "diesel_van":   Decimal("0.22"),
    "cargo_bike":   Decimal("0.01"),
    "truck":        Decimal("0.80"),
}

def transport_co2e(distance_km, vehicle_type):
    """Beregner transport-CO2e ud fra afstand og køretøjstype.

    Slår emissionsfaktor op i ``VEHICLE_EMISSION_FACTORS_KG_PER_KM`` og
    returnerer ``distance × faktor`` afrundet til 2 decimaler. Ukendte
    køretøjstyper falder tilbage til diesel_van-faktoren (0,22) som
    sikkerhedsnet mod KeyError — det er ikke konceptuelt rigtigt, kun robust.

    Args:
        distance_km: Afstand i kilometer (Decimal, float eller str-konvertibel).
        vehicle_type: ENUM-streng der matcher ``transport_events.vehicle_type``
            (electric_van, diesel_van, cargo_bike, truck).

    Returns:
        ``Decimal`` med kg CO2e afrundet til 2 decimaler.
    """
    distance = Decimal(str(distance_km))
    factor = VEHICLE_EMISSION_FACTORS_KG_PER_KM.get(vehicle_type, Decimal("0.22"))
    return round(distance * factor, 2)

def refurb_plan(condition_grade):
    """Returnerer reparationsplan og næste handling for et returneret asset.

    Mapper ``condition_grade`` (A/B/C/D) til en plan-tuple, der bestemmer
    omkostning i DKK, refurbishment-CO2e, ny stand efter behandling og næste
    skridt (resell, refurbish eller recycle). Ukendt grade behandles som D
    (genanvendelse).

    Args:
        condition_grade: Stand ved returnering — "A", "B", "C" eller "D".

    Returns:
        Tuple af 5 elementer: ``(action_type, cost_dkk, co2e_kg,
        new_condition_grade, next_action)``. Fx for grade A:
        ``("Light cleaning", Decimal("45.00"), Decimal("1.00"), "A", "resell")``.
    """
    if condition_grade == "A":
        return ("Light cleaning", Decimal("45.00"), Decimal("1.00"), "A", "resell")
    if condition_grade == "B":
        return ("Cleaning and minor repair", Decimal("120.00"), Decimal("3.50"), "A", "refurbish")
    if condition_grade == "C":
        return ("Repair and spare parts", Decimal("280.00"), Decimal("7.50"), "B", "refurbish")
    return ("Send to recycling", Decimal("80.00"), Decimal("2.00"), "D", "recycle")

# ============ Web-routes ============

@app.route("/")
def index():
    """Rod-URL — auth-gate.

    Hvis brugeren er logget ind, sendes de til ``/home`` (IKEA-stil forside).
    Ellers sendes de til ``/login``.
    """
    if "customer_id" in session:
        return redirect(url_for("home"))
    return redirect(url_for("login"))


@app.route("/home")
def home():
    """IKEA-stil forside efter login.

    Render ``home.html`` med velkomst, hurtige action-kort og produktoversigt.
    Kræver login — uloggede brugere sendes til ``/login``.
    """
    if "customer_id" not in session:
        return redirect(url_for("login"))

    customer_row = fetch_one("""
        SELECT customer_id, company_name, contact_person
        FROM customers
        WHERE customer_id = %s
    """, (session["customer_id"],))

    products = fetch_all("""
        SELECT p.*, COUNT(a.asset_id) AS available_assets
        FROM products p
        LEFT JOIN furniture_assets a
            ON p.product_id = a.product_id AND a.status = 'available'
        GROUP BY p.product_id
        ORDER BY p.product_name
    """)

    return render_template("home.html", customer=customer_row, products=products)


@app.route("/new-contract")
def new_contract():
    """Produktoversigt og oprettelses-formular (kræver login).

    Henter alle produkter med antal ledige assets pr. produkt og render
    ``index.html`` i IKEA-stil. Customer-record sendes med så formularen
    kan prefyldes og topbar kan vise profil-avatar.
    """
    if "customer_id" not in session:
        return redirect(url_for("login"))

    customer_row = fetch_one("""
        SELECT customer_id, company_name, cvr_number, contact_person, email, zip_code
        FROM customers
        WHERE customer_id = %s
    """, (session["customer_id"],))

    products = fetch_all("""
        SELECT p.*, COUNT(a.asset_id) AS available_assets
        FROM products p
        LEFT JOIN furniture_assets a
            ON p.product_id = a.product_id AND a.status = 'available'
        GROUP BY p.product_id
        ORDER BY p.product_name
    """)
    return render_template("index.html", products=products, customer=customer_row)


@app.route("/create-contract", methods=["POST"])
def create_contract():
    """Modtager oprettelses-formularen og opretter en ny aftale i én transaktion.

    Flow:
    1. Slå kunde op på CVR — genbrug eksisterende ``customer_id`` ved match,
       opret ny customer-record ellers.
    2. Vælg første ledige asset for det valgte produkt (sorteret efter
       condition_grade, derefter lifecycle_count DESC).
    3. Hent månedsleje fra ``products.monthly_price_dkk`` (backend stoler ikke
       på pris fra formularen).
    4. Indsæt ``faas_contracts``-række og marker asset som ``leased``.
    5. Beregn impact via ``calculate_contract_impact`` og gem i
       ``impact_results``.
    6. Log integration-event til ``integration_log``.

    Alt sker i én transaktion — fejler noget, rulles hele oprettelsen tilbage.

    Returns:
        Redirect til ``/impact/<contract_id>``.
    """
    product_id = int(request.form["product_id"])
    company_name = request.form["company_name"].strip()
    cvr_number = request.form["cvr_number"].strip()
    contact_person = request.form["contact_person"].strip()
    email = request.form["email"].strip()
    zip_code = request.form["zip_code"].strip()
    rental_months = int(request.form["rental_months"])

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        conn.start_transaction()

        cursor.execute(
            "SELECT customer_id FROM customers WHERE cvr_number = %s",
            (cvr_number,)
        )
        existing_customer = cursor.fetchone()

        if existing_customer:
            customer_id = existing_customer["customer_id"]
        else:
            cursor.execute("""
                INSERT INTO customers (company_name, cvr_number, contact_person, email, zip_code)
                VALUES (%s, %s, %s, %s, %s)
            """, (company_name, cvr_number, contact_person, email, zip_code))
            customer_id = cursor.lastrowid

        cursor.execute("""
            SELECT a.asset_id, a.lifecycle_count, p.baseline_co2e_kg, p.monthly_price_dkk,
                   p.expected_lifespan_years
            FROM furniture_assets a
            JOIN products p ON a.product_id = p.product_id
            WHERE a.product_id = %s AND a.status = 'available'
            ORDER BY a.condition_grade, a.lifecycle_count DESC
            LIMIT 1
        """, (product_id,))

        asset = cursor.fetchone()

        if not asset:
            raise ValueError("Ingen ledige møbler findes i demo-databasen for dette produkt.")

        monthly_price = Decimal(str(asset["monthly_price_dkk"]))

        start_date = date.today()
        end_date = date(start_date.year + ((start_date.month + rental_months - 1) // 12),
                        ((start_date.month + rental_months - 1) % 12) + 1,
                        start_date.day)

        cursor.execute("""
            INSERT INTO faas_contracts (customer_id, asset_id, start_date, end_date, monthly_price, status)
            VALUES (%s, %s, %s, %s, %s, 'active')
        """, (customer_id, asset["asset_id"], start_date, end_date, monthly_price))

        contract_id = cursor.lastrowid

        cursor.execute("""
            UPDATE furniture_assets
            SET status = 'leased'
            WHERE asset_id = %s
        """, (asset["asset_id"],))

        impact = calculate_contract_impact(
            asset["baseline_co2e_kg"],
            asset["expected_lifespan_years"],
            rental_months
        )

        cursor.execute("""
            INSERT INTO impact_results (contract_id, baseline_co2e_kg, circular_co2e_kg, co2e_saved_kg)
            VALUES (%s, %s, %s, %s)
        """, (
            contract_id,
            impact["baseline_co2e_kg"],
            impact["circular_co2e_kg"],
            impact["co2e_saved_kg"]
        ))

        cursor.execute("""
            INSERT INTO integration_log (source_system, target_system, event_type, status)
            VALUES (%s, %s, %s, %s)
        """, ("FaaS prototype", "CRM and sustainability reporting", "contract_created", "sent"))

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("impact", contract_id=contract_id))

@app.route("/impact/<int:contract_id>")
def impact(contract_id):
    """Renderer ``impact.html`` med CO2e-visualisering for en specifik aftale.

    Henter en fladt joinet række med kontrakt-, kunde-, produkt-, asset- og
    impact-data. Bruges som kvitterings-side efter oprettelse via
    ``create_contract``, og kan også åbnes direkte via URL fra dashboard og
    kundeprofil.

    Args:
        contract_id: ID på den kontrakt der skal vises.
    """
    # Fetch logged-in customer for topbar (kan være None hvis ikke logget ind)
    customer_row = None
    if "customer_id" in session:
        customer_row = fetch_one("""
            SELECT customer_id, company_name, cvr_number, contact_person
            FROM customers
            WHERE customer_id = %s
        """, (session["customer_id"],))

    data = fetch_one("""
        SELECT
            c.contract_id,
            c.start_date,
            c.end_date,
            c.monthly_price,
            c.status,
            cu.company_name,
            cu.cvr_number,
            cu.contact_person,
            cu.email,
            cu.zip_code,
            p.product_name,
            p.category,
            a.serial_number,
            a.lifecycle_count,
            i.baseline_co2e_kg,
            i.circular_co2e_kg,
            i.co2e_saved_kg
        FROM faas_contracts c
        JOIN customers cu ON c.customer_id = cu.customer_id
        JOIN furniture_assets a ON c.asset_id = a.asset_id
        JOIN products p ON a.product_id = p.product_id
        JOIN impact_results i ON c.contract_id = i.contract_id
        WHERE c.contract_id = %s
        ORDER BY i.calculated_at DESC
        LIMIT 1
    """, (contract_id,))
    return render_template("impact.html", data=data, customer=customer_row)

@app.route("/admin")
def admin():
    """Internt IKEA-dashboard.

    Henter fire datasæt og render ``admin.html``:

    - ``summary``: antal aftaler + total/gennemsnitlig CO2e-besparelse.
    - ``contracts``: alle kontrakter med kunde, produkt, asset og besparelse.
    - ``assets``: alle møbel-assets med status, stand og lifecycle_count.
    - ``returns``: alle registrerede returneringer.
    """
    summary = fetch_one("""
        SELECT
            COUNT(DISTINCT c.contract_id) AS contracts,
            COALESCE(SUM(i.co2e_saved_kg), 0) AS total_saved,
            COALESCE(AVG(i.co2e_saved_kg), 0) AS avg_saved
        FROM faas_contracts c
        LEFT JOIN impact_results i ON c.contract_id = i.contract_id
    """)

    contracts = fetch_all("""
        SELECT
            c.contract_id,
            c.customer_id,
            c.status,
            cu.company_name,
            cu.cvr_number,
            cu.contact_person,
            p.product_name,
            a.serial_number,
            a.condition_grade,
            i.co2e_saved_kg
        FROM faas_contracts c
        JOIN customers cu ON c.customer_id = cu.customer_id
        JOIN furniture_assets a ON c.asset_id = a.asset_id
        JOIN products p ON a.product_id = p.product_id
        LEFT JOIN impact_results i ON c.contract_id = i.contract_id
        ORDER BY c.contract_id DESC
    """)

    assets = fetch_all("""
        SELECT p.product_name, a.serial_number, a.condition_grade, a.status, a.lifecycle_count
        FROM furniture_assets a
        JOIN products p ON a.product_id = p.product_id
        ORDER BY a.status, p.product_name
    """)

    returns = fetch_all("""
        SELECT r.return_id, r.return_date, r.condition_grade, r.next_action, p.product_name,
               cu.company_name, cu.cvr_number, cu.contact_person
        FROM return_cases r
        JOIN faas_contracts c ON r.contract_id = c.contract_id
        JOIN customers cu ON c.customer_id = cu.customer_id
        JOIN furniture_assets a ON c.asset_id = a.asset_id
        JOIN products p ON a.product_id = p.product_id
        ORDER BY r.return_id DESC
    """)

    return render_template("admin.html", summary=summary, contracts=contracts, assets=assets, returns=returns)

@app.route("/return/<int:contract_id>", methods=["GET", "POST"])
def register_return(contract_id):
    """Registrerer en returnering på en aftale - IKEA-INTERN handling.

    Stand ved retur, transportafstand og køretøjstype er IKEAs autoritative
    vurdering, som finder sted når IKEA henter møblet. Ruten er derfor kun
    indgået fra det interne dashboard (/admin -> "Registrer retur"). Kunden
    har sin egen, separate "Anmod om afhentning"-rute i ``pickup_request()``,
    som ikke skriver til databasen.

    GET viser ``return.html`` med formularfelter (stand, distance, køretøjstype,
    skadenoter), prefyldt med aftalens metadata.

    POST behandler indsendelsen i én transaktion:

    1. Opret ``return_cases``-række.
    2. Opret ``refurbishment_activities``-række med action/CO2e fra
       ``refurb_plan()``.
    3. Opret ``transport_events``-række med beregnet transport-CO2e
       (``distance_km × emissionsfaktor``).
    4. Genberegn ``impact_results.co2e_saved_kg`` =
       ``baseline − cirkulær − SUM(transport_events.co2e_kg)`` og opdatér
       ``calculated_at``.
    5. Sæt asset til ``available``/``refurbishment``/``recycling`` afhængigt af
       næste handling, og inkrementér ``lifecycle_count``.
    6. Sæt kontrakt-status til ``'returned'``.
    7. Log integration-event.

    Render bagefter ``return_success.html`` med transportemission, ny besparelse
    og en knap tilbage til oversigten.

    Args:
        contract_id: ID på den aftale der returneres.
    """
    # Customer til topbar (kan være None — ruten kaldes typisk af IKEA-personale
    # via /admin og ikke nødvendigvis med en kunde-session aktiv).
    customer_row = None
    if "customer_id" in session:
        customer_row = fetch_one("""
            SELECT customer_id, company_name, cvr_number, contact_person
            FROM customers WHERE customer_id = %s
        """, (session["customer_id"],))

    contract = fetch_one("""
        SELECT c.contract_id, p.product_name, a.asset_id, a.serial_number,
               cu.company_name, cu.cvr_number, cu.contact_person
        FROM faas_contracts c
        JOIN customers cu ON c.customer_id = cu.customer_id
        JOIN furniture_assets a ON c.asset_id = a.asset_id
        JOIN products p ON a.product_id = p.product_id
        WHERE c.contract_id = %s
    """, (contract_id,))

    if request.method == "GET":
        return render_template("return.html", contract=contract, customer=customer_row)

    condition_grade = request.form["condition_grade"]
    damage_notes = request.form["damage_notes"]
    distance_km = Decimal(request.form["distance_km"])
    vehicle_type = request.form["vehicle_type"]

    action_type, cost_dkk, refurb_co2, new_grade, next_action = refurb_plan(condition_grade)
    return_transport_co2e = transport_co2e(distance_km, vehicle_type)

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        conn.start_transaction()

        cursor.execute("""
            INSERT INTO return_cases (contract_id, return_date, condition_grade, damage_notes, next_action)
            VALUES (%s, %s, %s, %s, %s)
        """, (contract_id, date.today(), condition_grade, damage_notes, next_action))

        return_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO refurbishment_activities (return_id, action_type, cost_dkk, co2e_kg, new_condition_grade)
            VALUES (%s, %s, %s, %s, %s)
        """, (return_id, action_type, cost_dkk, refurb_co2, new_grade))

        cursor.execute("""
            INSERT INTO transport_events (return_id, from_location, to_location, distance_km, vehicle_type, co2e_kg)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (return_id, "Customer home", "IKEA return hub", distance_km, vehicle_type, return_transport_co2e))

        cursor.execute("""
            SELECT
                ir.baseline_co2e_kg,
                ir.circular_co2e_kg,
                COALESCE((
                    SELECT SUM(te.co2e_kg)
                    FROM transport_events te
                    JOIN return_cases rc ON te.return_id = rc.return_id
                    WHERE rc.contract_id = %s
                ), 0) AS total_transport_co2e
            FROM impact_results ir
            WHERE ir.contract_id = %s
        """, (contract_id, contract_id))
        impact_row = cursor.fetchone()

        baseline = Decimal(str(impact_row["baseline_co2e_kg"]))
        circular = Decimal(str(impact_row["circular_co2e_kg"]))
        transport_total = Decimal(str(impact_row["total_transport_co2e"]))
        new_co2e_saved = baseline - circular - transport_total
        if new_co2e_saved < 0:
            new_co2e_saved = Decimal("0.00")
        new_co2e_saved = round(new_co2e_saved, 2)

        cursor.execute("""
            UPDATE impact_results
            SET co2e_saved_kg = %s, calculated_at = CURRENT_TIMESTAMP
            WHERE contract_id = %s
        """, (new_co2e_saved, contract_id))

        new_status = "available"
        if next_action == "refurbish":
            new_status = "refurbishment"
        elif next_action == "recycle":
            new_status = "recycling"

        cursor.execute("""
            UPDATE furniture_assets a
            JOIN faas_contracts c ON a.asset_id = c.asset_id
            SET a.status = %s,
                a.condition_grade = %s,
                a.lifecycle_count = a.lifecycle_count + 1
            WHERE c.contract_id = %s
        """, (new_status, new_grade, contract_id))

        cursor.execute("""
            UPDATE faas_contracts
            SET status = 'returned'
            WHERE contract_id = %s
        """, (contract_id,))

        cursor.execute("""
            INSERT INTO integration_log (source_system, target_system, event_type, status)
            VALUES (%s, %s, %s, %s)
        """, ("FaaS prototype", "Warehouse and refurbishment system", "return_registered", "sent"))

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    return render_template(
        "return_success.html",
        contract_id=contract_id,
        transport_co2e=return_transport_co2e,
        new_co2e_saved=new_co2e_saved,
        vehicle_type=vehicle_type,
        distance_km=distance_km,
        customer=customer_row,
        contract=contract,
    )

@app.route("/pickup-request/<int:contract_id>", methods=["GET", "POST"])
def pickup_request(contract_id):
    """Kundens afhentningsanmodning (POC, ingen persistens).

    Den autoritative returregistrering (stand, transport, CO2e-beregning) er
    en IKEA-intern handling, der kun er tilgaengelig via /admin -> /return/<id>.
    Denne rute giver kunden en simpel måde at signalere at møblet er klar til
    afhentning, plus en valgfri fritekstbemærkning om observerede skader.

    GET render formular. POST viser bekræftelsesside med den indtastede tekst
    echoet tilbage. Intet skrives til databasen, og der sættes ingen status
    på kontrakten — IKEA ændrer staten når de rent faktisk har vurderet og
    registreret returen.
    """
    if "customer_id" not in session:
        return redirect(url_for("login"))

    customer_row = fetch_one("""
        SELECT customer_id, company_name, cvr_number, contact_person
        FROM customers WHERE customer_id = %s
    """, (session["customer_id"],))

    contract = fetch_one("""
        SELECT c.contract_id, c.status, p.product_name, a.serial_number,
               cu.company_name, cu.cvr_number, cu.contact_person
        FROM faas_contracts c
        JOIN customers cu ON c.customer_id = cu.customer_id
        JOIN furniture_assets a ON c.asset_id = a.asset_id
        JOIN products p ON a.product_id = p.product_id
        WHERE c.contract_id = %s
    """, (contract_id,))

    if not contract:
        return "Aftalen findes ikke.", 404

    if request.method == "GET":
        return render_template(
            "pickup_request.html",
            contract=contract,
            customer=customer_row,
        )

    # POST: echo notes tilbage på bekræftelsessiden. Intet persisteres.
    customer_notes = request.form.get("customer_notes", "").strip()
    return render_template(
        "pickup_request_success.html",
        contract=contract,
        customer=customer_row,
        customer_notes=customer_notes,
    )


@app.route("/customer/<int:customer_id>")
def customer(customer_id):
    """Kundeprofil med samlet CO2e-effekt og aftaleoversigt.

    Henter tre datasæt og render ``customer.html``:

    - Kunde-record (firma, kontakt, email, CVR, postnummer).
    - ``summary`` med antal aftaler (total + aktive), total/avg sparet,
      samlet baseline, cirkulær og transport.
    - ``contracts`` med kundens aftaler — hver med ``transport_co2e_kg``
      aggregeret fra ``transport_events`` joinet via ``return_cases``.

    Returnerer 404-tekst hvis customer_id ikke findes.

    Args:
        customer_id: ID på kunden der skal vises.
    """
    customer_row = fetch_one("""
        SELECT customer_id, company_name, cvr_number, contact_person, email, zip_code
        FROM customers
        WHERE customer_id = %s
    """, (customer_id,))

    if not customer_row:
        return "Kunden findes ikke.", 404

    summary = fetch_one("""
        SELECT
            COUNT(DISTINCT c.contract_id) AS contracts,
            COUNT(DISTINCT CASE WHEN c.status = 'active' THEN c.contract_id END) AS active_contracts,
            COALESCE(SUM(i.co2e_saved_kg), 0) AS total_saved,
            COALESCE(AVG(i.co2e_saved_kg), 0) AS avg_saved,
            COALESCE(SUM(i.baseline_co2e_kg), 0) AS total_baseline,
            COALESCE(SUM(i.circular_co2e_kg), 0) AS total_circular,
            COALESCE((
                SELECT SUM(te.co2e_kg)
                FROM faas_contracts c2
                JOIN return_cases rc ON rc.contract_id = c2.contract_id
                JOIN transport_events te ON te.return_id = rc.return_id
                WHERE c2.customer_id = %s
            ), 0) AS total_transport
        FROM faas_contracts c
        LEFT JOIN impact_results i ON c.contract_id = i.contract_id
        WHERE c.customer_id = %s
    """, (customer_id, customer_id))

    contracts = fetch_all("""
        SELECT
            c.contract_id,
            c.status,
            c.start_date,
            c.end_date,
            p.product_name,
            a.serial_number,
            i.baseline_co2e_kg,
            i.circular_co2e_kg,
            COALESCE(t.transport_co2e_kg, 0) AS transport_co2e_kg,
            i.co2e_saved_kg
        FROM faas_contracts c
        JOIN furniture_assets a ON c.asset_id = a.asset_id
        JOIN products p ON a.product_id = p.product_id
        LEFT JOIN impact_results i ON c.contract_id = i.contract_id
        LEFT JOIN (
            SELECT rc.contract_id, SUM(te.co2e_kg) AS transport_co2e_kg
            FROM return_cases rc
            JOIN transport_events te ON te.return_id = rc.return_id
            GROUP BY rc.contract_id
        ) t ON t.contract_id = c.contract_id
        WHERE c.customer_id = %s
        ORDER BY c.contract_id DESC
    """, (customer_id,))

    return render_template(
        "customer.html",
        customer=customer_row,
        summary=summary,
        contracts=contracts
    )

# ============ JSON API-endpoints ============

@app.route("/api/products")
def api_products():
    """JSON-endpoint: liste over alle produkter.

    Tænkt som integrationspunkt for eksterne systemer (CRM, sortimentsstyring).

    Returns:
        JSON-array af produkt-dicts sorteret efter ``product_name``.
    """
    products = fetch_all("SELECT * FROM products ORDER BY product_name")
    return jsonify(products)

@app.route("/api/dashboard")
def api_dashboard():
    """JSON-endpoint: summary over aftaler og samlet CO2e-besparelse.

    Returns:
        JSON-objekt med felterne ``contracts``, ``total_saved`` og ``avg_saved``.
    """
    summary = fetch_one("""
        SELECT
            COUNT(DISTINCT c.contract_id) AS contracts,
            COALESCE(SUM(i.co2e_saved_kg), 0) AS total_saved,
            COALESCE(AVG(i.co2e_saved_kg), 0) AS avg_saved
        FROM faas_contracts c
        LEFT JOIN impact_results i ON c.contract_id = i.contract_id
    """)
    return jsonify(summary)


# ============ Autentificering ============

@app.route("/login", methods=["GET", "POST"])
def login():
    """Login-side med email + adgangskode for eksisterende erhvervskunder.

    GET render ``login.html``.

    POST slår brugeren op på email, verificerer adgangskoden mod
    ``password_hash`` via ``werkzeug.security.check_password_hash``, gemmer
    ``customer_id`` i Flask-sessionen og redirecter til
    ``/customer/<customer_id>``.

    Ved fejl render samme login-side med en venlig fejlmeddelelse.
    """
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    if not email or not password:
        return render_template("login.html", error="Udfyld både email og adgangskode."), 400

    user = fetch_one(
        "SELECT customer_id, password_hash FROM customers WHERE LOWER(email) = %s",
        (email,)
    )

    if not user or not user["password_hash"] or not check_password_hash(user["password_hash"], password):
        return render_template("login.html", error="Forkert email eller adgangskode."), 401

    session.clear()
    session["customer_id"] = user["customer_id"]
    return redirect(url_for("home"))


@app.route("/signup/business", methods=["GET", "POST"])
def signup_business():
    """Erhvervskunde-registrering med firmaoplysninger og adgangskode.

    GET render ``signup_business.html``.

    POST validerer formularen (påkrævet vilkår-checkbox + ingen eksisterende
    CVR/email), opretter en ny customer-record med hashed password og logger
    brugeren ind via session, derefter redirect til ``/customer/<id>``.
    """
    if request.method == "GET":
        return render_template("signup_business.html")

    # Hent formfelter
    company_name = request.form.get("company_name", "").strip()
    cvr_number = request.form.get("cvr_number", "").strip()
    first_name = request.form.get("first_name", "").strip()
    last_name = request.form.get("last_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    zip_code = request.form.get("zip_code", "").strip()
    password = request.form.get("password", "")
    terms_accepted = request.form.get("terms_accepted") == "on"

    contact_person = f"{first_name} {last_name}".strip()

    # Server-side validering — backend kan ikke stole på client-side disabled-knap.
    errors = []
    if not terms_accepted:
        errors.append("Du skal acceptere Vilkår og betingelser for at fortsætte.")
    if not company_name or not cvr_number or not contact_person or not email:
        errors.append("Virksomhedsnavn, CVR, kontaktperson og email er påkrævet.")
    if len(password) < 8:
        errors.append("Adgangskoden skal være mindst 8 tegn.")

    # Tjek for eksisterende CVR og email hver for sig, så fejlmeddelelsen er
    # specifik om hvilket felt der støder.
    if not errors:
        existing_cvr = fetch_one(
            "SELECT customer_id FROM customers WHERE cvr_number = %s",
            (cvr_number,)
        )
        if existing_cvr:
            errors.append(
                f"CVR-nummeret {cvr_number} er allerede registreret. "
                f"Brug login i stedet eller indtast et andet CVR."
            )

        existing_email = fetch_one(
            "SELECT customer_id FROM customers WHERE LOWER(email) = %s",
            (email,)
        )
        if existing_email:
            errors.append(
                f"E-mailen {email} er allerede i brug. "
                f"Brug login i stedet eller indtast en anden e-mail."
            )

    if errors:
        return render_template(
            "signup_business.html",
            errors=errors,
            form=request.form
        ), 400

    # Opret ny kunde
    password_hash = generate_password_hash(password)
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO customers (company_name, cvr_number, contact_person, email, zip_code, password_hash)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (company_name, cvr_number, contact_person, email, zip_code, password_hash))
        new_customer_id = cursor.lastrowid
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    session.clear()
    session["customer_id"] = new_customer_id
    return redirect(url_for("home"))


@app.route("/logout")
def logout():
    """Tømmer session og redirecter til login-siden."""
    session.clear()
    return redirect(url_for("login"))


# ============ Webshop: produkt, kurv, checkout ============

@app.route("/product/<int:product_id>")
def product(product_id):
    """Produktdetalje-side med både køb- og lease-CTA'er.

    Render ``product.html`` med fuld produktinfo, antal ledige assets og
    klimanøgletal. Tilgængelig for alle (logget ind eller ej) — men 'Læg i
    kurv' kræver login.
    """
    p = fetch_one("""
        SELECT p.*, COUNT(CASE WHEN a.status = 'available' THEN 1 END) AS available_assets
        FROM products p
        LEFT JOIN furniture_assets a ON p.product_id = a.product_id
        WHERE p.product_id = %s
        GROUP BY p.product_id
    """, (product_id,))

    if not p:
        return "Produktet findes ikke.", 404

    # Customer for topbar (kan være None)
    customer_row = None
    if "customer_id" in session:
        customer_row = fetch_one("""
            SELECT customer_id, company_name, contact_person FROM customers
            WHERE customer_id = %s
        """, (session["customer_id"],))

    return render_template("product.html", product=p, customer=customer_row)


@app.route("/cart/add", methods=["POST"])
def cart_add():
    """Tilføjer en linje til session-kurven og redirecter til kurven.

    Forventer form-felter: ``product_id``, ``kind`` ('purchase' eller 'lease'),
    og for lease også ``rental_months``. Slår produkt-info op for at gemme
    snapshot af pris og navn i kurven (så priser ikke ændres efter checkout-start).
    """
    if "customer_id" not in session:
        return redirect(url_for("login"))

    product_id = int(request.form["product_id"])
    kind = request.form.get("kind", "purchase")

    p = fetch_one(
        "SELECT product_id, product_name, monthly_price_dkk, sale_price_dkk, image_url, category FROM products WHERE product_id = %s",
        (product_id,)
    )
    if not p:
        return "Produktet findes ikke.", 404

    if kind == "lease":
        months = int(request.form.get("rental_months", 3))
        unit_price = Decimal(str(p["monthly_price_dkk"]))
        line_total = unit_price * months
        item = {
            "product_id": p["product_id"],
            "product_name": p["product_name"],
            "image_url": p.get("image_url"),
            "category": p.get("category"),
            "kind": "lease",
            "rental_months": months,
            "unit_price": float(unit_price),
            "line_total": float(line_total),
        }
    else:
        unit_price = Decimal(str(p["sale_price_dkk"]))
        item = {
            "product_id": p["product_id"],
            "product_name": p["product_name"],
            "image_url": p.get("image_url"),
            "category": p.get("category"),
            "kind": "purchase",
            "rental_months": None,
            "unit_price": float(unit_price),
            "line_total": float(unit_price),
        }

    items = cart_get()
    items.append(item)
    cart_save(items)
    return redirect(url_for("cart"))


@app.route("/cart/remove/<int:index>", methods=["POST"])
def cart_remove(index):
    """Fjerner en linje fra kurven (1-baseret index fra UI'et)."""
    items = cart_get()
    if 0 <= index < len(items):
        items.pop(index)
        cart_save(items)
    return redirect(url_for("cart"))


@app.route("/cart")
def cart():
    """Kurv-side med opsummering: køb-i-dag vs. lease-månedligt vs. samlet
    lejeforpligtelse.

    Kræver login. Hvis kurven er tom, viser fallback med 'Til forsiden'-link.
    """
    if "customer_id" not in session:
        return redirect(url_for("login"))

    customer_row = fetch_one("""
        SELECT customer_id, company_name, cvr_number, contact_person, email, zip_code
        FROM customers WHERE customer_id = %s
    """, (session["customer_id"],))

    items = cart_get()

    # Split totaler: engangskøb (skal betales i dag), månedlig leje (recurring),
    # og samlet lejeforpligtelse (informativ — sum over hele perioden).
    purchase_total = Decimal("0.00")
    lease_monthly_total = Decimal("0.00")
    lease_commitment_total = Decimal("0.00")
    for it in items:
        if it.get("kind") == "lease":
            lease_monthly_total += Decimal(str(it.get("unit_price", 0)))
            lease_commitment_total += Decimal(str(it.get("line_total", 0)))
        else:
            purchase_total += Decimal(str(it.get("line_total", 0)))

    return render_template(
        "cart.html",
        customer=customer_row,
        items=items,
        purchase_total=purchase_total,
        lease_monthly_total=lease_monthly_total,
        lease_commitment_total=lease_commitment_total,
        due_today=purchase_total,
    )


@app.route("/checkout", methods=["POST"])
def checkout():
    """Finaliserer ordren — itererer hver kurv-linje og opretter enten en
    purchase- eller en faas_contracts-record.

    Atomic transaktion: enten oprettes alt eller intet. Efter succes ryddes
    kurven og brugeren lander på ``checkout_success.html`` med en liste over
    hvad der blev oprettet, plus links til hver lease-aftales kvittering.
    """
    if "customer_id" not in session:
        return redirect(url_for("login"))

    items = cart_get()
    if not items:
        return redirect(url_for("cart"))

    customer_id = session["customer_id"]
    created_purchases = []   # [{purchase_id, product_name, price}]
    created_contracts = []   # [{contract_id, product_name, co2e_saved}]

    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        conn.start_transaction()

        for item in items:
            product_id = item["product_id"]

            # Find ledigt asset for produktet
            cursor.execute("""
                SELECT a.asset_id, a.lifecycle_count, p.baseline_co2e_kg,
                       p.monthly_price_dkk, p.expected_lifespan_years, p.sale_price_dkk
                FROM furniture_assets a
                JOIN products p ON a.product_id = p.product_id
                WHERE a.product_id = %s AND a.status = 'available'
                ORDER BY a.condition_grade, a.lifecycle_count DESC
                LIMIT 1
            """, (product_id,))
            asset = cursor.fetchone()
            if not asset:
                raise ValueError(f"Ingen ledige assets for {item['product_name']}.")

            if item["kind"] == "purchase":
                # Indsæt purchase + marker asset som 'sold'
                cursor.execute("""
                    INSERT INTO purchases (customer_id, product_id, asset_id, sale_price_dkk)
                    VALUES (%s, %s, %s, %s)
                """, (customer_id, product_id, asset["asset_id"], asset["sale_price_dkk"]))
                purchase_id = cursor.lastrowid

                cursor.execute(
                    "UPDATE furniture_assets SET status = 'sold' WHERE asset_id = %s",
                    (asset["asset_id"],)
                )

                cursor.execute("""
                    INSERT INTO integration_log (source_system, target_system, event_type, status)
                    VALUES (%s, %s, %s, %s)
                """, ("FaaS prototype", "Order management", "purchase_created", "sent"))

                created_purchases.append({
                    "purchase_id": purchase_id,
                    "product_name": item["product_name"],
                    "price": float(asset["sale_price_dkk"]),
                })

            else:  # lease
                months = int(item["rental_months"])
                start_date = date.today()
                end_date = date(
                    start_date.year + ((start_date.month + months - 1) // 12),
                    ((start_date.month + months - 1) % 12) + 1,
                    start_date.day
                )
                monthly_price = Decimal(str(asset["monthly_price_dkk"]))

                cursor.execute("""
                    INSERT INTO faas_contracts (customer_id, asset_id, start_date, end_date, monthly_price, status)
                    VALUES (%s, %s, %s, %s, %s, 'active')
                """, (customer_id, asset["asset_id"], start_date, end_date, monthly_price))
                contract_id = cursor.lastrowid

                cursor.execute(
                    "UPDATE furniture_assets SET status = 'leased' WHERE asset_id = %s",
                    (asset["asset_id"],)
                )

                impact = calculate_contract_impact(
                    asset["baseline_co2e_kg"],
                    asset["expected_lifespan_years"],
                    months
                )
                cursor.execute("""
                    INSERT INTO impact_results (contract_id, baseline_co2e_kg, circular_co2e_kg, co2e_saved_kg)
                    VALUES (%s, %s, %s, %s)
                """, (contract_id, impact["baseline_co2e_kg"], impact["circular_co2e_kg"], impact["co2e_saved_kg"]))

                cursor.execute("""
                    INSERT INTO integration_log (source_system, target_system, event_type, status)
                    VALUES (%s, %s, %s, %s)
                """, ("FaaS prototype", "CRM and sustainability reporting", "contract_created", "sent"))

                created_contracts.append({
                    "contract_id": contract_id,
                    "product_name": item["product_name"],
                    "co2e_saved": float(impact["co2e_saved_kg"]),
                    "rental_months": months,
                })

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

    # Ryd kurv og vis kvittering
    cart_save([])

    customer_row = fetch_one("""
        SELECT customer_id, company_name, contact_person FROM customers WHERE customer_id = %s
    """, (customer_id,))

    return render_template(
        "checkout_success.html",
        customer=customer_row,
        purchases=created_purchases,
        contracts=created_contracts,
    )


# ============ Fejlhåndtering ============

@app.errorhandler(Error)
def database_error(error):
    """Flask error handler for ``mysql.connector.Error``.

    Returnerer en plain-text fejlmeddelelse med HTTP 500 i stedet for Flasks
    standard-traceback, så MySQL-fejl ikke lækker stack til klienten.
    """
    return f"Databasefejl: {error}", 500

if __name__ == "__main__":
    app.run(debug=True)
