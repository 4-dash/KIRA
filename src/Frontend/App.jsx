import React, { useState, useEffect, useRef } from 'react';
import { Send, Map as MapIcon, Navigation, Star, MapPin, Menu, X, Globe, User, Bot, Loader2, AlertCircle, Filter, Sliders, Train, Bus, Footprints, Clock, ArrowRight, Flag } from 'lucide-react';

// --- Konfiguration & Mock-Daten ---

const INITIAL_MESSAGE = {
  id: 1,
  sender: 'ai',
  text: "Guten Tag! Ich bin KIRA. Wohin möchtest du reisen?",
};

const FILTER_OPTIONS = {
  types: [
    { id: 'stay', label: 'Unterkunft', icon: MapPin },
    { id: 'dining', label: 'Gastronomie', icon: MapPin },
    { id: 'culture', label: 'Kultur', icon: MapPin },
    { id: 'nature', label: 'Natur', icon: MapPin },
  ],
  priceRanges: [
    { id: '$', label: 'Budget', icon: '$' },
    { id: '$$', label: 'Mittel', icon: '$$' },
    { id: '$$$', label: 'Premium', icon: '$$$' },
  ],
  ratings: [
    { id: 4.5, label: '4,5+ Sterne', value: 4.5 },
    { id: 4.0, label: '4,0+ Sterne', value: 4.0 },
  ],
};

// --- Komponenten ---

