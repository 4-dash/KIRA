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
  let tripData = null;
  let displayText = msg.text;

  // VERBESSERTE JSON ERKENNUNG
  // Wir suchen nach etwas, das wie ein JSON-Objekt aussieht, auch wenn Text davor steht.
  if (isAi && typeof msg.text === 'string') {
    // Entferne Markdown Code-Blöcke falls vorhanden
    const cleanText = msg.text.replace(/```json/g, '').replace(/```/g, '').trim();
    
    if (cleanText.startsWith('{') || cleanText.startsWith('[')) {
        try {
          const parsed = JSON.parse(cleanText);
          if (parsed.legs || parsed.suggestions) { // Prüfen auf typische KIRA Daten
            tripData = parsed;
            displayText = "Ich habe folgende Verbindung gefunden:"; // Standard-Text statt Rohdaten
          }
        } catch (e) {
          // Kein gültiges JSON
        }
    }
  }

  return (
    <div className={`flex w-full mb-4 ${isAi ? 'justify-start' : 'justify-end'}`}>
      <div className={`flex max-w-[90%] md:max-w-[80%] ${isAi ? 'flex-row' : 'flex-row-reverse'}`}>
        <div className={`shrink-0 h-8 w-8 rounded-full flex items-center justify-center mx-2 ${isAi ? 'bg-slate-200 text-slate-600' : 'bg-slate-300 text-slate-700'}`}>
          {isAi ? <Bot size={18} /> : <User size={18} />}
        </div>
        
        <div className="flex flex-col">
          <div className={`p-3 rounded-2xl text-sm shadow-sm ${isAi ? 'bg-white border border-slate-100 text-slate-700 rounded-tl-none' : 'bg-slate-700 text-white rounded-tr-none'}`}>
            <p className="whitespace-pre-line">{displayText}</p>
          </div>
          {tripData && (
            <div className="mt-2 ml-1">
              <TripCard data={tripData} />
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

const PlaceCard = ({ place }) => (
    <div className="bg-white p-3 rounded-2xl border border-slate-100 shadow-sm">
        <h4 className="font-bold">{place.name}</h4>
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
    const ws = new WebSocket('ws://localhost:8000/chat'); // ODER ws://192.168.0.70:8000/chat falls Localhost nicht geht

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