import json

def decode_dsc_message(dsc_array):
    if len(dsc_array) < 22:
        raise ValueError("Array does not contain enough elements to decode a DSC message.")
    
    mmsi = ''.join([str(x) for x in dsc_array[0:9]])
    
    category_code = dsc_array[9]
    category_map = {
        100: "Routine",
        108: "Safety",
        110: "Urgency",
        112: "Distress"
    }
    category = category_map.get(category_code, "Unknown")
    
    # Decode nature of distress if category is Distress
    nature_of_distress = None
    if category == "Distress":
        nature_of_distress = dsc_array[10]
        nature_of_distress_map = {
            100: "Undesignated",
            101: "Fire, explosion",
            102: "Flooding",
            103: "Collision",
            104: "Grounding",
            105: "Listing, in danger of capsizing",
            106: "Sinking",
            107: "Disabled and adrift",
            108: "Abandoning ship",
            109: "Man overboard",
            110: "Piracy/armed attack",
            112: "Medical assistance"
        }
        nature_of_distress = nature_of_distress_map.get(nature_of_distress, "Unknown")
    
    # Decode Latitude
    lat_deg = dsc_array[11]
    lat_min = dsc_array[12]
    lat_dir = 'N' if dsc_array[13] <= 89 else 'S'
    latitude = f"{lat_deg}°{lat_min}'{lat_dir}"
    
    # Decode Longitude
    lon_deg = dsc_array[14]
    lon_min = dsc_array[15]
    lon_dir = 'E' if dsc_array[16] <= 179 else 'W'
    longitude = f"{lon_deg}°{lon_min}'{lon_dir}"
    
    # UT Time
    utc_hour = dsc_array[17]
    utc_minute = dsc_array[18]
    utc_time = f"{utc_hour:02}:{utc_minute:02}"
    
    # Additional Data (example, EOS, VHF channels etc.)
    eos = dsc_array[19]
    vhf_rx_channel = dsc_array[20]
    vhf_tx_channel = dsc_array[21]
    
    message = {
        "MMSI": mmsi,
        "Category": category,
        "Latitude": latitude,
        "Longitude": longitude,
        "UTC Time": utc_time,
        "EOS": eos,
        "VHF RX Channel": vhf_rx_channel,
        "VHF TX Channel": vhf_tx_channel
    }
    
    if nature_of_distress:
        message["Nature of Distress"] = nature_of_distress
    
    return json.dumps(message, indent=4)

# Example usage
dsc_array = [98, 76, 54, 32, 10, 100, 12, 34, 56, 78, 90, 109, 111, 90, 10, 69, 90, 10, 69, 127, 81,120]
json_message = decode_dsc_message(dsc_array)
print(json_message)