const ChatMessage = ({ msg }) => {
  const isAi = msg.sender === 'ai';
  
  // States to hold the parsed data
  let tripData = null;
  let activityData = null; 
  let multiStepData = null;
  let displayText = msg.text;

  // Logic to parse the AI response looking for JSON
  if (isAi && typeof msg.text === 'string') {
    // Clean up potential Markdown formatting (```json ... ```)
    const cleanText = msg.text.replace(/```json/g, '').replace(/```/g, '').trim();
    
    if (cleanText.startsWith('{') || cleanText.startsWith('[')) {
        try {
          const parsed = JSON.parse(cleanText);
          
          // Case 1: Single Trip Plan
          if (parsed.legs) { 
            tripData = parsed;
            displayText = "Ich habe folgende Verbindung gefunden:"; 
          }
          // Case 2: List of Activities
          else if (parsed.type === 'activity_list') {
            activityData = parsed;
            displayText = "Hier sind meine Empfehlungen:";
          }
          // Case 3: Complex Multi-Step Itinerary
          else if (parsed.type === 'multi_step_plan') {
             multiStepData = parsed;
             displayText = parsed.intro || "Hier ist dein Reiseplan:";
          }
        } catch (e) { 
          // If parsing fails, we just show the raw text
          console.error("JSON Parse Error", e);
        }
    }
  }

  return (
    <div className={`flex w-full mb-4 ${isAi ? 'justify-start' : 'justify-end'}`}>
      <div className={`flex max-w-[95%] md:max-w-[85%] ${isAi ? 'flex-row' : 'flex-row-reverse'}`}>
        
        {/* Avatar Bubble */}
        <div className={`shrink-0 h-8 w-8 rounded-full flex items-center justify-center mx-2 ${isAi ? 'bg-slate-200 text-slate-600' : 'bg-slate-300 text-slate-700'}`}>
          {isAi ? <Bot size={18} /> : <User size={18} />}
        </div>
        
        <div className="flex flex-col w-full">
          {/* Main Text Bubble */}
          <div className={`p-3 rounded-2xl text-sm shadow-sm w-fit ${isAi ? 'bg-white border border-slate-100 text-slate-700 rounded-tl-none' : 'bg-slate-700 text-white rounded-tr-none'}`}>
            <p className="whitespace-pre-line">{displayText}</p>
          </div>

          {/* RENDER: Single Trip Card */}
          {tripData && (
            <div className="mt-2 ml-1">
              <TripCard data={tripData} />
            </div>
          )}

          {/* RENDER: Activity List */}
          {activityData && (
            <div className="mt-2 ml-1">
              <ActivityList data={activityData} />
            </div>
          )}

          {/* RENDER: Multi-Step Timeline (The new feature) */}
          {multiStepData && (
            <div className="mt-4 space-y-0 ml-1 border-l-2 border-slate-200 pl-4">
                {multiStepData.steps.map((step, idx) => (
                    <div key={idx} className="relative">
                      {/* --- NEU: TAG HEADER --- */}
                        {step.type === 'header' && (
                           <div className="mt-8 mb-4 first:mt-0">
                               <div className="absolute -left-[25px] mt-1.5 w-4 h-4 rounded-full bg-slate-800 border-2 border-white z-10"></div>
                               <h3 className="font-bold text-slate-800 text-lg ml-1">{step.title}</h3>
                           </div>
                        )}
                        
                        {/* Timeline Dot (Color changes if it's an error) */}
                        <div className={`absolute -left-[21px] top-6 w-3 h-3 rounded-full border-2 border-white ${step.type === 'error' ? 'bg-red-300' : 'bg-slate-300'}`}></div>
                        
                        {/* 1. Successful Trip Segment */}
                        {step.type === 'trip' && (
                            <div className="mb-4">
                                <div className="text-xs font-bold text-slate-400 mb-1 uppercase tracking-wider">Fahrt</div>
                                <TripCard data={step.data} />
                            </div>
                        )}
                        
                        {/* 2. Activity Segment */}
                        {step.type === 'activity' && (
                            <div className="mb-6">
                                <div className="text-xs font-bold text-indigo-400 mb-1 uppercase tracking-wider">Aktivität</div>
                                <SinglePlaceCard place={step.data} />
                            </div>
                        )}

                        {/* 3. Error Segment (This fixes the missing trips!) */}
                        {step.type === 'error' && (
                            <div className="mb-6">
                                <div className="text-xs font-bold text-red-400 mb-1 uppercase tracking-wider">Route nicht möglich</div>
                                <div className="bg-red-50 p-3 rounded-xl border border-red-100 flex gap-3 items-center text-red-600 mt-1">
                                    <AlertCircle size={18} className="shrink-0" />
                                    <div className="flex flex-col">
                                      <span className="text-xs font-medium">{step.message}</span>
                                      <span className="text-[10px] opacity-75">Prüfe die Entfernung oder Fahrplandaten.</span>
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


const FilterPanel = ({ isOpen, onClose, filters, setFilters }) => {
    // Vereinfachte Filter-Komponente
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
        {/* Platzhalter Icon/Bild */}
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
// --- MAIN APP ---

export default function App() {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState([INITIAL_MESSAGE]);
  const [isLoading, setIsLoading] = useState(false);
  const [socket, setSocket] = useState(null);
  const [showMobileChat, setShowMobileChat] = useState(true);
  const [showFilters, setShowFilters] = useState(false);
  const [mapHeight, setMapHeight] = useState(50);
  const [isResizing, setIsResizing] = useState(false);
  const [filters, setFilters] = useState({ types: [], priceRanges: [], ratings: [] });
  
  const [mapState, setMapState] = useState({ lat: 47.5162, lon: 10.1936, name: "Allgäu, Deutschland" }); 
  const [recommendations, setRecommendations] = useState([]);

  const mapContainerRef = useRef(null);
  const containerRef = useRef(null);
  const messagesEndRef = useRef(null);

  // 1. WebSocket Verbindung herstellen
  useEffect(() => {
    // Erkennt automatisch ob localhost oder eine IP genutzt wird
    const host = window.location.hostname || "localhost";
    const ws = new WebSocket(`ws://${host}:8000/chat`);

    ws.onopen = () => {
      console.log('✅ Connected to KIRA Backend');
    };

    ws.onmessage = (event) => {
      setIsLoading(false);
      const rawData = event.data;

      try {
        const parsed = JSON.parse(rawData);

        // Fall A: Es ist eine normale Text-Nachricht von der KI
        if (parsed.type === "assistant_message") {
          setMessages(prev => [
            ...prev, 
            { id: Date.now(), sender: 'ai', text: parsed.content }
          ]);
        } 
        // Fall B: Es ist ein Tool-Ergebnis (Reiseplan, Karte, JSON-Daten)
        else {
          // Wir speichern das rohe JSON als Text, damit deine 
          // ChatMessage-Komponente (mit tripData/activityData) es rendern kann
          setMessages(prev => [
            ...prev, 
            { id: Date.now(), sender: 'ai', text: rawData }
          ]);
        }
      } catch (e) {
        // Fallback: Falls die Nachricht kein JSON ist, einfach als Text anzeigen
        setMessages(prev => [
          ...prev, 
          { id: Date.now(), sender: 'ai', text: rawData }
        ]);
      }
    };

    ws.onerror = (e) => {
      console.error('❌ WebSocket Error:', e);
      setIsLoading(false);
    };

    ws.onclose = () => {
      console.log('ℹ️ WebSocket connection closed');
    };

    setSocket(ws);

    // Cleanup beim Schließen der Komponente
    return () => ws.close();
  }, []);

  // 2. Leaflet Karte initialisieren
  useEffect(() => {
    if (!mapContainerRef.current) return;
    const leafletLink = document.createElement('link');
    leafletLink.rel = 'stylesheet';
    leafletLink.href = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css';
    document.head.appendChild(leafletLink);

    const leafletScript = document.createElement('script');
    leafletScript.src = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js';
    leafletScript.onload = () => {
      const map = window.L.map(mapContainerRef.current).setView([mapState.lat, mapState.lon], 11);
      window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
      return () => map.remove();
    };
    document.body.appendChild(leafletScript);
  }, []);

  // 3. Scroll to Bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);


  // 4. NACHRICHT SENDEN (Die wichtigste Funktion!)
  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;

    const userText = input;
    setInput('');
    setMessages(prev => [...prev, { id: Date.now(), sender: 'user', text: userText }]);
    setIsLoading(true);

    // An Backend senden statt selber zu suchen!
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
    const mockTripJSON = JSON.stringify({
      date: "2026-01-30",
      start: "Fischen",
      end: "Sonthofen (Hotel)",
      total_duration: "35", // Dauer angepasst
      legs: [
        { 
          mode: "WALK", 
          line: "", 
          from: "Dein Standort", 
          to: "Fischen Bhf", 
          start_time: "08:00", 
          end_time: "08:10", 
          duration: 10 
        },
        { 
          mode: "RAIL", 
          line: "RE 17", 
          from: "Fischen Bhf", 
          to: "Sonthofen Bf", 
          start_time: "08:12", 
          end_time: "08:20", 
          duration: 8 
        },
        // --- HIER IST DER NEUE BUS ---
        { 
          mode: "BUS", 
          line: "Bus 45", // Bus-Linie
          from: "Sonthofen Bf", 
          to: "Rathausplatz", 
          start_time: "08:25", // 5 Min Umstieg
          end_time: "08:32", 
          duration: 7 
        },
        // -----------------------------
        { 
          mode: "WALK", 
          line: "", 
          from: "Rathausplatz", 
          to: "Zielort (Hotel)", 
          start_time: "08:32", 
          end_time: "08:35", 
          duration: 3 
        }
      ]
    });
    setMessages(prev => [...prev, { id: Date.now(), sender: 'ai', text: mockTripJSON }]);
  };

  // --- NEUER CODE START ---
  const handleDemoClick = () => {
    // Das exakte Datenformat, das deine TripCard erwartet
    const demoJson = JSON.stringify({
      date: "2026-01-30",
      start: "Fischen",
      end: "Sonthofen",
      total_duration: "23",
      legs: [
        { 
          mode: "WALK", 
          line: "", 
          from: "Dein Standort", 
          to: "Fischen Bhf", 
          start_time: "08:00", 
          end_time: "08:10", 
          duration: 10 
        },
        { 
          mode: "RAIL", 
          line: "RE 17", // Echter Zugname für Realismus
          from: "Fischen Bhf", 
          to: "Sonthofen Bf", 
          start_time: "08:12", 
          end_time: "08:20", 
          duration: 8 
        },
        { 
          mode: "WALK", 
          line: "", 
          from: "Sonthofen Bf", 
          to: "Zielort", 
          start_time: "08:20", 
          end_time: "08:25", 
          duration: 5 
        }
      ]
    });
    
    // Fügt die Nachricht hinzu, deine ChatMessage-Komponente rendert dann automatisch die Karte
    setMessages(prev => [...prev, { id: Date.now(), sender: 'ai', text: demoJson }]);
  };
  // --- NEUER CODE ENDE ---
  
  <div className="flex gap-2">
            <button onClick={testTripCard} className="text-xs bg-emerald-100 text-emerald-700 px-3 py-1 rounded">
  🎫 Demo: Fischen Ticket
</button>
            
            {/* --- NEUER BUTTON --- */}
            <button onClick={handleDemoClick} className="text-xs bg-blue-100 text-blue-700 px-3 py-1 rounded font-bold">
              🎫 Demo: Fischen-Sonthofen
            </button>
            {/* -------------------- */}
            
          </div>

  return (
    <div className="h-screen w-full bg-slate-50 flex flex-col md:flex-row overflow-hidden font-sans rounded-3xl" ref={containerRef}>
      
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
            <button onClick={testTripCard} className="text-xs bg-emerald-100 text-emerald-700 px-3 py-1 rounded">Test Card</button>
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

      <FilterPanel isOpen={showFilters} onClose={() => setShowFilters(false)} filters={filters} setFilters={setFilters}/>
    </div>
  );
}