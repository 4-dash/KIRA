import React, { useState, useEffect, useRef } from 'react';
<<<<<<< Updated upstream
import { Send, Map as MapIcon, Navigation, Star, MapPin, Menu, X, Globe, User, Bot, Loader2, AlertCircle } from 'lucide-react';
=======
import { Send, Map as MapIcon, Navigation, Star, MapPin, Menu, X, Globe, User, Bot, Loader2, AlertCircle, Filter, Sliders,Train, Bus, Footprints, Clock, ArrowRight, Flag } from 'lucide-react';
>>>>>>> Stashed changes

// --- Configuration & Mock Data ---

const SUGGESTIONS = [
  { id: 1, name: "City Center Hotel", rating: 4.8, type: "Stay", price: "$$$" },
  { id: 2, name: "National Museum", rating: 4.6, type: "Culture", price: "$" },
  { id: 3, name: "Famous Food Market", rating: 4.9, type: "Dining", price: "$$" },
];

const INITIAL_MESSAGE = {
  id: 1,
  sender: 'ai',
  text: "Hello! I'm your AI Trip Advisor. I'm connected to the global map. Which city would you like to explore?",
};

// --- Components ---

const ChatMessage = ({ msg }) => {
  const isAi = msg.sender === 'ai';
  
  // Wir prüfen, ob der Text ein JSON-Objekt für einen Trip ist
  let tripData = null;
  let displayText = msg.text;

  // Einfacher Check: Beginnt es wie JSON? (Du kannst das robuster machen)
  if (isAi && typeof msg.text === 'string' && msg.text.trim().startsWith('{')) {
    try {
      const parsed = JSON.parse(msg.text);
      if (parsed.legs) {
        tripData = parsed;
        displayText = "Ich habe hier eine Verbindung für dich gefunden:";
      }
    } catch (e) {
      // Kein valides JSON, normaler Text
    }
  }

  return (
    <div className={`flex w-full mb-4 ${isAi ? 'justify-start' : 'justify-end'}`}>
<<<<<<< Updated upstream
      <div className={`flex max-w-[85%] md:max-w-[75%] ${isAi ? 'flex-row' : 'flex-row-reverse'}`}>
        <div className={`flex-shrink-0 h-8 w-8 rounded-full flex items-center justify-center mx-2 ${isAi ? 'bg-indigo-100 text-indigo-600' : 'bg-emerald-100 text-emerald-600'}`}>
          {isAi ? <Bot size={18} /> : <User size={18} />}
        </div>
        <div className={`p-3 rounded-2xl text-sm shadow-sm ${isAi ? 'bg-white border border-slate-100 text-slate-700 rounded-tl-none' : 'bg-emerald-500 text-white rounded-tr-none'}`}>
          <p>{msg.text}</p>
=======
      <div className={`flex max-w-[90%] md:max-w-[80%] ${isAi ? 'flex-row' : 'flex-row-reverse'}`}>
        <div className={`flex-shrink-0 h-8 w-8 rounded-full flex items-center justify-center mx-2 ${isAi ? 'bg-slate-200 text-slate-600' : 'bg-slate-300 text-slate-700'}`}>
          {isAi ? <Bot size={18} /> : <User size={18} />}
        </div>
        
        <div className="flex flex-col">
          {/* Die Textblase */}
          <div className={`p-3 rounded-2xl text-sm shadow-sm ${isAi ? 'bg-white border border-slate-100 text-slate-700 rounded-tl-none' : 'bg-slate-700 text-white rounded-tr-none'}`}>
            <p className="whitespace-pre-line">{displayText}</p>
          </div>

          {/* Falls Trip-Daten da sind -> Karte rendern */}
          {tripData && (
            <div className="mt-2 ml-1">
              <TripCard data={tripData} />
            </div>
          )}
>>>>>>> Stashed changes
        </div>
      </div>
    </div>
  );
};



