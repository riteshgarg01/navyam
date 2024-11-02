import sqlite3

# Connect to the database
def connect_db():
    return sqlite3.connect('solar.db')

# Calculate the max bill for each slab and update the database
def update_max_bill():
    conn = connect_db()
    cursor = conn.cursor()
    
    # Fetch all tariff data
    query = "SELECT id, min_slab, max_slab, fixed, variable FROM tariffs"
    cursor.execute(query)
    tariffs = cursor.fetchall()
    
    # Calculate and update the max bill for each slab
    for tariff in tariffs:
        tariff_id = tariff[0]
        min_slab = tariff[1]
        max_slab = tariff[2]
        fixed_charge = tariff[3]
        variable_rate = tariff[4]

        # Skip if it's the 'infinity' slab
        if max_slab == 999999:
            max_bill = None
        else:
            # Calculate units in the slab and then the max bill
            max_bill = fixed_charge + (max_slab * variable_rate)

        # Update the max_bill column in the database
        update_query = "UPDATE tariffs SET max_bill = ? WHERE id = ?"
        cursor.execute(update_query, (max_bill, tariff_id))
    
    # Commit the changes and close the connection
    conn.commit()
    conn.close()


# update installation costs for a defined system size
def update_fixed_cost():
    conn = connect_db()
    cursor = conn.cursor()
    
    # Fetch all tariff data
    query = "SELECT id, location_tier, system_capacity_kW, overall_cost FROM installation_costs"
    cursor.execute(query)
    costs = cursor.fetchall()
    
    # Calculate and update the max bill for each slab
    for cost in costs:
        costs_id = cost[0]
        local_location_tier = cost[1]
        local_system_capacity = cost[2]
        variable_cost = cost[3]

        # Skip if it's the 'infinity' slab
        if local_system_capacity < 4:
            total_fixed_cost = 50000
        elif local_system_capacity < 7:
            total_fixed_cost = 100000
        else:
            total_fixed_cost = 150000
        
        # Calculate total cost as sum of fixed and variable costs
        total_installation_cost = total_fixed_cost + variable_cost

        # Update the costs in the column
        update_query = "UPDATE installation_costs SET overall_cost = ? WHERE id = ?"
        cursor.execute(update_query, (total_installation_cost, costs_id))
    
    # Commit the changes and close the connection
    conn.commit()
    conn.close()

# Run the update
update_fixed_cost()
print("Max bills updated successfully!")
