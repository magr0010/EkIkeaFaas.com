CREATE DATABASE IF NOT EXISTS ikea_faas
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE ikea_faas;

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
