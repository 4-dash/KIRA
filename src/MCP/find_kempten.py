import requests

OTP_URL = "http://localhost:8080/otp/routers/default/index/graphql"

query = """
{
  stops {
    name
  }
}
"""

print("📡 Frage OTP-Server nach Haltestellen...")

try:
    response = requests.post(OTP_URL, json={"query": query}, timeout=10)
    
    if response.status_code == 200:
        data = response.json()
        stops = data['data']['stops']
        print(f"✅ Verbindung steht! Habe {len(stops)} Haltestellen geladen.")
        
        print("\n🔍 Suche nach 'Kempten':")
        found = False
        for stop in stops:
            if "kempten" in stop['name'].lower():
                print(f"   - {stop['name']}")
                found = True
        
        if not found:
            print("❌ Kein Eintrag mit 'Kempten' gefunden.")
            print("   (Vielleicht heißt er 'Allgäu Hbf' oder ähnlich?)")
            
    else:
        print(f"❌ Server antwortet mit Fehler: {response.status_code}")

except Exception as e:
    print(f"❌ VERBINDUNGSFEHLER: {e}")
    print("   -> Prüfe dein PuTTY! Der Tunnel scheint zu zu sein.")