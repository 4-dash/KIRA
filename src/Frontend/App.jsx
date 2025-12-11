import React, { useState, useEffect, useRef } from 'react';
import { Send, Map as MapIcon, Navigation, Star, MapPin, Menu, X, Globe, User, Bot, Loader2, AlertCircle, Filter, Sliders } from 'lucide-react';

// --- Konfiguration & Mock-Daten ---

const SUGGESTIONS = [
  { id: 1, name: "City Center Hotel", rating: 4.8, type: "Unterkunft", price: "$$$" },
  { id: 2, name: "Nationalmuseum", rating: 4.6, type: "Kultur", price: "$" },
  { id: 3, name: "Berühmter Lebensmittelmarkt", rating: 4.9, type: "Gastronomie", price: "$$" },
];

const INITIAL_MESSAGE = {
  id: 1,
  sender: 'ai',
  text: "Guten Tag! Ich bin dein KI-Reiseberater. Ich bin mit der Weltkarte verbunden. Welche Stadt möchtest du erkunden?",
};

const FILTER_OPTIONS = {
  types: [
    { id: 'stay', label: 'Unterkunft', icon: MapPin },
    { id: 'dining', label: 'Gastronomie', icon: MapPin },
    { id: 'culture', label: 'Kultur', icon: MapPin },
    { id: 'nature', label: 'Natur', icon: MapPin },
    { id: 'adventure', label: 'Abenteuer', icon: MapPin },
    { id: 'shopping', label: 'Einkaufen', icon: MapPin },
  ],
  priceRanges: [
    { id: '$', label: 'Budget', icon: '$' },
    { id: '$$', label: 'Mittel', icon: '$$' },
    { id: '$$$', label: 'Premium', icon: '$$$' },
  ],
  ratings: [
    { id: 4.5, label: '4,5+ Sterne', value: 4.5 },
    { id: 4.0, label: '4,0+ Sterne', value: 4.0 },
    { id: 3.5, label: '3,5+ Sterne', value: 3.5 },
  ],
};

// --- Komponenten ---

const ChatMessage = ({ msg }) => {
  const isAi = msg.sender === 'ai';
  return (
    <div className={`flex w-full mb-4 ${isAi ? 'justify-start' : 'justify-end'}`}>
      <div className={`flex max-w-[85%] md:max-w-[75%] ${isAi ? 'flex-row' : 'flex-row-reverse'}`}>
        <div className={`flex-shrink-0 h-8 w-8 rounded-full flex items-center justify-center mx-2 ${isAi ? 'bg-slate-200 text-slate-600' : 'bg-slate-300 text-slate-700'}`}>
          {isAi ? <Bot size={18} /> : <User size={18} />}
        </div>
        <div className={`p-3 rounded-2xl text-sm shadow-sm ${isAi ? 'bg-white border border-slate-100 text-slate-700 rounded-tl-none' : 'bg-slate-500 text-white rounded-tr-none'}`}>
          <p>{msg.text}</p>
        </div>
      </div>
    </div>
  );
};

const PlaceCard = ({ place }) => (
  <div className="bg-white p-3 rounded-2xl border border-slate-100 shadow-sm hover:shadow-md transition-shadow flex items-center justify-between group cursor-pointer">
    <div className="flex items-center gap-3">
      <div className="h-10 w-10 rounded-xl bg-slate-100 flex items-center justify-center text-slate-600 group-hover:bg-slate-600 group-hover:text-white transition-colors">
        <MapPin size={20} />
      </div>
      <div>
        <h4 className="font-semibold text-slate-800 text-sm">{place.name}</h4>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <span className="flex items-center gap-1 text-slate-600"><Star size={12} fill="currentColor" /> {place.rating}</span>
          <span>•</span>
          <span>{place.type}</span>
          <span>•</span>
          <span>{place.price}</span>
        </div>
      </div>
    </div>
    <button className="text-slate-300 hover:text-slate-600 transition-colors">
      <Navigation size={18} />
    </button>
  </div>
);

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

