USE ikea_faas;

INSERT INTO products (product_name, category, material_type, baseline_co2e_kg, expected_lifespan_years, monthly_price_dkk)
VALUES
('LAGKAPTEN Skrivebord',     'Desk',  'Particleboard and steel', 45.00,  8,  99.00),
('MARKUS Kontorstol',        'Chair', 'Textile, steel and foam', 55.00,  10, 149.00),
('LANDSKRONA 3-pers. sofa',  'Sofa',  'Gunnared blå, træ',       120.00, 12, 299.00),
('POÄNG Lænestol',           'Chair', 'Wood veneer and textile', 42.00,  10, 119.00);

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
