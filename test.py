def calculate_monthly_bill(units_consumed, tariffs):
    """
    Calculate the electricity bill based on slab tariffs.
    
    Parameters:
    units_consumed (float): The amount of electricity consumed in kWh.
    tariffs (list): The slab-based tariffs for the state.
    
    Returns:
    float: The calculated monthly bill.
    """
    bill = 0
    for slab in tariffs:
        
        slab_units = 0
        if units_consumed > slab['max_slab']:
            bill += slab['max_bill']
        else:
            slab_units = units_consumed - slab['min_slab'] + 1

        if slab_units > 0:
            bill += slab_units * slab['variable'] + slab['fixed']
        
        # If the units consumed are less than the max slab, break the loop
        if units_consumed <= slab['max_slab']:
            break
    
    return bill

# Define tariff structure
tariffs = [
    {'min_slab': 1, 'max_slab': 50, 'fixed': 230, 'variable': 4.75, 'max_bill': 467.5},
    {'min_slab': 51, 'max_slab': 150, 'fixed': 230, 'variable': 6.50, 'max_bill': 880.0},
    {'min_slab': 151, 'max_slab': 300, 'fixed': 275, 'variable': 7.35, 'max_bill': 1882.5},
    {'min_slab': 301, 'max_slab': 500, 'fixed': 345, 'variable': 7.65, 'max_bill': 3145.0},
    {'min_slab': 501, 'max_slab': float('inf'), 'fixed': 400, 'variable': 7.95, 'max_bill': None}
]

# Test with 420 units consumed
units_consumed = 420
bill = calculate_monthly_bill(units_consumed, tariffs)
print(f"Total bill for 420 units: ₹{bill:.2f}")