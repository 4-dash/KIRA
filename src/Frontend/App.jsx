import React, { useState, useEffect, useRef } from 'react';
import { Send, Map as MapIcon, Navigation, Star, MapPin, Menu, X, Globe, User, Bot, Loader2, AlertCircle, Filter, Sliders, Train, Bus, Footprints, Clock, ArrowRight, Flag, Save, Check, Download, Upload} from 'lucide-react';

// --- Konfiguration & Mock-Daten ---

const INITIAL_MESSAGE = {
  id: 1,
  sender: 'ai',
  text: "Guten Tag! Ich bin KIRA. Wohin möchtest du reisen?",
};

// --- Komponenten ---

const ChatMessage = ({ msg }) => {
  const isAi = msg.sender === 'ai';
  const [isSaved, setIsSaved] = useState(false);
  
  let tripData = null;
  let activityData = null; 
  let multiStepData = null;
  let displayText = msg.text;

  if (isAi && typeof msg.text === 'string') {
    const cleanText = msg.text.replace(/```json/g, '').replace(/```/g, '').trim();
    
    if (cleanText.startsWith('{') || cleanText.startsWith('[')) {
        try {
          const parsed = JSON.parse(cleanText);
          
          if (parsed.legs) { 
            tripData = parsed;
            displayText = "Ich habe folgende Verbindung gefunden:"; 
          }
          else if (parsed.type === 'activity_list') {
            activityData = parsed;
            displayText = "Hier sind meine Empfehlungen:";
          }
          else if (parsed.type === 'multi_step_plan') {
             multiStepData = parsed;
             displayText = parsed.intro || "Hier ist dein Reiseplan:";
          }
          // --- NEU: Fehler abfangen ---
          else if (parsed.error) {
             displayText = `⚠️ ${parsed.error}`;
             // Optional: Style anpassen, damit es rot wirkt?
             // Wir lassen es erstmal als Text, aber jetzt ohne Klammern und Anführungszeichen.
          }
        } catch (e) { 
          console.error("JSON Parse Error", e);
        }
    }
  }

  const handleSaveTrip = async () => {
    const dataToSave = multiStepData || tripData;
    if (!dataToSave) return;
    
    try {
        const response = await fetch('http://localhost:8000/api/save_trip', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                saved_at: new Date().toISOString(),
                plan: dataToSave
            })
        });
        if (response.ok) setIsSaved(true);
    } catch (e) {
        console.error("Fehler beim Speichern der Reise:", e);
    }
  };

  const handleExportTrip = () => {
    const dataToExport = multiStepData || tripData;
    if (!dataToExport) return;
    
    // JSON in einen Text-String umwandeln und als Blob verpacken
    const dataStr = JSON.stringify(dataToExport, null, 2);
    const blob = new Blob([dataStr], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    
    // Einen unsichtbaren Link erstellen, anklicken und wieder entfernen
    const link = document.createElement('a');
    link.href = url;
    link.download = `KIRA_Reiseplan_${new Date().toISOString().split('T')[0]}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className={`flex w-full mb-4 ${isAi ? 'justify-start' : 'justify-end'}`}>
      <div className={`flex max-w-[95%] md:max-w-[85%] ${isAi ? 'flex-row' : 'flex-row-reverse'}`}>
        <div className={`shrink-0 h-8 w-8 rounded-full flex items-center justify-center mx-2 ${isAi ? 'bg-slate-200 text-slate-600' : 'bg-slate-300 text-slate-700'}`}>
          {isAi ? <Bot size={18} /> : <User size={18} />}
        </div>
        
        <div className="flex flex-col w-full">
          <div className={`p-3 rounded-2xl text-sm shadow-sm w-fit ${isAi ? 'bg-white border border-slate-100 text-slate-700 rounded-tl-none' : 'bg-slate-700 text-white rounded-tr-none'}`}>
            <p className="whitespace-pre-line">{displayText}</p>
          </div>

          {tripData && <div className="mt-2 ml-1"><TripCard data={tripData} /></div>}
          {activityData && <div className="mt-2 ml-1"><ActivityList data={activityData} /></div>}

          {multiStepData && (
            <div className="mt-4 space-y-0 ml-1 border-l-2 border-slate-200 pl-4">
                {multiStepData.steps.map((step, idx) => (
                    <div key={idx} className="relative">
                        {step.type === 'header' && (
                           <div className="mt-8 mb-4 first:mt-0">
                               <div className="absolute -left-[25px] mt-1.5 w-4 h-4 rounded-full bg-slate-800 border-2 border-white z-10"></div>
                               <h3 className="font-bold text-slate-800 text-lg ml-1">{step.title}</h3>
                           </div>
                        )}
                        
                        <div className={`absolute -left-[21px] top-6 w-3 h-3 rounded-full border-2 border-white ${step.type === 'error' ? 'bg-red-300' : 'bg-slate-300'}`}></div>
                        
                        {step.type === 'trip' && (
                            <div className="mb-4">
                                <div className="text-xs font-bold text-slate-400 mb-1 uppercase tracking-wider">{step.label || 'Fahrt'}</div>
                                <TripCard data={step.data} />
                            </div>
                        )}
                        
                        {step.type === 'activity' && (
                            <div className="mb-6">
                                <div className="text-xs font-bold text-indigo-400 mb-1 uppercase tracking-wider">Aktivität</div>
                                <SinglePlaceCard place={step.data} />
                            </div>
                        )}

                        {step.type === 'error' && (
                            <div className="mb-6">
                                <div className="text-xs font-bold text-red-400 mb-1 uppercase tracking-wider">Route nicht möglich</div>
                                <div className="bg-red-50 p-3 rounded-xl border border-red-100 flex gap-3 items-center text-red-600 mt-1">
                                    <AlertCircle size={18} className="shrink-0" />
                                    <div className="flex flex-col">
                                      <span className="text-xs font-medium">{step.message}</span>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                ))}
            </div>
          )}
            {/* 🔥 NEU: Container für BEIDE Speichern-Buttons */}
          {(tripData || multiStepData) && (
            <div className="flex flex-wrap gap-2 mt-4 ml-1">
                {/* 1. Button: In Datenbank speichern */}
                <button 
                    onClick={handleSaveTrip}
                    disabled={isSaved}
                    className={`px-4 py-2 w-fit rounded-xl text-sm font-bold flex items-center gap-2 transition-all ${
                        isSaved 
                        ? 'bg-emerald-100 text-emerald-700 border border-emerald-200' 
                        : 'bg-slate-800 text-white hover:bg-slate-700 shadow-md hover:shadow-lg'
                    }`}
                >
                    {isSaved ? <Check size={16} /> : <Save size={16} />}
                    {isSaved ? 'In Datenbank gespeichert' : 'In DB speichern'}
                </button>

                {/* 2. Button: Lokal als Datei herunterladen */}
                <button 
                    onClick={handleExportTrip}
                    className="px-4 py-2 w-fit rounded-xl text-sm font-bold flex items-center gap-2 transition-all bg-white text-slate-700 border border-slate-200 hover:bg-slate-50 shadow-sm hover:shadow-md"
                >
                    <Download size={16} />
                    Als JSON exportieren
                </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

const TripCard = ({ data }) => {
  if (!data || !data.legs) return null;
  return (
    <div className="w-full max-w-md bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden my-3">
      <div className="bg-slate-50 p-4 border-b border-slate-100 flex justify-between items-center">
        <div>
          <div className="flex items-center gap-2 text-slate-800 font-bold text-sm">
            {data.start} <ArrowRight size={14} /> {data.end}
          </div>
          <div className="text-xs text-slate-500 mt-1 flex items-center gap-1">
            <Clock size={12} /> {data.date} • {data.total_duration} Min.
          </div>
        </div>
        <div className="bg-slate-200 text-slate-600 px-2 py-1 rounded-lg text-xs font-bold">Trip</div>
      </div>
      <div className="p-4 relative">
        {data.legs.map((leg, index) => {
          const isLast = index === data.legs.length - 1;
          let Icon = Footprints;
          let colorClass = "bg-emerald-100 text-emerald-600 border-emerald-200";
          if (leg.mode === 'RAIL') { Icon = Train; colorClass = "bg-blue-100 text-blue-600 border-blue-200"; }
          if (leg.mode === 'BUS') { Icon = Bus; colorClass = "bg-amber-100 text-amber-600 border-amber-200"; }

          return (
            <div key={index} className="flex gap-3 relative pb-6 last:pb-0">
              {!isLast && <div className="absolute left-3.75 top-8 bottom-0 w-0.5 bg-slate-200" />}
              <div className="w-12 text-xs font-bold text-slate-500 pt-2 text-right">{leg.start_time}</div>
              <div className="relative z-10">
                <div className={`h-8 w-8 rounded-full border-2 flex items-center justify-center ${colorClass}`}>
                  <Icon size={14} />
                </div>
              </div>
              <div className="flex-1 pt-1">
                <div className="font-bold text-sm text-slate-700">
                  {leg.mode === 'WALK' ? 'Fußweg' : `${leg.mode} ${leg.line || ''}`}
                </div>
                <div className="text-xs text-slate-500">{leg.from} <span className="text-slate-300">→</span> {leg.to}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const SinglePlaceCard = ({ place }) => (
    <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm flex gap-4 my-2">
        <div className="h-10 w-10 bg-indigo-100 text-indigo-600 rounded-full flex items-center justify-center shrink-0">
            <Star size={18} />
        </div>
        <div>
            <h4 className="font-bold text-slate-800 text-sm">{place.name}</h4>
            <p className="text-xs text-slate-600 line-clamp-2">{place.description}</p>
        </div>
    </div>
);

const FilterPanel = ({ isOpen, onClose }) => {
    if(!isOpen) return null;
    return (
        <div className="absolute top-0 left-0 w-full h-full bg-white z-50 p-4">
            <h2 className="font-bold mb-4">Filter</h2>
            <button onClick={onClose} className="bg-slate-200 px-4 py-2 rounded">Schließen</button>
        </div>
    )
}

const ActivityList = ({ data }) => {
  return (
    <div className="w-full mt-3 space-y-3">
      <p className="text-sm text-slate-500 font-medium">Ich habe {data.items.length} Vorschläge für {data.location} gefunden:</p>
      <div className="grid grid-cols-1 gap-3">
        {data.items.map((item, idx) => (
          <PlaceCard key={idx} place={item} />
        ))}
      </div>
    </div>
  );
};

const PlaceCard = ({ place }) => (
    <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-sm hover:shadow-md transition-shadow flex gap-4">
        <div className="h-12 w-12 bg-indigo-100 text-indigo-600 rounded-lg flex items-center justify-center shrink-0">
            <MapPin size={20} />
        </div>
        <div>
            <h4 className="font-bold text-slate-800 text-sm">{place.name}</h4>
            <div className="text-xs text-slate-500 font-bold mb-1 uppercase tracking-wider">{place.category}</div>
            <p className="text-xs text-slate-600 leading-relaxed line-clamp-2">{place.description}</p>
        </div>
    </div>
);

// Hilfsfunktion: Decodiert Google Polyline Format
function decodePolyline(encoded) {
  if (!encoded) return [];
  var poly = [];
  var index = 0, len = encoded.length;
  var lat = 0, lng = 0;

  while (index < len) {
    var b, shift = 0, result = 0;
    do {
      b = encoded.charCodeAt(index++) - 63;
      result |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    var dlat = ((result & 1) != 0 ? ~(result >> 1) : (result >> 1));
    lat += dlat;

    shift = 0;
    result = 0;
    do {
      b = encoded.charCodeAt(index++) - 63;
      result |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    var dlng = ((result & 1) != 0 ? ~(result >> 1) : (result >> 1));
    lng += dlng;

    poly.push([lat / 1e5, lng / 1e5]);
  }
  return poly;
}

// --- MAIN APP ---

export default function App() {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState([INITIAL_MESSAGE]);
  const [isLoading, setIsLoading] = useState(false);
  const [socket, setSocket] = useState(null);
  const [showMobileChat, setShowMobileChat] = useState(true);
  const [showFilters, setShowFilters] = useState(false);

  const [activeDay, setActiveDay] = useState(1);
  const [isMapReady, setIsMapReady] = useState(false);
  
  const mapContainerRef = useRef(null);
  const messagesEndRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const routeLayerRef = useRef(null);
  const fileInputRef = useRef(null);

  // 🔥 NEU: Import-Logik
  const handleImportClick = () => {
    fileInputRef.current?.click();
  };
  const handleFileChange = (event) => {
    const file = event.target.files[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const content = e.target.result;
            // Kurzer Test, ob es wirklich JSON ist
            JSON.parse(content); 
            
            // Wir tun so, als hätte die KI diese Nachricht gerade geschrieben.
            // Dadurch greifen all deine bestehenden Karten- und Render-Funktionen!
            setMessages(prev => [...prev, { 
                id: Date.now(), 
                sender: 'ai', 
                text: content 
            }]);
            
            // Setzt den ActiveDay wieder auf 1, falls es ein Mehrtagestrip ist
            setActiveDay(1);
        } catch (err) {
            console.error("Invalid JSON file", err);
            alert("Die hochgeladene Datei ist kein gültiger KIRA-Reiseplan.");
        }
    };
    reader.readAsText(file);
    event.target.value = ''; // Feld zurücksetzen, damit man die gleiche Datei nochmal laden kann
  };

  // 1. WebSocket Verbindung herstellen
  useEffect(() => {
    const wsUrl = import.meta.env.VITE_WS_URL || "ws://localhost:8000/chat";
    const ws = new WebSocket(wsUrl); 
    ws.onopen = () => console.log('✅ Connected to KIRA Backend');
    ws.onmessage = (event) => {
      const aiText = event.data;
      setIsLoading(false);
      setMessages(prev => [...prev, { id: Date.now(), sender: 'ai', text: aiText }]);
    };
    ws.onerror = (e) => {
        console.error('❌ WebSocket Error:', e);
        setIsLoading(false);
    }
    setSocket(ws);
    return () => ws.close();
  }, []);

 // 2. Leaflet Karte initialisieren (ROBUST)
  useEffect(() => {
    // A) Ressourcen laden
    if (!document.getElementById('leaflet-css')) {
        const link = document.createElement('link');
        link.id = 'leaflet-css';
        link.rel = 'stylesheet';
        link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
        document.head.appendChild(link);
    }
    if (!document.getElementById('leaflet-js')) {
        const script = document.createElement('script');
        script.id = 'leaflet-js';
        script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
        document.head.appendChild(script);
    }
    
    // B) Karte starten
    const checkL = setInterval(() => {
        // Warten bis Leaflet geladen UND der Container im HTML verfügbar ist
        if (window.L && mapContainerRef.current) {
            clearInterval(checkL);
            
            // 🔥 FIX: Alte Karte sauber entfernen, bevor wir eine neue bauen!
            // Das löst das Problem mit der weißen/leeren Karte.
            if (mapInstanceRef.current) {
                mapInstanceRef.current.remove();
                mapInstanceRef.current = null;
            }

            routeLayerRef.current = null;

            mapContainerRef.current.innerHTML = "";
            if (mapContainerRef.current._leaflet_id) {
                mapContainerRef.current._leaflet_id = null;
            }

            try {
                const map = window.L.map(mapContainerRef.current).setView([47.5162, 10.1936], 11);
                window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
                mapInstanceRef.current = map;

                setIsMapReady(true);
                setTimeout(() => { map.invalidateSize(); }, 200);
            } catch (e) {
                console.error("Fehler beim Karten-Start:", e);
            }
        }
    }, 100);

    // Cleanup beim Verlassen
    return () => clearInterval(checkL);
  }, []);

  // 3. Effect: Lauscht auf Nachrichten und zeichnet Routen
// 3. Effect: Lauscht auf Nachrichten und zeichnet Routen & Icons
  useEffect(() => {
    const lastMsg = messages[messages.length - 1];
    // Sicherheits-Check: Nur laufen, wenn Karte bereit ist
    if (!lastMsg || lastMsg.sender !== 'ai' || !mapInstanceRef.current || !isMapReady) return;

    try {
        const cleanText = lastMsg.text.replace(/```json/g, '').replace(/```/g, '').trim();
        if (cleanText.startsWith('{')) {
            const data = JSON.parse(cleanText);
            
            // Layer-Management
            if (!routeLayerRef.current) {
                routeLayerRef.current = window.L.layerGroup().addTo(mapInstanceRef.current);
            }
            routeLayerRef.current.clearLayers();

            const routesToDraw = [];
            const markersMap = new Map(); 

            // --- HELPER: ICONS ---
            const getIconHtml = (category) => {
                const cat = (category || '').toLowerCase();
                let iconPath = '';
                let bgColor = 'bg-slate-800'; 

                if (cat.includes('museum') || cat.includes('kultur')) {
                    iconPath = '<path d="M3 22v-8c0-1.1.9-2 2-2h14c1.1 0 2 .9 2 2v8M3 6l9-4 9 4M12 6v7M8 6v7M16 6v7"/>';
                    bgColor = 'bg-indigo-600';
                } 
                else if (cat.includes('restaurant') || cat.includes('essen') || cat.includes('gasthof')) {
                    iconPath = '<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2M15 22v-8H7v8M19 8V2M22 8V2M19 14v8"/>';
                    bgColor = 'bg-orange-500';
                }
                else if (cat.includes('wandern') || cat.includes('natur') || cat.includes('berg')) {
                    iconPath = '<path d="m8 3 4 8 5-5 5 15H2L8 3z"/>';
                    bgColor = 'bg-emerald-600';
                }
                else if (cat.includes('hotel') || cat.includes('unterkunft')) {
                    iconPath = '<path d="M2 4v16M2 8h18a2 2 0 0 1 2 2v10M2 17h20M6 8v9"/>';
                    bgColor = 'bg-blue-600';
                }
                else {
                    iconPath = '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>';
                }

                return `
                    <div class="${bgColor} w-8 h-8 rounded-full flex items-center justify-center shadow-md border-2 border-white text-white">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            ${iconPath}
                        </svg>
                    </div>
                `;
            };

            const addMarker = (lat, lon, type, name, category) => { 
                const nLat = parseFloat(lat);
                const nLon = parseFloat(lon);
                if (isNaN(nLat) || isNaN(nLon)) return;

                const key = `${nLat.toFixed(5)},${nLon.toFixed(5)}`;
                const existing = markersMap.get(key);
                
                if (type === 'activity') {
                    markersMap.set(key, { pos: [nLat, nLon], type, name, category });
                    return;
                }
                if (existing && existing.type === 'activity') return; 
                markersMap.set(key, { pos: [nLat, nLon], type, name, category: null });
            };

            const processLegs = (legs, stepLabel) => {
                const label = (stepLabel || '').toLowerCase();
                
                legs.forEach((leg, index) => {
                    let legColor = '#f97316'; 
                    const isLast = index === legs.length - 1;
                    const isFirst = index === 0;

                    if (label.includes('anreise') || label.includes('hinfahrt')) {
                        legColor = '#3b82f6'; 
                        if (isLast && leg.mode === 'WALK') legColor = '#f97316';
                    } 
                    else if (label.includes('rückreise') || label.includes('rückfahrt')) {
                        legColor = '#ef4444'; 
                        if (isFirst && leg.mode === 'WALK') legColor = '#f97316';
                    }
                    if (label.includes('route') || leg.line === 'Wanderweg') {
                        legColor = '#16a34a'; 
                    }

                    // 🔥 FIX 1: Geometrie flexibel finden (egal ob 'geometry' oder 'legGeometry.points')
                    let rawGeo = leg.geometry || leg.legGeometry;
                    // Falls OTP ein Objekt schickt: { points: "..." }
                    if (rawGeo && typeof rawGeo === 'object' && rawGeo.points) {
                        rawGeo = rawGeo.points;
                    }

                    if (rawGeo) {
                        let points = [];
                        if (typeof rawGeo === 'string') {
                            points = decodePolyline(rawGeo);
                        } else if (Array.isArray(rawGeo)) {
                            // 🔥 FIX 2: Koordinaten-Check (Afrika-Fix) 🔥
                            // GeoJSON ist [Lon, Lat], Leaflet will [Lat, Lon].
                            // Wenn wir Koordinaten nahe Somalia (Lat < 40, Lon > 40) sehen, tauschen wir sie.
                            points = rawGeo.map(pt => {
                                if (pt[0] < 40 && pt[1] > 40) {
                                    return [pt[1], pt[0]]; // Tauschen!
                                }
                                return pt;
                            });
                        }
                        
                        if (points.length > 0) {
                            routesToDraw.push({ points: points, color: legColor });
                        }
                    }
                    
                    if (leg.from_coords) addMarker(leg.from_coords[0], leg.from_coords[1], 'transfer', leg.from);
                    if (leg.stops) leg.stops.forEach(s => addMarker(s.lat, s.lon, 'stop', s.name));
                    if (leg.to_coords) addMarker(leg.to_coords[0], leg.to_coords[1], 'transfer', leg.to);
                });
            };

            // --- DATEN VERARBEITEN ---
            if (data.legs) {
                processLegs(data.legs, 'anreise'); 
            } 
            else if (data.type === 'activity_list') {
                 data.items.forEach(item => {
                     if (item.lat && item.lon) addMarker(item.lat, item.lon, 'activity', item.name, item.category);
                 });
            }
            else if (data.type === 'multi_step_plan') {
                // 🔥 FIX: Prüfen, ob dieser Plan überhaupt in Tage unterteilt ist
                const hasHeaders = data.steps.some(s => s.type === 'header');
                let currentDayCount = 0; 
                
                data.steps.forEach((step, idx) => {
                    if (step.type === 'header') currentDayCount++;
                    
                    // 🔥 FIX: Nur filtern, wenn es wirklich Tages-Überschriften gibt!
                    if (hasHeaders && currentDayCount !== activeDay) return; 

                    if (step.type === 'trip' && step.data.legs) {
                        let smartLabel = step.label || 'weiterfahrt';
                        if (idx === 0) smartLabel = 'anreise';
                        if (idx === data.steps.length - 1) smartLabel = 'rückreise';
                        processLegs(step.data.legs, smartLabel);
                    }
                    if (step.type === 'activity' && step.data.lat && step.data.lon) {
                        addMarker(step.data.lat, step.data.lon, 'activity', step.data.name, step.data.category);
                    }
                });
            }

            // --- ZEICHNEN ---
            routesToDraw.forEach(route => {
                window.L.polyline(route.points, { color: route.color, weight: 5, opacity: 0.8 }).addTo(routeLayerRef.current);
            });

            markersMap.forEach((pt) => {
                if (pt.type === 'activity') {
                    const icon = window.L.divIcon({
                        className: 'custom-icon', 
                        html: getIconHtml(pt.category),
                        iconSize: [32, 32],
                        iconAnchor: [16, 32], 
                        popupAnchor: [0, -32]
                    });
                    window.L.marker(pt.pos, { icon: icon, zIndexOffset: 1000 }).bindPopup(pt.name).addTo(routeLayerRef.current);
                } 
                else {
                    window.L.circleMarker(pt.pos, {
                        radius: 4,
                        fillColor: '#ffffff',
                        color: '#3b82f6',
                        weight: 2,
                        opacity: 1,
                        fillOpacity: 1
                    }).bindPopup(pt.name).addTo(routeLayerRef.current);
                }
            });

            // Zoom anpassen
            const allLatLngs = [];
            routesToDraw.forEach(r => allLatLngs.push(...r.points));
            markersMap.forEach(pt => allLatLngs.push(pt.pos));
            
            if (allLatLngs.length > 0) {
                const bounds = window.L.latLngBounds(allLatLngs);
                mapInstanceRef.current.fitBounds(bounds, { padding: [50, 50] });
            }
        }
    } catch (e) {
        console.error("Map Draw Error:", e);
    }
  },[messages, activeDay, isMapReady]);

  // 4. Scroll to Bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);


  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;

    setActiveDay(1);

    const userText = input;
    setInput('');
    setMessages(prev => [...prev, { id: Date.now(), sender: 'user', text: userText }]);
    setIsLoading(true);

    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(userText);
    } else {
      setMessages(prev => [...prev, { 
        id: Date.now(), 
        sender: 'ai', 
        text: "⚠️ Keine Verbindung zum Server. Läuft backend_api.py?" 
      }]);
      setIsLoading(false);
    }
  };

  const testTripCard = () => {
    // Einfache Testfunktion
  };

  const handleDemoClick = () => {
    const demoJson = JSON.stringify({
      date: "2026-01-30",
      start: "Fischen",
      end: "Sonthofen",
      total_duration: "23",
      legs: [
        { mode: "WALK", from: "Dein Standort", to: "Fischen Bhf", start_time: "08:00", end_time: "08:10", duration: 10, geometry: "_p~iF~ps|U_ulLnnqC" },
        { mode: "RAIL", line: "RE 17", from: "Fischen Bhf", to: "Sonthofen Bf", start_time: "08:12", end_time: "08:20", duration: 8, geometry: "_p~iF~ps|U_ulLnnqC" }
      ]
    });
    setMessages(prev => [...prev, { id: Date.now(), sender: 'ai', text: demoJson }]);
  };

  return (
    <div className="h-screen w-full bg-slate-50 flex flex-col md:flex-row overflow-hidden font-sans rounded-3xl">
      
      {/* Linke Seite: Chat */}
      <div className={`${showMobileChat ? 'flex' : 'hidden'} md:flex flex-col w-full md:w-112.5 bg-white border-r border-slate-200 z-20 h-full`}>
        <div className="p-4 border-b border-slate-100 flex items-center justify-between">
          <h1 className="font-bold text-slate-800 text-lg">KIRA</h1>
          <button onClick={() => setShowMobileChat(false)} className="md:hidden"><X size={24} /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 bg-slate-50 space-y-4">
          {messages.map((msg) => <ChatMessage key={msg.id} msg={msg} />)}
          {isLoading && (
            <div className="text-slate-500 text-sm ml-4">
              KIRA denkt nach... <Loader2 className="inline animate-spin"/>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <div className="p-4 bg-white border-t border-slate-100">
          <form onSubmit={handleSend} className="flex items-center gap-2 mb-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Wohin möchtest du reisen?"
              className="flex-1 bg-slate-100 rounded-2xl py-3 pl-5 pr-4 focus:outline-none"
            />
            <button type="submit" className="p-3 bg-slate-700 text-white rounded-xl">
              <Send size={18} />
            </button>
          </form>
          
          <div className="flex gap-2">
            {/* Der Demo-Button wurde hier komplett entfernt */}
            
            {/* Import Button & Verstecktes Input-Feld */}
            <input 
                type="file" 
                accept=".json" 
                ref={fileInputRef} 
                onChange={handleFileChange} 
                style={{ display: 'none' }} 
            />
            <button onClick={handleImportClick} className="text-xs bg-slate-200 text-slate-700 px-3 py-1 rounded font-bold flex items-center gap-1 hover:bg-slate-300">
              <Upload size={14} /> Trip importieren
            </button>
          </div>
        </div>
      </div>

      {/* Rechte Seite: Karte */}
      <div className="flex-1 relative bg-slate-50 h-full flex flex-col p-6">
        
        {/* 1. DIE KARTE (Liegt unten, z-0) */}
        <div className="rounded-3xl overflow-hidden shadow-2xl border border-slate-200 bg-white h-full relative z-0">
          <div ref={mapContainerRef} className="w-full h-full" />
        </div>

        {/* 2. MENU BUTTON (Liegt drüber) */}
        {!showMobileChat && (
          <button 
            onClick={() => setShowMobileChat(true)} 
            className="absolute top-4 left-4 z-[1000] bg-white p-2 rounded-xl shadow-md border border-slate-100 hover:bg-slate-50 transition-colors"
          >
            <Menu className="text-slate-600"/>
          </button>
        )}
        
        {/* 3. TAG-AUSWAHL BUTTONS (Liegen ganz oben, z-1000) */}
        {(() => {
            const lastMsg = messages[messages.length - 1];
            if (lastMsg && lastMsg.sender === 'ai') {
                try {
                    const cleanText = lastMsg.text.replace(/```json/g, '').replace(/```/g, '').trim();
                    if (cleanText.startsWith('{')) {
                        const data = JSON.parse(cleanText);
                        
                        if (data.type === 'multi_step_plan') {
                            const totalDays = data.steps.filter(s => s.type === 'header').length;
                            
                            if (totalDays > 1) {
                                return (
                                    <div className="absolute top-8 left-1/2 transform -translate-x-1/2 z-[1000] bg-white/95 backdrop-blur-md p-1.5 rounded-2xl shadow-xl border border-slate-200/50 flex gap-1">
                                        {Array.from({ length: totalDays }, (_, i) => i + 1).map(day => (
                                            <button
                                                key={day}
                                                onClick={() => setActiveDay(day)}
                                                className={`px-4 py-2 rounded-xl text-sm font-bold transition-all shadow-sm ${
                                                    activeDay === day 
                                                    ? 'bg-slate-800 text-white scale-105' 
                                                    : 'bg-transparent text-slate-500 hover:bg-slate-100 hover:text-slate-700'
                                                }`}
                                            >
                                                Tag {day}
                                            </button>
                                        ))}
                                    </div>
                                );
                            }
                        }
                    }
                } catch (e) { }
            }
            return null;
        })()}
        
      </div>

    </div>
  );

  
}