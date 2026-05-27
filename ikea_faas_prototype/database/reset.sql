-- =====================================================================
-- reset.sql — komplet nulstilling og opbygning af ikea_faas
-- ADVARSEL: Dropper alle tabeller og sletter al data. Kør kun i dev.
-- Kør hele filen i MySQL Workbench eller via:
--   mysql -u <bruger> -p < database/reset.sql
-- =====================================================================

CREATE DATABASE IF NOT EXISTS ikea_faas
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE ikea_faas;

-- ---------------------------------------------------------------------
-- 1. Drop alt i omvendt dependency-rækkefølge
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS purchases;
DROP TABLE IF EXISTS integration_log;
DROP TABLE IF EXISTS impact_results;
DROP TABLE IF EXISTS transport_events;
DROP TABLE IF EXISTS refurbishment_activities;
DROP TABLE IF EXISTS return_cases;
DROP TABLE IF EXISTS faas_contracts;
DROP TABLE IF EXISTS furniture_assets;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

-- ---------------------------------------------------------------------
-- 2. Opret tabeller
-- ---------------------------------------------------------------------
CREATE TABLE customers (
    customer_id INT AUTO_INCREMENT PRIMARY KEY,
    company_name VARCHAR(150) NOT NULL,
    cvr_number VARCHAR(20) UNIQUE,
    contact_person VARCHAR(100) NOT NULL,
    email VARCHAR(150) NOT NULL,
    zip_code VARCHAR(20),
    password_hash VARCHAR(255) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE products (
    product_id INT AUTO_INCREMENT PRIMARY KEY,
    product_name VARCHAR(100) NOT NULL,
    category VARCHAR(80) NOT NULL,
    material_type VARCHAR(80) NOT NULL,
    baseline_co2e_kg DECIMAL(10,2) NOT NULL,
    expected_lifespan_years INT NOT NULL,
    monthly_price_dkk DECIMAL(10,2) NOT NULL,
    sale_price_dkk DECIMAL(10,2) NOT NULL,
    image_url VARCHAR(255) NULL
);

CREATE TABLE furniture_assets (
    asset_id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    serial_number VARCHAR(80) NOT NULL UNIQUE,
    condition_grade ENUM('A','B','C','D') NOT NULL DEFAULT 'A',
    status ENUM('available','leased','sold','returned','refurbishment','recycling') NOT NULL DEFAULT 'available',
    lifecycle_count INT NOT NULL DEFAULT 0,
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE TABLE faas_contracts (
    contract_id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    asset_id INT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    monthly_price DECIMAL(10,2) NOT NULL,
    status ENUM('active','returned','closed') NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (asset_id) REFERENCES furniture_assets(asset_id)
);

CREATE TABLE return_cases (
    return_id INT AUTO_INCREMENT PRIMARY KEY,
    contract_id INT NOT NULL,
    return_date DATE NOT NULL,
    condition_grade ENUM('A','B','C','D') NOT NULL,
    damage_notes TEXT,
    next_action ENUM('resell','refurbish','recycle') NOT NULL,
    FOREIGN KEY (contract_id) REFERENCES faas_contracts(contract_id)
);

CREATE TABLE refurbishment_activities (
    refurb_id INT AUTO_INCREMENT PRIMARY KEY,
    return_id INT NOT NULL,
    action_type VARCHAR(100) NOT NULL,
    cost_dkk DECIMAL(10,2) NOT NULL,
    co2e_kg DECIMAL(10,2) NOT NULL,
    new_condition_grade ENUM('A','B','C','D') NOT NULL,
    FOREIGN KEY (return_id) REFERENCES return_cases(return_id)
);

CREATE TABLE transport_events (
    transport_id INT AUTO_INCREMENT PRIMARY KEY,
    return_id INT NOT NULL,
    from_location VARCHAR(100) NOT NULL,
    to_location VARCHAR(100) NOT NULL,
    distance_km DECIMAL(10,2) NOT NULL,
    vehicle_type ENUM('diesel_van','electric_van','cargo_bike','truck') NOT NULL,
    co2e_kg DECIMAL(10,2) NOT NULL,
    FOREIGN KEY (return_id) REFERENCES return_cases(return_id)
);

CREATE TABLE impact_results (
    impact_id INT AUTO_INCREMENT PRIMARY KEY,
    contract_id INT NOT NULL,
    baseline_co2e_kg DECIMAL(10,2) NOT NULL,
    circular_co2e_kg DECIMAL(10,2) NOT NULL,
    co2e_saved_kg DECIMAL(10,2) NOT NULL,
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (contract_id) REFERENCES faas_contracts(contract_id)
);

CREATE TABLE integration_log (
    integration_id INT AUTO_INCREMENT PRIMARY KEY,
    source_system VARCHAR(100) NOT NULL,
    target_system VARCHAR(100) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    status ENUM('pending','sent','failed') NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE purchases (
    purchase_id INT AUTO_INCREMENT PRIMARY KEY,
    customer_id INT NOT NULL,
    product_id INT NOT NULL,
    asset_id INT NULL,
    sale_price_dkk DECIMAL(10,2) NOT NULL,
    purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    FOREIGN KEY (asset_id) REFERENCES furniture_assets(asset_id)
);

-- ---------------------------------------------------------------------
-- 3. Seed: produkter med priser
-- ---------------------------------------------------------------------
INSERT INTO products
  (product_name, category, material_type, baseline_co2e_kg, expected_lifespan_years, monthly_price_dkk, sale_price_dkk, image_url)
VALUES
  ('LAGKAPTEN Skrivebord',     'Desk',  'Particleboard and steel', 45.00,  8,  99.00,  399.00,  'images/lagkapten-skrivebord.jpg'),
  ('MARKUS Kontorstol',        'Chair', 'Textile, steel and foam', 55.00,  10, 149.00, 1899.00, 'images/markus-kontorstol.jpg'),
  ('LANDSKRONA 3-pers. sofa',  'Sofa',  'Gunnared blå, træ',       120.00, 12, 299.00, 8995.00, 'images/landskrona-sofa.jpg'),
  ('POÄNG Lænestol',           'Chair', 'Wood veneer and textile', 42.00,  10, 119.00, 999.00,  'images/poang-laenestol.jpg');

-- ---------------------------------------------------------------------
-- 4. Seed: møbel-assets
-- ---------------------------------------------------------------------
INSERT INTO furniture_assets (product_id, serial_number, condition_grade, status, lifecycle_count)
VALUES
  (1, 'DESK-FAAS-001',   'A', 'available', 1),
  (1, 'DESK-FAAS-002',   'B', 'available', 2),
  (2, 'CHAIR-FAAS-001',  'A', 'available', 1),
  (2, 'CHAIR-FAAS-002',  'B', 'available', 2),
  (3, 'SOFA-FAAS-001',   'A', 'available', 1),
  (3, 'SOFA-FAAS-002',   'B', 'available', 3),
  (4, 'LOUNGE-FAAS-001', 'A', 'available', 1),
  (4, 'LOUNGE-FAAS-002', 'B', 'available', 2);

-- ---------------------------------------------------------------------
-- 5. Seed: demo-kunder (valgfrit — kan slettes hvis du vil starte tom)
-- ---------------------------------------------------------------------
-- Demo-kunder. password_hash hasher demo-adgangskoden 'demo1234' (werkzeug scrypt).
INSERT INTO customers (company_name, cvr_number, contact_person, email, zip_code, password_hash)
VALUES
  ('Nordic Office ApS',   '12345678', 'Frank Jensen', 'frank@nordicoffice.dk',  '2100',
   'scrypt:32768:8:1$x1xbf1J4VSPnKUKM$86fa0684e82b0f02822548899a14bb7d988e39b20f79a50e4e91467ac99be2939b71e4194d20ca3ae610da3a915269b4321486c865febd0fd04fbc2c37151b51'),
  ('Green Workspace ApS', '87654321', 'Maria Larsen', 'maria@greenworkspace.dk', '2300',
   'scrypt:32768:8:1$x1xbf1J4VSPnKUKM$86fa0684e82b0f02822548899a14bb7d988e39b20f79a50e4e91467ac99be2939b71e4194d20ca3ae610da3a915269b4321486c865febd0fd04fbc2c37151b51');

-- ---------------------------------------------------------------------
-- 6. Verificer
-- ---------------------------------------------------------------------
SELECT product_id, product_name, monthly_price_dkk FROM products;
SELECT asset_id, product_id, serial_number, status FROM furniture_assets;
SELECT customer_id, company_name, contact_person FROM customers;