const PlaceCard = ({ place }) => (
  <div className="bg-white p-3 rounded-xl border border-slate-100 shadow-sm hover:shadow-md transition-shadow flex items-center justify-between group cursor-pointer">
    <div className="flex items-center gap-3">
      <div className="h-10 w-10 rounded-lg bg-indigo-50 flex items-center justify-center text-indigo-600 group-hover:bg-indigo-600 group-hover:text-white transition-colors">
        <MapPin size={20} />
      </div>
      <div>
        <h4 className="font-semibold text-slate-800 text-sm">{place.name}</h4>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span className="flex items-center gap-1 text-amber-500"><Star size={12} fill="currentColor" /> {place.rating}</span>
          <span>•</span>
          <span>{place.type}</span>
          <span>•</span>
          <span>{place.price}</span>
        </div>
      </div>
    </div>
    <button className="text-slate-300 hover:text-indigo-600 transition-colors">
      <Navigation size={18} />
    </button>
  </div>
);

<<<<<<< Updated upstream
=======
const FilterPanel = ({ isOpen, onClose, filters, setFilters }) => {
  const toggleFilter = (category, id) => {
    setFilters(prev => ({
      ...prev,
      [category]: prev[category].includes(id)
        ? prev[category].filter(item => item !== id)
        : [...prev[category], id]
    }));
  };

  const clearFilters = () => {
    setFilters({ types: [], priceRanges: [], ratings: [] });
  };

  const activeFilterCount = Object.values(filters).flat().length;

  return (
    <>
      {isOpen && (
        <div 
          className="fixed inset-0 bg-black/40 z-30 backdrop-blur-sm transition-opacity rounded-3xl"
          onClick={onClose}
        />
      )}

      <div className={`
        fixed md:absolute top-0 left-0 w-full md:w-80 h-full bg-white shadow-2xl z-40
        transition-transform duration-300 ease-out overflow-y-auto rounded-r-3xl md:rounded-3xl
        ${isOpen ? 'translate-x-0' : '-translate-x-full'}
      `}>
        
        <div className="sticky top-0 bg-gradient-to-r from-slate-700 to-slate-800 text-white p-4 flex items-center justify-between shadow-lg rounded-tr-3xl md:rounded-t-3xl">
          <div className="flex items-center gap-3">
            <Sliders size={24} />
            <h2 className="font-bold text-lg">Filter</h2>
            {activeFilterCount > 0 && (
              <span className="ml-2 px-2.5 py-0.5 bg-white text-slate-700 text-xs font-bold rounded-full">
                {activeFilterCount}
              </span>
            )}
          </div>
          <button 
            onClick={onClose}
            className="p-1 hover:bg-slate-600 rounded-lg transition-colors"
          >
            <X size={24} />
          </button>
        </div>

        <div className="p-4 space-y-6">
          
          <div>
            <h3 className="font-semibold text-slate-800 text-sm mb-3 flex items-center gap-2">
              <MapPin size={16} />
              Aktivitätstypen
            </h3>
            <div className="grid grid-cols-2 gap-2">
              {FILTER_OPTIONS.types.map(type => (
                <button
                  key={type.id}
                  onClick={() => toggleFilter('types', type.id)}
                  className={`
                    p-3 rounded-xl font-medium text-sm transition-all border-2
                    ${filters.types.includes(type.id)
                      ? 'bg-slate-700 text-white border-slate-700 shadow-lg shadow-slate-300'
                      : 'bg-slate-50 text-slate-700 border-slate-200 hover:border-slate-300 hover:bg-slate-100'
                    }
                  `}
                >
                  {type.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <h3 className="font-semibold text-slate-800 text-sm mb-3 flex items-center gap-2">
              <Filter size={16} />
              Preisbereich
            </h3>
            <div className="space-y-2">
              {FILTER_OPTIONS.priceRanges.map(price => (
                <button
                  key={price.id}
                  onClick={() => toggleFilter('priceRanges', price.id)}
                  className={`
                    w-full p-3 rounded-xl font-medium text-sm text-left transition-all border-2
                    ${filters.priceRanges.includes(price.id)
                      ? 'bg-slate-700 text-white border-slate-700 shadow-lg shadow-slate-300'
                      : 'bg-slate-50 text-slate-700 border-slate-200 hover:border-slate-300 hover:bg-slate-100'
                    }
                  `}
                >
                  <span className="font-bold mr-2">{price.icon}</span>
                  {price.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <h3 className="font-semibold text-slate-800 text-sm mb-3 flex items-center gap-2">
              <Star size={16} />
              Mindestbewertung
            </h3>
            <div className="space-y-2">
              {FILTER_OPTIONS.ratings.map(rating => (
                <button
                  key={rating.id}
                  onClick={() => toggleFilter('ratings', rating.id)}
                  className={`
                    w-full p-3 rounded-xl font-medium text-sm text-left transition-all border-2
                    ${filters.ratings.includes(rating.id)
                      ? 'bg-slate-700 text-white border-slate-700 shadow-lg shadow-slate-300'
                      : 'bg-slate-50 text-slate-700 border-slate-200 hover:border-slate-300 hover:bg-slate-100'
                    }
                  `}
                >
                  <Star size={16} className="inline mr-2" fill="currentColor" />
                  {rating.label}
                </button>
              ))}
            </div>
          </div>

          {activeFilterCount > 0 && (
            <button
              onClick={clearFilters}
              className="w-full p-3 bg-slate-100 text-slate-600 hover:bg-slate-200 rounded-xl font-semibold transition-colors border border-slate-200"
            >
              Alle Filter löschen
            </button>
          )}
        </div>
      </div>
    </>
  );
};

const TripCard = ({ data }) => {
  if (!data || !data.legs) return null;

  return (
    <div className="w-full max-w-md bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden my-3">
      {/* Header: Zusammenfassung */}
      <div className="bg-slate-50 p-4 border-b border-slate-100 flex justify-between items-center">
        <div>
          <div className="flex items-center gap-2 text-slate-800 font-bold text-sm">
            {data.start} <ArrowRight size={14} /> {data.end}
          </div>
          <div className="text-xs text-slate-500 mt-1 flex items-center gap-1">
            <Clock size={12} /> {data.date} • {data.total_duration} Min.
          </div>
        </div>
        <div className="bg-slate-200 text-slate-600 px-2 py-1 rounded-lg text-xs font-bold">
          Trip
        </div>
      </div>

      {/* Body: Timeline */}
      <div className="p-4 relative">
        {data.legs.map((leg, index) => {
          const isLast = index === data.legs.length - 1;
          
          // Icon & Farbe je nach Modus wählen
          let Icon = Footprints;
          let colorClass = "bg-emerald-100 text-emerald-600 border-emerald-200";
          if (leg.mode === 'RAIL') { Icon = Train; colorClass = "bg-blue-100 text-blue-600 border-blue-200"; }
          if (leg.mode === 'BUS') { Icon = Bus; colorClass = "bg-amber-100 text-amber-600 border-amber-200"; }

          return (
            <div key={index} className="flex gap-3 relative pb-6 last:pb-0">
              {/* Vertikale Linie (außer beim letzten Element) */}
              {!isLast && (
                <div className="absolute left-[15px] top-8 bottom-0 w-0.5 bg-slate-200" />
              )}
              
              {/* Zeitspalte */}
              <div className="w-12 text-xs font-bold text-slate-500 pt-2 text-right">
                {leg.start_time}
              </div>

              {/* Icon Spalte */}
              <div className="relative z-10">
                <div className={`h-8 w-8 rounded-full border-2 flex items-center justify-center ${colorClass}`}>
                  <Icon size={14} />
                </div>
              </div>

              {/* Details Spalte */}
              <div className="flex-1 pt-1">
                <div className="font-bold text-sm text-slate-700">
                  {leg.mode === 'WALK' ? 'Fußweg' : `${leg.mode} ${leg.line}`}
                </div>
                <div className="text-xs text-slate-500">
                  {leg.from} <span className="text-slate-300">→</span> {leg.to}
                </div>
                <div className="text-[10px] text-slate-400 mt-1 uppercase tracking-wide">
                  {leg.duration} min
                </div>
              </div>
            </div>
          );
        })}

        {/* Ankunfts-Marker (Footer der Timeline) */}
        <div className="flex gap-3 relative mt-6 pt-2 border-t border-slate-50 border-dashed">
           <div className="w-12 text-xs font-bold text-slate-800 text-right">
             {data.legs[data.legs.length - 1].end_time}
           </div>
           <div className="relative z-10">
             <div className="h-8 w-8 rounded-full bg-slate-800 text-white flex items-center justify-center shadow-md">
               <Flag size={14} />
             </div>
           </div>
           <div className="flex-1 pt-1">
             <div className="font-bold text-sm text-slate-800">Ziel erreicht</div>
             <div className="text-xs text-slate-500">{data.end}</div>
           </div>
        </div>
      </div>
    </div>
  );
};

>>>>>>> Stashed changes
export default function App() {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState([INITIAL_MESSAGE]);
  const [isLoading, setIsLoading] = useState(false);
  const [isMounted, setIsMounted] = useState(false); // Track if component is ready
  
  // Default Map State (Paris)
  const [mapState, setMapState] = useState({ 
    lat: 49.878708, 
    lon:  8.646927, 
    name: "Darmstadt, Germany"
  }); 
  
  const [recommendations, setRecommendations] = useState([]);
  const [showMobileChat, setShowMobileChat] = useState(true);

  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  // Ensure map only loads after layout is complete
  useEffect(() => {
    setIsMounted(true);
  }, []);

<<<<<<< Updated upstream
=======
  // Resize Handler
  useEffect(() => {
    const handleMouseUp = () => {
      setIsResizing(false);
    };

    const handleMouseMove = (e) => {
      if (!isResizing || !containerRef.current) return;

      const rect = containerRef.current.getBoundingClientRect();
      const mapDiv = mapContainerRef.current.parentElement.getBoundingClientRect();
      const newHeight = ((e.clientY - mapDiv.top) / rect.height) * 100;

      if (newHeight > 20 && newHeight < 80) {
        setMapHeight(newHeight);
      }
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);

    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing]);

  // Leaflet Karte initialisieren
  useEffect(() => {
    if (!isMounted || !mapContainerRef.current) return;

    // Leaflet und die CSS laden
    const leafletLink = document.createElement('link');
    leafletLink.rel = 'stylesheet';
    leafletLink.href = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css';
    document.head.appendChild(leafletLink);

    const leafletScript = document.createElement('script');
    leafletScript.src = 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js';
    leafletScript.onload = () => {
      // Initialisiere die Karte
      const map = window.L.map(mapContainerRef.current).setView([mapState.lat, mapState.lon], 12);

      window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19,
      }).addTo(map);

      // Marker
      const marker = window.L.marker([mapState.lat, mapState.lon]).addTo(map);

      // Klick auf Karte
      map.on('click', (e) => {
        const { lat, lng } = e.latlng;
        
        // Marker aktualisieren
        marker.setLatLng([lat, lng]);
        
        // State aktualisieren
        setMapState({
          lat,
          lon: lng,
          name: `${lat.toFixed(4)}, ${lng.toFixed(4)}`
        });

        
        // Chat-Nachricht
        setMessages(prev => [...prev, {
          id: Date.now(),
          sender: 'ai',
          text: `Du hast eine neue Position ausgewählt: ${lat.toFixed(4)}, ${lng.toFixed(4)}`
        }]);
      });

      // Invalidate size nach kurzer Verzögerung
      setTimeout(() => {
        map.invalidateSize();
      }, 100);

      // Update Marker wenn sich mapState ändert
      return () => {
        map.remove();
      };
    };

    document.body.appendChild(leafletScript);
  }, [isMounted, mapState.lat, mapState.lon]);

  const handleMouseDown = (e) => {
    e.preventDefault();
    setIsResizing(true);
  };

    // --- NEW: Helper function to simulate a trip ---
  const testTripCard = () => {
    const mockTripJSON = JSON.stringify({
      date: "2026-01-27",
      start: "Kempten Hbf",
      end: "Fischen",
      total_duration: "34",
      legs: [
        { mode: "WALK", from: "Startpunkt", to: "Kempten Hbf", start_time: "07:30", end_time: "07:39", duration: 9 },
        { mode: "RAIL", line: "RE17", from: "Kempten Hbf", to: "Immenstadt", start_time: "07:43", end_time: "07:55", duration: 12 },
        { mode: "BUS", line: "45", from: "Immenstadt", to: "Fischen", start_time: "08:05", end_time: "08:17", duration: 12 }
      ]
    });

    setMessages(prev => [...prev, { 
      id: Date.now(), 
      sender: 'ai', 
      text: mockTripJSON 
    }]);
  };

>>>>>>> Stashed changes
  const handleSend = async (e) => {
    e.preventDefault();
    if (!input.trim()) return;

    const userText = input;
    setInput('');
    setMessages(prev => [...prev, { id: Date.now(), sender: 'user', text: userText }]);
    setIsLoading(true);

  

    try {
      const response = await fetch(
        `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(userText)}`
      );
      
      if (!response.ok) throw new Error("Network response was not ok");
      
      const data = await response.json();

      await new Promise(r => setTimeout(r, 800));

      if (data && data.length > 0) {
        const location = data[0];
        const newLat = parseFloat(location.lat);
        const newLon = parseFloat(location.lon);
        const displayName = location.display_name.split(',')[0];

        // Update map state (we ignore the API bbox now to force our own zoom)
        setMapState({ 
          lat: newLat, 
          lon: newLon, 
          name: displayName
        });
        
        setRecommendations(SUGGESTIONS);

        setMessages(prev => [...prev, { 
          id: Date.now() + 1, 
          sender: 'ai', 
          text: `I found ${displayName}! I've updated the map to show the area.` 
        }]);
      } else {
        setMessages(prev => [...prev, { 
          id: Date.now() + 1, 
          sender: 'ai', 
          text: `I couldn't find a place called "${userText}". Could you check the spelling?` 
        }]);
      }
    } catch (error) {
      console.error("Search error:", error);
      setMessages(prev => [...prev, { 
        id: Date.now() + 1, 
        sender: 'ai', 
        text: "I'm having trouble connecting to the map server. Please try again later." 
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  // Construct OpenStreetMap Embed URL
  // We manually calculate a small bounding box to force a "City View" zoom
  const getMapUrl = () => {
    const lat = parseFloat(String(mapState.lat));
    const lon = parseFloat(String(mapState.lon));

    // 0.025 is a slightly safer zoom level for initial loading
    const delta = 0.025; 
    
    const minLon = (lon - delta).toFixed(4);
    const minLat = (lat - delta).toFixed(4);
    const maxLon = (lon + delta).toFixed(4);
    const maxLat = (lat + delta).toFixed(4);

    // OSM Format: bbox=minLon,minLat,maxLon,maxLat
    return `https://www.openstreetmap.org/export/embed.html?bbox=${minLon},${minLat},${maxLon},${maxLat}&layer=mapnik&marker=${lat},${lon}`;
  };

  return (
    <div className="h-screen w-full bg-slate-50 flex flex-col md:flex-row overflow-hidden font-sans">
      
      {/* --- Left Panel: Chat & Controls --- */}
      <div className={`
        ${showMobileChat ? 'flex' : 'hidden'} 
        md:flex flex-col w-full md:w-[400px] lg:w-[450px] bg-white border-r border-slate-200 shadow-xl z-20 h-full absolute md:relative
      `}>
        {/* Header */}
        <div className="p-4 border-b border-slate-100 flex items-center justify-between bg-white">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 bg-indigo-600 rounded-xl flex items-center justify-center shadow-lg shadow-indigo-200">
              <Globe className="text-white" size={24} />
            </div>
            <div>
              <h1 className="font-bold text-slate-800 text-lg leading-tight">KIRA</h1>
              <p className="text-xs text-slate-500 font-medium">Real-time Map Agent</p>
            </div>
          </div>
          <button 
            onClick={() => setShowMobileChat(false)}
            className="md:hidden p-2 text-slate-400 hover:text-slate-600"
          >
            <X size={24} />
          </button>
        </div>

        {/* Chat Area */}
        <div className="flex-1 overflow-y-auto p-4 bg-slate-50 scrollbar-thin scrollbar-thumb-slate-200">
          <div className="space-y-2">
            <div className="text-center text-xs text-slate-400 my-4 uppercase tracking-wider font-semibold">Session Started</div>
            
            {messages.map((msg) => (
              <ChatMessage key={msg.id} msg={msg} />
            ))}
            
            {isLoading && (
              <div className="flex w-full mb-4 justify-start">
                 <div className="flex max-w-[85%] flex-row">
                    <div className="flex-shrink-0 h-8 w-8 rounded-full flex items-center justify-center mx-2 bg-indigo-100 text-indigo-600">
                      <Bot size={18} />
                    </div>
                    <div className="bg-white border border-slate-100 p-3 rounded-2xl rounded-tl-none shadow-sm flex items-center gap-3">
                      <Loader2 className="animate-spin text-indigo-500" size={18} />
                      <span className="text-sm text-slate-600">Searching global database...</span>
                    </div>
                 </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Input Area */}
        <div className="p-4 bg-white border-t border-slate-100">
          <form onSubmit={handleSend} className="relative flex items-center">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Type a city name..."
              disabled={isLoading}
              className="w-full bg-slate-100 text-slate-800 placeholder:text-slate-400 rounded-full py-3 pl-5 pr-12 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:bg-white transition-all border border-transparent focus:border-indigo-100 disabled:opacity-70"
            />
            <button 
              type="submit"
              disabled={!input.trim() || isLoading}
              className="absolute right-1.5 p-2 bg-indigo-600 text-white rounded-full hover:bg-indigo-700 disabled:opacity-50 disabled:hover:bg-indigo-600 transition-colors shadow-md"
            >
              <Send size={18} />
            </button>
          </form>
<<<<<<< Updated upstream
          
          <div className="mt-3 flex gap-2 overflow-x-auto pb-1 no-scrollbar">
            {['Tokyo', 'New York', 'London', 'Sydney'].map(city => (
=======

          <div className="flex gap-2 overflow-x-auto pb-1 no-scrollbar">
            <button
              onClick={() => setShowFilters(true)}
              className="whitespace-nowrap px-4 py-2 bg-slate-700 hover:bg-slate-800 text-white text-sm font-semibold rounded-xl transition-colors shadow-md flex items-center gap-2"
              title="Filter öffnen"
            >
              <Sliders size={16} />
              Filter
            </button>
            <button
              onClick={testTripCard}
              className="whitespace-nowrap px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-semibold rounded-xl transition-colors shadow-md flex items-center gap-2"
            >
              <Navigation size={16} />
              Test Trip
            </button>
            {/* --- NEW BUTTON ENDS HERE --- */}
            {['Allgäu', 'Bodensee', 'Lindau', 'Füssen'].map(city => (
>>>>>>> Stashed changes
              <button 
                key={city}
                onClick={() => setInput(city)}
                disabled={isLoading}
                className="whitespace-nowrap px-3 py-1.5 bg-slate-50 hover:bg-indigo-50 text-slate-600 hover:text-indigo-600 text-xs font-medium rounded-lg border border-slate-200 transition-colors"
              >
                {city}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* --- Right Panel: Map & Recommendations --- */}
      <div className="flex-1 relative bg-slate-200 h-full flex flex-col">
        
        {/* Mobile Toggle Button */}
        {!showMobileChat && (
          <button 
            onClick={() => setShowMobileChat(true)}
            className="md:hidden absolute top-4 left-4 z-30 bg-white p-3 rounded-full shadow-lg text-indigo-600"
          >
            <Menu size={24} />
          </button>
        )}

        {/* Map Header Overlay */}
        <div className="absolute top-0 left-0 right-0 z-10 p-4 pointer-events-none">
          <div className="bg-white/90 backdrop-blur-md p-3 rounded-2xl shadow-lg border border-white/50 inline-flex items-center gap-3 pointer-events-auto">
            <div className="bg-orange-100 p-2 rounded-lg text-orange-600">
              <MapIcon size={20} />
            </div>
            <div>
              <h2 className="font-bold text-slate-800 text-sm">{mapState.name}</h2>
              <p className="text-xs text-slate-500">Live Map View</p>
            </div>
          </div>
        </div>

        {/* The Map (Iframe) */}
        <div className="flex-1 w-full h-full bg-slate-200 relative">
          {isMounted && (
            <iframe 
              width="100%" 
              height="100%" 
              frameBorder="0" 
              scrolling="no" 
              marginHeight={0} 
              marginWidth={0} 
              src={getMapUrl()} 
              className="w-full h-full"
              title="OpenStreetMap"
            ></iframe>
          )}
          
          <div className="absolute inset-0 pointer-events-none bg-indigo-900/5" />
        </div>

        {/* Recommendations Overlay */}
        {recommendations.length > 0 && (
          <div className="absolute bottom-6 left-4 right-4 z-10">
            <div className="bg-white/90 backdrop-blur-md border border-white/50 p-4 rounded-2xl shadow-xl max-h-[30vh] overflow-y-auto">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-semibold text-slate-800 flex items-center gap-2">
                  <Star className="text-yellow-500" size={16} fill="currentColor" />
                  Suggestions in {mapState.name}
                </h3>
                <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-1 rounded-full font-medium">Top Rated</span>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                {recommendations.map(place => (
                  <PlaceCard key={place.id} place={place} />
                ))}
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}