export default function App() {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState([INITIAL_MESSAGE]);
  const [isLoading, setIsLoading] = useState(false);
  const [isMounted, setIsMounted] = useState(false);
  const [showMobileChat, setShowMobileChat] = useState(true);
  const [showFilters, setShowFilters] = useState(false);
  const [mapHeight, setMapHeight] = useState(50);
  const [isResizing, setIsResizing] = useState(false);
  
  const [filters, setFilters] = useState({
    types: [],
    priceRanges: [],
    ratings: []
  });
  
  const [mapState, setMapState] = useState({ 
    lat: 47.5162, 
    lon: 10.1936, 
    name: "Allgäu, Deutschland"
  }); 
  
  const [recommendations, setRecommendations] = useState([]);
  const mapContainerRef = useRef(null);
  const containerRef = useRef(null);

  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  useEffect(() => {
    setIsMounted(true);
  }, []);

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

        setRecommendations(SUGGESTIONS);
        
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
      
      if (!response.ok) throw new Error("Netzwerkfehler");
      
      const data = await response.json();

      await new Promise(r => setTimeout(r, 800));

      if (data && data.length > 0) {
        const location = data[0];
        const newLat = parseFloat(location.lat);
        const newLon = parseFloat(location.lon);
        const displayName = location.display_name.split(',')[0];

        setMapState({ 
          lat: newLat, 
          lon: newLon, 
          name: displayName
        });
        
        setRecommendations(SUGGESTIONS);

        setMessages(prev => [...prev, { 
          id: Date.now() + 1, 
          sender: 'ai', 
          text: `Ich habe ${displayName} gefunden! Die Karte wurde aktualisiert.` 
        }]);
      } else {
        setMessages(prev => [...prev, { 
          id: Date.now() + 1, 
          sender: 'ai', 
          text: `Ich konnte keinen Ort namens "${userText}" finden. Bitte überprüfe die Schreibweise.` 
        }]);
      }
    } catch (error) {
      console.error("Suchfehler:", error);
      setMessages(prev => [...prev, { 
        id: Date.now() + 1, 
        sender: 'ai', 
        text: "Ich habe Schwierigkeiten, die Verbindung zum Kartendienst herzustellen. Bitte versuche es später erneut." 
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="h-screen w-full bg-slate-50 flex flex-col md:flex-row overflow-hidden font-sans rounded-3xl">
      
      <FilterPanel 
        isOpen={showFilters} 
        onClose={() => setShowFilters(false)}
        filters={filters}
        setFilters={setFilters}
      />
      
      <div className={`
        ${showMobileChat ? 'flex' : 'hidden'} 
        md:flex flex-col w-full md:w-[400px] lg:w-[450px] bg-white border-r border-slate-200 shadow-xl z-20 h-full absolute md:relative rounded-r-3xl md:rounded-l-3xl
      `}>
        <div className="p-4 border-b border-slate-100 flex items-center justify-between bg-white rounded-tr-3xl md:rounded-tl-3xl">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 bg-slate-700 rounded-2xl flex items-center justify-center shadow-lg">
              <MapIcon className="text-white" size={24} />
            </div>
            <div>
              <h1 className="font-bold text-slate-800 text-lg leading-tight">KIRA</h1>
              <p className="text-xs text-slate-500 font-medium">KI-Reiseberater in Echtzeit</p>
            </div>
          </div>
          <button 
            onClick={() => setShowMobileChat(false)}
            className="md:hidden p-2 text-slate-400 hover:text-slate-600 rounded-lg"
          >
            <X size={24} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 bg-slate-50 scrollbar-thin scrollbar-thumb-slate-200">
          <div className="space-y-2">
            <div className="text-center text-xs text-slate-400 my-4 uppercase tracking-wider font-semibold">Sitzung gestartet</div>
            
            {messages.map((msg) => (
              <ChatMessage key={msg.id} msg={msg} />
            ))}
            
            {isLoading && (
              <div className="flex w-full mb-4 justify-start">
                 <div className="flex max-w-[85%] flex-row">
                    <div className="flex-shrink-0 h-8 w-8 rounded-full flex items-center justify-center mx-2 bg-slate-200 text-slate-600">
                      <Bot size={18} />
                    </div>
                    <div className="bg-white border border-slate-100 p-3 rounded-2xl rounded-tl-none shadow-sm flex items-center gap-3">
                      <Loader2 className="animate-spin text-slate-600" size={18} />
                      <span className="text-sm text-slate-600">Durchsuche globale Datenbank...</span>
                    </div>
                 </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        </div>

        <div className="p-4 bg-white border-t border-slate-100 rounded-br-3xl md:rounded-bl-3xl">
          <form onSubmit={handleSend} className="relative flex items-center gap-2 mb-3">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Stadt eingeben..."
              disabled={isLoading}
              className="flex-1 bg-slate-100 text-slate-800 placeholder:text-slate-400 rounded-2xl py-3 pl-5 pr-12 focus:outline-none focus:ring-2 focus:ring-slate-400/20 focus:bg-white transition-all border border-transparent focus:border-slate-200 disabled:opacity-70"
            />
            <button 
              type="submit"
              disabled={!input.trim() || isLoading}
              className="p-2.5 bg-slate-700 text-white rounded-xl hover:bg-slate-800 disabled:opacity-50 disabled:hover:bg-slate-700 transition-colors shadow-md"
            >
              <Send size={18} />
            </button>
          </form>

          <div className="flex gap-2 overflow-x-auto pb-1 no-scrollbar">
            <button
              onClick={() => setShowFilters(true)}
              className="whitespace-nowrap px-4 py-2 bg-slate-700 hover:bg-slate-800 text-white text-sm font-semibold rounded-xl transition-colors shadow-md flex items-center gap-2"
              title="Filter öffnen"
            >
              <Sliders size={16} />
              Filter
            </button>
            {['Allgäu', 'Bodensee', 'Lindau', 'Füssen'].map(city => (
              <button 
                key={city}
                onClick={() => setInput(city)}
                disabled={isLoading}
                className="whitespace-nowrap px-3 py-1.5 bg-slate-50 hover:bg-slate-100 text-slate-600 hover:text-slate-800 text-xs font-medium rounded-lg border border-slate-200 transition-colors"
              >
                {city}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div 
        ref={containerRef}
        className="flex-1 relative bg-slate-50 h-full flex flex-col p-6 rounded-l-3xl md:rounded-r-3xl"
      >
        
        {!showMobileChat && (
          <button 
            onClick={() => setShowMobileChat(true)}
            className="md:hidden absolute top-4 left-4 z-30 bg-white p-3 rounded-xl shadow-lg text-slate-700"
          >
            <Menu size={24} />
          </button>
        )}

        <div className="absolute top-6 left-6 right-6 z-10 pointer-events-none">
          <div className="bg-white/90 backdrop-blur-md p-3 rounded-2xl shadow-lg border border-white/50 inline-flex items-center gap-3 pointer-events-auto">
            <div className="bg-slate-100 p-2 rounded-xl text-slate-600">
              <MapIcon size={20} />
            </div>
            <div>
              <h2 className="font-bold text-slate-800 text-sm">{mapState.name}</h2>
              <p className="text-xs text-slate-500">Livekartenansicht</p>
            </div>
          </div>
        </div>

        <div 
          className="mt-20 rounded-3xl overflow-hidden shadow-2xl border border-slate-200 bg-white"
          style={{ height: `${mapHeight}%` }}
        >
          <div 
            ref={mapContainerRef}
            className="w-full h-full"
            style={{ pointerEvents: isResizing ? 'none' : 'auto' }}
          />
        </div>

        <div
          onMouseDown={handleMouseDown}
          className={`h-1 bg-gradient-to-r from-slate-200 via-slate-400 to-slate-200 rounded-full my-4 cursor-row-resize hover:h-1.5 transition-all select-none relative z-50 ${
            isResizing ? 'h-1.5 bg-slate-600 shadow-lg' : ''
          }`}
          title="Zum Ändern der Kartengröße ziehen"
        />

        <div className="flex-1 flex flex-col">
          {recommendations.length > 0 && (
            <div className="bg-white rounded-3xl shadow-lg border border-slate-200 p-4 overflow-y-auto">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-semibold text-slate-800 flex items-center gap-2">
                  <Star className="text-slate-600" size={16} fill="currentColor" />
                  Empfehlungen in {mapState.name}
                </h3>
                <span className="text-xs bg-slate-100 text-slate-700 px-2 py-1 rounded-full font-medium">Top bewertet</span>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                {recommendations.map(place => (
                  <PlaceCard key={place.id} place={place} />
                ))}
              </div>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}