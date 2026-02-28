# DEPRECATED (kept intentionally for now)
GQL_PLAN = """
query PlanTrip(
  $fromLat: Float!,
  $fromLon: Float!,
  $toLat: Float!,
  $toLon: Float!,
  $date: String!,
  $time: String!
) {
  plan(
    from: {lat: $fromLat, lon: $fromLon}
    to: {lat: $toLat, lon: $toLon}
    date: $date
    time: $time
    numItineraries: 3
    transportModes: [{mode: TRANSIT}, {mode: WALK}]
  ) {
    itineraries {
      legs {
        mode
        startTime
        endTime
        duration
        route {
          shortName
          longName
        }
        from { name lat lon }
        to { name lat lon }
      }
    }
  }
}
"""

GQL_STOPS = """
query Stops {
  stops {
    name
    lat
    lon
  }
}
"""
