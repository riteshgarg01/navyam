CREATE TABLE tariffs (
    id SERIAL PRIMARY KEY,
    state TEXT,
    min_slab INTEGER,
    max_slab INTEGER,
    fixed NUMERIC,          -- Replaced REAL with NUMERIC for precision
    variable NUMERIC,       -- Replaced REAL with NUMERIC for precision
    max_bill NUMERIC
);

CREATE TABLE multipliers (
    id SERIAL PRIMARY KEY,
    state TEXT,
    month TEXT,
    multiplier NUMERIC
);

CREATE TABLE installation_costs (
    id SERIAL PRIMARY KEY,
    location_tier TEXT,
    system_capacity_kW INTEGER,
    overall_cost NUMERIC
);
