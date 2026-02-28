from datetime import datetime, timedelta

from otp_service import otp_graphql, get_stop_coords, extract_primary_transit_leg_from_plan
from otp_queries import GQL_PLAN

START_NAME = "Fischen"
END_NAME = "Sonthofen"

def main():
    print(f"--- Test Trip: {START_NAME} -> {END_NAME} ---")

    start_lat, start_lon = get_stop_coords(START_NAME)
    end_lat, end_lon = get_stop_coords(END_NAME)

    tomorrow = datetime.now() + timedelta(days=1)
    trip_time = tomorrow.replace(hour=7, minute=30, second=0, microsecond=0)

    variables = {
        "fromLat": start_lat,
        "fromLon": start_lon,
        "toLat": end_lat,
        "toLon": end_lon,
        "date": trip_time.strftime("%Y-%m-%d"),
        "time": trip_time.strftime("%H:%M"),
    }

    print(f"📡 Sende Anfrage an OTP für {variables['date']} um {variables['time']}...")
    data = otp_graphql(GQL_PLAN, variables)

    leg = extract_primary_transit_leg_from_plan(data)
    if not leg:
        print("❌ Keine Transit-Verbindung gefunden.")
        return

    print("\n✅ ERFOLG: Verbindung gefunden!")
    print(f"   Modus:   {leg.transport_mode} {leg.carrier_number}")
    print(f"   Dauer:   {leg.duration_min} Min")
    print(f"   Abfahrt: {leg.departure_time}")
    print(f"   Ankunft: {leg.arrival_time}")

if __name__ == "__main__":
    main()
