-- Check if 'navyam' database exists; create it if not
DO
$$
BEGIN
   IF NOT EXISTS (SELECT FROM pg_database WHERE datname = 'navyam') THEN
      CREATE DATABASE navyam;
   END IF;
END
$$;

-- Connect to the navyam database
\c navyam;

-- Create the `tariffs` table
CREATE TABLE IF NOT EXISTS tariffs (
    id SERIAL PRIMARY KEY,
    state TEXT,
    min_slab INTEGER,
    max_slab INTEGER,
    fixed REAL,
    variable REAL,
    max_bill REAL
);

-- Create the `multipliers` table
CREATE TABLE IF NOT EXISTS multipliers (
    id SERIAL PRIMARY KEY,
    state TEXT,
    month TEXT,
    multiplier REAL
);

-- Create the `installation_costs` table
CREATE TABLE IF NOT EXISTS installation_costs (
    id SERIAL PRIMARY KEY,
    location_tier TEXT,
    system_capacity_kW INTEGER,
    overall_cost REAL
);

-- Load data into the tariffs table
COPY tariffs (id, state, min_slab, max_slab, fixed, variable, max_bill)
FROM '/docker-entrypoint-initdb.d/tariffs.csv' DELIMITER '|' CSV;

-- Load data into the multipliers table
COPY multipliers (id, state, month, multiplier)
FROM '/docker-entrypoint-initdb.d/multipliers.csv' DELIMITER '|' CSV;

-- Load data into the installation_costs table
COPY installation_costs (id, location_tier, system_capacity_kW, overall_cost)
FROM '/docker-entrypoint-initdb.d/installation_costs.csv' DELIMITER '|' CSV;
