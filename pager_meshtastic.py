import sys
import re
import csv
import fnmatch
import subprocess
import fileinput

def parse_pocsag_message(message):
    regex = r'POCSAG512:\s+Address:\s+(\d+)\s+Function:\s+\d+\s+Alpha:\s+(.+)'
    match = re.match(regex, message)
    if match:
        address = match.group(1)
        alpha = match.group(2).strip()
        return address, alpha
    else:
        return None, None

def convert_wildcard_to_fnmatch(address):
    return address.replace('%', '*')

def load_aliases(filename):
    aliases = []
    try:
        with open(filename, newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                address_pattern = convert_wildcard_to_fnmatch(row['address'])
                aliases.append((address_pattern, row['agency'], row['icon']))
        print(f"Debug: Loaded {len(aliases)} aliases", file=sys.stderr)
    except Exception as e:
        print(f"Error loading aliases: {e}", file=sys.stderr)
    return aliases

def main():
    aliases = load_aliases('alias.csv')

    try:
        for line in fileinput.input():
            line = line.strip()
            if line.startswith("POCSAG"):
                address, alpha = parse_pocsag_message(line)
                if address and alpha:
                    agency = "Unknown"
                    for address_pattern, agency_name, icon in reversed(aliases):
                        if fnmatch.fnmatchcase(address, address_pattern):
                            agency = agency_name
                            if icon == 'life-ring':
                                message = f"\07 RNLI {agency} {alpha}\07"
                            else:
                                message = f"RNLI {agency} {alpha}"
                            command = ["meshtastic", "--ch-index", "1", "--sendtext", message]
                            
                            print(f"Debug: Running command: {' '.join(command)}", file=sys.stderr)
                            subprocess.run(command, check=True)
                            break
                    else:
                        print("Debug: Agency not found, message not sent.", file=sys.stderr)
                else:
                    print("Debug: Address or alpha is None, message not processed.", file=sys.stderr)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
