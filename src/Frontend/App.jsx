import React, { useState, useEffect, useRef } from 'react';
import { Send, Map as MapIcon, Navigation, Star, MapPin, Menu, X, Globe, User, Bot, Loader2, AlertCircle, Filter, Sliders, Train, Bus, Footprints, Clock, ArrowRight, Flag } from 'lucide-react';

// --- Konfiguration & Mock-Daten ---

const INITIAL_MESSAGE = {
  id: 1,
  sender: 'ai',
  text: "Guten Tag! Ich bin KIRA. Wohin möchtest du reisen?",
};

// --- Komponenten ---

const ChatMessage = ({ msg }) => {
  const isAi = msg.sender === 'ai';
  
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
  
  const mapContainerRef = useRef(null);
  const messagesEndRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const routeLayerRef = useRef(null);

  // 1. WebSocket Verbindung herstellen
  useEffect(() => {
    const ws = new WebSocket('ws://localhost:8000/chat'); 
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

  // 2. Leaflet Karte initialisieren (DAS HAT GEFEHLT!)
  useEffect(() => {
    if (!mapContainerRef.current) return;
    
    // Checken ob Leaflet CSS schon da ist
    if (!document.getElementById('leaflet-css')) {
        const link = document.createElement('link');
        link.id = 'leaflet-css';
        link.rel = 'stylesheet';
        link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
        document.head.appendChild(link);
    }

    // Checken ob Leaflet JS schon da ist
    if (!document.getElementById('leaflet-js')) {
        const script = document.createElement('script');
        script.id = 'leaflet-js';
        script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
        document.head.appendChild(script);
    }
    
    // Warten bis L verfügbar ist
    const checkL = setInterval(() => {
        if (window.L) {
            clearInterval(checkL);
            
            // Map erstellen (falls noch nicht da)
            if (!mapInstanceRef.current) {
                const map = window.L.map(mapContainerRef.current).setView([47.5162, 10.1936], 11);
                window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
                mapInstanceRef.current = map;
            }
        }
    }, 100);

    return () => {
        // Cleanup beim Unmount (optional)
        // mapInstanceRef.current?.remove(); 
    };
  }, []);

  // 3. Effect: Lauscht auf Nachrichten und zeichnet Routen
 useEffect(() => {
    const lastMsg = messages[messages.length - 1];
    if (!lastMsg || lastMsg.sender !== 'ai' || !mapInstanceRef.current) return;

    try {
        const cleanText = lastMsg.text.replace(/```json/g, '').replace(/```/g, '').trim();
        if (cleanText.startsWith('{')) {
            const data = JSON.parse(cleanText);
            
            if (!routeLayerRef.current) {
                routeLayerRef.current = window.L.layerGroup().addTo(mapInstanceRef.current);
            }
            routeLayerRef.current.clearLayers();

            const routesToDraw = [];
            const markersMap = new Map(); 

            const addMarker = (lat, lon, type, name) => {
                const key = `${lat.toFixed(5)},${lon.toFixed(5)}`;
                const existing = markersMap.get(key);
                if (type === 'activity') {
                    markersMap.set(key, { pos: [lat, lon], type, name });
                    return;
                }
                if (existing && existing.type === 'activity') return; 
                if (type === 'transfer') {
                     markersMap.set(key, { pos: [lat, lon], type, name });
                     return;
                }
                if (!existing) {
                    markersMap.set(key, { pos: [lat, lon], type, name });
                }
            };

            // --- NEU: INTELLIGENTE FARB-LOGIK ---
            const processLegs = (legs, stepLabel) => {
                const label = (stepLabel || '').toLowerCase();
                
                legs.forEach((leg, index) => {
                    let legColor = '#f97316'; // Standard: Orange (für Activities/Zwischenwege)
                    const isLast = index === legs.length - 1;
                    const isFirst = index === 0;

                    // Logik für Anreise (Blau -> Orange am Ende)
                    if (label.includes('anreise') || label.includes('hinfahrt')) {
                        legColor = '#3b82f6'; // Blau
                        // Ausnahme: Das letzte Stück zu Fuß ist schon der Weg zum Museum
                        if (isLast && leg.mode === 'WALK') {
                            legColor = '#f97316'; // Orange
                        }
                    } 
                    // Logik für Rückreise (Orange am Anfang -> Rot)
                    else if (label.includes('rückreise') || label.includes('rückfahrt')) {
                        legColor = '#ef4444'; // Rot
                        // Ausnahme: Das erste Stück zu Fuß ist noch der Weg vom Museum weg
                        if (isFirst && leg.mode === 'WALK') {
                            legColor = '#f97316'; // Orange
                        }
                    }

                    if (leg.geometry) {
                        routesToDraw.push({ points: decodePolyline(leg.geometry), color: legColor });
                    }
                    
                    // Marker sammeln
                    if (leg.from_coords) addMarker(leg.from_coords[0], leg.from_coords[1], 'transfer', leg.from);
                    if (leg.stops) leg.stops.forEach(s => addMarker(s.lat, s.lon, 'stop', s.name));
                    if (leg.to_coords) addMarker(leg.to_coords[0], leg.to_coords[1], 'transfer', leg.to);
                });
            };

            // --- DATEN VERARBEITEN ---
            if (data.legs) {
                processLegs(data.legs, 'anreise'); // Single Trip = Anreise Logik
            } 
            else if (data.type === 'activity_list') {
                 data.items.forEach(item => {
                     if (item.lat && item.lon) addMarker(item.lat, item.lon, 'activity', item.name);
                 });
            }
            else if (data.type === 'multi_step_plan') {
                data.steps.forEach((step, idx) => {
                    if (step.type === 'trip' && step.data.legs) {
                        // Wir übergeben das Label ("Anreise", "Rückreise") an die Logik
                        let smartLabel = step.label || 'weiterfahrt';
                        
                        // Fallback falls Label fehlt
                        if (idx === 0) smartLabel = 'anreise';
                        if (idx === data.steps.length - 1) smartLabel = 'rückreise';

                        processLegs(step.data.legs, smartLabel);
                    }
                    if (step.type === 'activity' && step.data.lat && step.data.lon) {
                        addMarker(step.data.lat, step.data.lon, 'activity', step.data.name);
                    }
                });
            }

            // --- ZEICHNEN ---
            const allLatLngs = [];
            routesToDraw.forEach(route => {
                window.L.polyline(route.points, { color: route.color, weight: 5, opacity: 0.8 }).addTo(routeLayerRef.current);
                allLatLngs.push(...route.points);
            });

            markersMap.forEach((pt) => {
                let color = '#3b82f6'; 
                let fillColor = '#3b82f6';
                let radius = 6;
                let zIndexOffset = 0;

                if (pt.type === 'activity') {
                    color = '#ffffff';
                    fillColor = '#f97316'; 
                    radius = 9;       
                    zIndexOffset = 1000;
                } else if (pt.type === 'stop') {
                    color = '#3b82f6';
                    fillColor = '#ffffff'; 
                    radius = 4;
                } 
                
                window.L.circleMarker(pt.pos, {
                    radius: radius,
                    fillColor: fillColor,
                    color: color,
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 1,
                    zIndexOffset: zIndexOffset
                }).bindPopup(pt.name).addTo(routeLayerRef.current);
                
                allLatLngs.push(pt.pos);
            });

            if (allLatLngs.length > 0) {
                const bounds = window.L.latLngBounds(allLatLngs);
                mapInstanceRef.current.fitBounds(bounds, { padding: [50, 50] });
            }
        }
    } catch (e) {
        console.error("Map Draw Error:", e);
    }
  }, [messages]);

  // 4. Scroll to Bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);


  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;

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
          {isLoading && <div className="text-slate-500 text-sm ml-4">KIRA denkt nach... <Loader2 className="inline animate-spin"/></div>}
          <div ref={messagesEndRef} />
        </div>

        <div className="p-4 bg-white border-t border-slate-100">
          <form onSubmit={handleSend} className="flex items-center gap-2 mb-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Reise von Kempten nach..."
              className="flex-1 bg-slate-100 rounded-2xl py-3 pl-5 pr-4 focus:outline-none"
            />
            <button type="submit" className="p-3 bg-slate-700 text-white rounded-xl"><Send size={18} /></button>
          </form>
          <div className="flex gap-2">
            <button onClick={handleDemoClick} className="text-xs bg-blue-100 text-blue-700 px-3 py-1 rounded font-bold">
              🎫 Demo: Fischen-Sonthofen
            </button>
          </div>
        </div>
      </div>

      {/* Rechte Seite: Karte */}
      <div className="flex-1 relative bg-slate-50 h-full flex flex-col p-6">
        {!showMobileChat && <button onClick={() => setShowMobileChat(true)} className="absolute top-4 left-4 z-30 bg-white p-2 rounded shadow"><Menu/></button>}
        
        <div className="rounded-3xl overflow-hidden shadow-2xl border border-slate-200 bg-white h-full">
          <div ref={mapContainerRef} className="w-full h-full" />
        </div>
      </div>

      <FilterPanel isOpen={showFilters} onClose={() => setShowFilters(false)}/>
    </div>
  );
}