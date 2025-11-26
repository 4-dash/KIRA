import React, { useState, useEffect, useRef } from 'react';
import { Send, Map as MapIcon, Navigation, Star, MapPin, Menu, X, Globe, User, Bot, Loader2, AlertCircle } from 'lucide-react';

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
  return (
    <div className={`flex w-full mb-4 ${isAi ? 'justify-start' : 'justify-end'}`}>
      <div className={`flex max-w-[85%] md:max-w-[75%] ${isAi ? 'flex-row' : 'flex-row-reverse'}`}>
        <div className={`flex-shrink-0 h-8 w-8 rounded-full flex items-center justify-center mx-2 ${isAi ? 'bg-indigo-100 text-indigo-600' : 'bg-emerald-100 text-emerald-600'}`}>
          {isAi ? <Bot size={18} /> : <User size={18} />}
        </div>
        <div className={`p-3 rounded-2xl text-sm shadow-sm ${isAi ? 'bg-white border border-slate-100 text-slate-700 rounded-tl-none' : 'bg-emerald-500 text-white rounded-tr-none'}`}>
          <p>{msg.text}</p>
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
              <h1 className="font-bold text-slate-800 text-lg leading-tight">TripAI</h1>
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
          
          <div className="mt-3 flex gap-2 overflow-x-auto pb-1 no-scrollbar">
            {['Tokyo', 'New York', 'London', 'Sydney'].map(city => (
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
              className="w-full h-full grayscale-[0.2] contrast-[1.1]"
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