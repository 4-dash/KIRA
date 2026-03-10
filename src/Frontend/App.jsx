import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  ArrowRight,
  BedDouble,
  Bot,
  Bus,
  Camera,
  Check,
  Clock,
  Coffee,
  Compass,
  Download,
  FerrisWheel,
  Footprints,
  Landmark,
  Loader2,
  MapPin,
  Menu,
  Music4,
  Save,
  Send,
  ShoppingBag,
  Star,
  Trees,
  Train,
  Upload,
  User,
  UtensilsCrossed,
  X,
} from 'lucide-react';

const INITIAL_MESSAGE = {
  id: 1,
  sender: 'ai',
  text: 'Guten Tag! Ich bin KIRA. Wohin möchtest du reisen?',
};

function safeJsonParse(value) {
  if (typeof value !== 'string') return null;
  const clean = value.replace(/```json/g, '').replace(/```/g, '').trim();
  if (!(clean.startsWith('{') || clean.startsWith('['))) return null;
  try {
    return JSON.parse(clean);
  } catch {
    return null;
  }
}

function decodePolyline(encoded) {
  if (!encoded) return [];
  const poly = [];
  let index = 0;
  let lat = 0;
  let lng = 0;

  while (index < encoded.length) {
    let b;
    let shift = 0;
    let result = 0;
    do {
      b = encoded.charCodeAt(index++) - 63;
      result |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    const dlat = (result & 1) !== 0 ? ~(result >> 1) : result >> 1;
    lat += dlat;

    shift = 0;
    result = 0;
    do {
      b = encoded.charCodeAt(index++) - 63;
      result |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    const dlng = (result & 1) !== 0 ? ~(result >> 1) : result >> 1;
    lng += dlng;

    poly.push([lat / 1e5, lng / 1e5]);
  }
  return poly;
}

function getParsedMessages(messages) {
  return messages.map((msg) => ({ ...msg, parsed: safeJsonParse(msg.text) }));
}

function getLatestRenderablePlan(parsedMessages) {
  for (let i = parsedMessages.length - 1; i >= 0; i -= 1) {
    const parsed = parsedMessages[i]?.parsed;
    if (!parsed) continue;
    if (parsed.legs || parsed?.type === 'activity_list' || parsed?.type === 'multi_step_plan') {
      return { message: parsedMessages[i], data: parsed };
    }
  }
  return null;
}

function modeIcon(mode) {
  if (mode === 'RAIL') return Train;
  if (mode === 'BUS') return Bus;
  return Footprints;
}

function modeColor(mode) {
  if (mode === 'RAIL') return 'bg-blue-100 text-blue-600 border-blue-200';
  if (mode === 'BUS') return 'bg-amber-100 text-amber-600 border-amber-200';
  return 'bg-emerald-100 text-emerald-600 border-emerald-200';
}

const ROUTE_COLORS = ['#2563eb', '#7c3aed', '#ea580c', '#0f766e', '#dc2626', '#0891b2'];

function getLegRouteColor(leg, index = 0) {
  if (leg?.mode === 'WALK') return '#16a34a';
  if (leg?.mode === 'BUS') return '#f59e0b';
  if (leg?.mode === 'RAIL') return '#2563eb';
  return ROUTE_COLORS[index % ROUTE_COLORS.length];
}

function getCategoryMeta(place = {}) {
  const haystack = [place.category, place.type, place.subcategory, place.tags, place.description, place.name]
    .flat()
    .filter(Boolean)
    .join(' ')
    .toLowerCase();

  if (/(restaurant|gasthof|essen|food|küche|cafe|café|bar|bistro)/.test(haystack)) {
    return {
      label: 'Gastronomie',
      icon: UtensilsCrossed,
      emoji: '🍽️',
      chip: 'bg-amber-100 text-amber-700 border-amber-200',
      markerBg: '#f59e0b',
      markerBorder: '#fef3c7',
    };
  }
  if (/(museum|galerie|ausstellung|kultur|theater|denkmal|histor)/.test(haystack)) {
    return {
      label: 'Kultur',
      icon: Landmark,
      emoji: '🏛️',
      chip: 'bg-violet-100 text-violet-700 border-violet-200',
      markerBg: '#8b5cf6',
      markerBorder: '#ede9fe',
    };
  }
  if (/(hotel|unterkunft|hostel|pension|resort|camping|ferienwohnung)/.test(haystack)) {
    return {
      label: 'Unterkunft',
      icon: BedDouble,
      emoji: '🛏️',
      chip: 'bg-sky-100 text-sky-700 border-sky-200',
      markerBg: '#0ea5e9',
      markerBorder: '#e0f2fe',
    };
  }
  if (/(park|natur|wander|berg|see|outdoor|trail|landschaft)/.test(haystack)) {
    return {
      label: 'Natur',
      icon: Trees,
      emoji: '🌲',
      chip: 'bg-emerald-100 text-emerald-700 border-emerald-200',
      markerBg: '#16a34a',
      markerBorder: '#dcfce7',
    };
  }
  if (/(shop|einkauf|retail|markt|store|boutique)/.test(haystack)) {
    return {
      label: 'Shopping',
      icon: ShoppingBag,
      emoji: '🛍️',
      chip: 'bg-rose-100 text-rose-700 border-rose-200',
      markerBg: '#f43f5e',
      markerBorder: '#ffe4e6',
    };
  }
  if (/(freizeit|erlebnis|spaß|attraction|event|zoo|aquarium|kino|konzert)/.test(haystack)) {
    return {
      label: 'Freizeit',
      icon: FerrisWheel,
      emoji: '🎡',
      chip: 'bg-pink-100 text-pink-700 border-pink-200',
      markerBg: '#ec4899',
      markerBorder: '#fce7f3',
    };
  }
  if (/(aussicht|view|foto|camera)/.test(haystack)) {
    return {
      label: 'Aussicht',
      icon: Camera,
      emoji: '📷',
      chip: 'bg-cyan-100 text-cyan-700 border-cyan-200',
      markerBg: '#06b6d4',
      markerBorder: '#cffafe',
    };
  }
  if (/(musik|music|festival)/.test(haystack)) {
    return {
      label: 'Musik',
      icon: Music4,
      emoji: '🎵',
      chip: 'bg-fuchsia-100 text-fuchsia-700 border-fuchsia-200',
      markerBg: '#d946ef',
      markerBorder: '#fae8ff',
    };
  }
  if (/(tour|tourismus|poi|highlight|sehenswert)/.test(haystack)) {
    return {
      label: 'Highlight',
      icon: Compass,
      emoji: '📍',
      chip: 'bg-indigo-100 text-indigo-700 border-indigo-200',
      markerBg: '#6366f1',
      markerBorder: '#e0e7ff',
    };
  }
  return {
    label: 'Ort',
    icon: Star,
    emoji: '⭐',
    chip: 'bg-slate-100 text-slate-700 border-slate-200',
    markerBg: '#64748b',
    markerBorder: '#e2e8f0',
  };
}

function createPoiMapIcon(L, place = {}) {
  const meta = getCategoryMeta(place);
  return L.divIcon({
    className: 'kira-poi-marker',
    html: `<div style="width:32px;height:32px;border-radius:9999px;background:${meta.markerBg};border:2px solid ${meta.markerBorder};display:flex;align-items:center;justify-content:center;box-shadow:0 6px 14px rgba(15,23,42,0.22);font-size:16px;line-height:1;">${meta.emoji}</div>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
    popupAnchor: [0, -14],
  });
}



function formatOpeningHours(openingHours) {
  if (!openingHours) return [];

  const entries = Array.isArray(openingHours) ? openingHours : [openingHours];

  const dayMap = {
    Monday: 'Mo',
    Tuesday: 'Di',
    Wednesday: 'Mi',
    Thursday: 'Do',
    Friday: 'Fr',
    Saturday: 'Sa',
    Sunday: 'So',
  };

  const normalizeDay = (value) => {
    if (!value || typeof value !== 'string') return value;
    const raw = value.split('/').pop();
    return dayMap[raw] || raw;
  };

  const dayOrder = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];

  const compressDays = (days) => {
    const normalized = [...new Set((days || []).filter(Boolean))]
      .sort((a, b) => dayOrder.indexOf(a) - dayOrder.indexOf(b));
    if (!normalized.length) return '';

    const groups = [];
    let start = normalized[0];
    let prevIndex = dayOrder.indexOf(normalized[0]);

    for (let i = 1; i < normalized.length; i += 1) {
      const current = normalized[i];
      const currentIndex = dayOrder.indexOf(current);
      if (currentIndex === prevIndex + 1) {
        prevIndex = currentIndex;
        continue;
      }
      groups.push(start === dayOrder[prevIndex] ? start : `${start}–${dayOrder[prevIndex]}`);
      start = current;
      prevIndex = currentIndex;
    }

    groups.push(start === dayOrder[prevIndex] ? start : `${start}–${dayOrder[prevIndex]}`);
    return groups.join(', ');
  };

  const formatDate = (value) => {
    if (!value) return null;
    const [year, month, day] = String(value).split('-');
    if (!year || !month || !day) return value;
    return `${day}.${month}.${year}`;
  };

  const lines = entries
    .map((entry) => {
      if (!entry || typeof entry !== 'object') return null;

      const dayValues = Array.isArray(entry.dayOfWeek)
        ? entry.dayOfWeek.map(normalizeDay)
        : [normalizeDay(entry.dayOfWeek)];

      const days = compressDays(dayValues);
      const opens = entry.opens || '?';
      const closes = entry.closes || '?';
      const validFrom = formatDate(entry.validFrom);
      const validThrough = formatDate(entry.validThrough);

      let dateRange = '';
      if (validFrom && validThrough) {
        dateRange = ` (${validFrom} – ${validThrough})`;
      } else if (validFrom) {
        dateRange = ` (ab ${validFrom})`;
      } else if (validThrough) {
        dateRange = ` (bis ${validThrough})`;
      }

      if (days) return `${days}: ${opens}–${closes}${dateRange}`;
      return `${opens}–${closes}${dateRange}`;
    })
    .filter(Boolean);

  return [...new Set(lines)];
}


function firstNonEmpty(...values) {
  for (const value of values.flat()) {
    if (value === undefined || value === null) continue;
    if (typeof value === 'string' && !value.trim()) continue;
    return value;
  }
  return null;
}

function getPlaceDescription(place = {}) {
  const raw = firstNonEmpty(
    place.description,
    place.short_description,
    place.summary,
    place.details,
    place.text,
    place.content,
  );

  if (Array.isArray(raw)) {
    return raw.filter(Boolean).join('\n\n') || 'Keine Beschreibung verfügbar.';
  }
  if (raw && typeof raw === 'object') {
    return Object.values(raw).filter(Boolean).join('\n\n') || 'Keine Beschreibung verfügbar.';
  }
  return String(raw || 'Keine Beschreibung verfügbar.');
}

function getPlaceAddress(place = {}) {
  return firstNonEmpty(
    place.address,
    place.full_address,
    place.address_text,
    [place.street, place.house_number, place.postcode, place.city].filter(Boolean).join(', '),
    [place.street, place.city].filter(Boolean).join(', '),
    place?.address?.streetAddress,
    [place?.address?.streetAddress, place?.address?.postalCode, place?.address?.addressLocality].filter(Boolean).join(', '),
  );
}

function getPlaceWebsite(place = {}) {
  return firstNonEmpty(place.website, place.url, place.link, place?.address?.url);
}

function getPlacePhone(place = {}) {
  return firstNonEmpty(place.telephone, place.phone, place?.address?.telephone);
}

function getPlaceOpeningHours(place = {}) {
  return firstNonEmpty(place.opening_hours, place.openingHoursSpecification, place.openingHours, place.openinghours);
}

function getPlaceDateRange(place = {}) {
  return {
    startDate: firstNonEmpty(place.start_date, place.startDate, place.validFrom),
    endDate: firstNonEmpty(place.end_date, place.endDate, place.validThrough),
  };
}

function buildSelectionPayload({ kind, messageId, planData, step, leg, dayIndex, stepIndex, legIndex, activity }) {
  if (!kind) return null;
  if (kind === 'trip') {
    return {
      selection_type: 'trip',
      message_id: messageId,
      label: `${planData?.start || ''} → ${planData?.end || ''}`.trim(),
      from_name: planData?.start,
      to_name: planData?.end,
    };
  }
  if (kind === 'day') {
    return {
      selection_type: 'day',
      message_id: messageId,
      day_index: dayIndex,
      label: `Tag ${dayIndex}`,
    };
  }
  if (kind === 'step') {
    return {
      selection_type: 'step',
      message_id: messageId,
      day_index: dayIndex,
      step_index: stepIndex,
      label: step?.label || step?.title || `Schritt ${stepIndex + 1}`,
    };
  }
  if (kind === 'leg') {
    return {
      selection_type: 'leg',
      message_id: messageId,
      day_index: dayIndex,
      step_index: stepIndex,
      leg_index: legIndex,
      label: `${leg?.from || ''} → ${leg?.to || ''}`.trim(),
      from_name: leg?.from,
      to_name: leg?.to,
    };
  }
  if (kind === 'activity') {
    return {
      selection_type: 'activity',
      message_id: messageId,
      day_index: dayIndex,
      step_index: stepIndex,
      label: activity?.name,
      name: activity?.name,
      coords: Number.isFinite(activity?.lat) && Number.isFinite(activity?.lon) ? [activity.lat, activity.lon] : undefined,
    };
  }
  return null;
}

function enrichSelectionWithPlanContext(selection, planData) {
  if (!selection || !planData) return selection;
  const enriched = { ...selection };

  if (selection.selection_type === 'activity' && Number.isInteger(selection.step_index)) {
    const activity = planData?.steps?.[selection.step_index]?.data;
    if (activity) {
      enriched.name = enriched.name || activity.name;
      enriched.label = enriched.label || activity.name;
      if (!Array.isArray(enriched.coords) && Number.isFinite(activity?.lat) && Number.isFinite(activity?.lon)) {
        enriched.coords = [activity.lat, activity.lon];
      }
    }
  }

  if ((selection.selection_type === 'trip' || selection.selection_type === 'step' || selection.selection_type === 'leg') && Number.isInteger(selection.step_index)) {
    const trip = planData?.steps?.[selection.step_index]?.data || planData;
    const firstLeg = trip?.legs?.[0];
    const lastLeg = trip?.legs?.[trip.legs.length - 1];
    if (firstLeg?.from) enriched.from_name = enriched.from_name || firstLeg.from;
    if (lastLeg?.to) enriched.to_name = enriched.to_name || lastLeg.to;
  }

  return enriched;
}


function inferOperationFromSelection(selection, userText = '', dragOverride = null) {
  if (!selection) return null;
  const text = (userText || '').toLowerCase();
  if (selection.selection_type === 'leg') {
    return { operation: 'regenerate_leg', scope: 'leg' };
  }
  if (selection.selection_type === 'day') {
    return { operation: 'reroute_day', scope: 'day' };
  }
  if (selection.selection_type === 'step') {
    return { operation: 'regenerate_step', scope: 'step' };
  }
  if (selection.selection_type === 'trip') {
    return { operation: 'regenerate_trip', scope: 'trip' };
  }
  if (selection.selection_type === 'activity') {
    if (dragOverride) return { operation: 'move_activity', scope: 'activity' };
    if (text.includes('ersetz') || text.includes('replace') || text.includes('andere')) {
      return { operation: 'replace_activity', scope: 'activity' };
    }
    return { operation: 'apply_route_preferences', scope: 'activity' };
  }
  return null;
}

function SelectionActions({ selection, pendingOperation, onChooseOperation }) {
  if (!selection) return null;
  const buttons = [];
  if (selection.selection_type === 'trip') {
    buttons.push({ operation: 'regenerate_trip', label: 'Trip neu berechnen' });
  }
  if (selection.selection_type === 'day') {
    buttons.push({ operation: 'reroute_day', label: 'Tag neu berechnen' });
  }
  if (selection.selection_type === 'step') {
    buttons.push({ operation: 'regenerate_step', label: 'Schritt neu berechnen' });
  }
  if (selection.selection_type === 'leg') {
    buttons.push({ operation: 'regenerate_leg', label: 'Leg neu berechnen' });
    buttons.push({ operation: 'apply_route_preferences', label: 'Präferenzen anwenden' });
  }
  if (selection.selection_type === 'activity') {
    buttons.push({ operation: 'move_activity', label: 'Standort verschieben' });
    buttons.push({ operation: 'replace_activity', label: 'Aktivität ersetzen' });
    buttons.push({ operation: 'apply_route_preferences', label: 'Umgebung neu routen' });
  }
  if (!buttons.length) return null;
  return (
    <div className="mb-3 flex flex-wrap gap-2">
      {buttons.map((button) => {
        const active = pendingOperation?.operation === button.operation;
        return (
          <button
            key={button.operation}
            type="button"
            onClick={() => onChooseOperation({ operation: button.operation, scope: selection.selection_type })}
            className={`rounded-xl border px-3 py-2 text-xs font-bold transition ${active ? 'border-slate-800 bg-slate-800 text-white' : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'}`}
          >
            {button.label}
          </button>
        );
      })}
    </div>
  );
}

function SelectionBanner({ selection, dragOverride, pendingOperation, onClear }) {
  if (!selection && !dragOverride) return null;
  return (
    <div className="mb-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          {selection && (
            <div>
              <span className="font-bold text-slate-800">Im Fokus:</span>{' '}
              {selection.label || selection.name || selection.selection_type}
            </div>
          )}
          {dragOverride && (
            <div>
              <span className="font-bold text-slate-800">Karten-Override:</span>{' '}
              {dragOverride.target_label} → {dragOverride.coords[0].toFixed(5)}, {dragOverride.coords[1].toFixed(5)}
            </div>
          )}
          {pendingOperation && (
            <div>
              <span className="font-bold text-slate-800">Aktion:</span> {pendingOperation.operation}
            </div>
          )}
          <div className="text-slate-500">
            Änderungen werden erst angewendet, wenn du unten eine Aktion auswählst oder ein Element auf der Karte verschiebst.
          </div>
        </div>
        <button onClick={onClear} className="rounded-lg bg-white px-3 py-1 font-bold text-slate-600 border border-slate-200">
          Zurücksetzen
        </button>
      </div>
    </div>
  );
}

function SinglePlaceCard({ place, isSelected, onSelect, selectionMode = 'single', isChecked = false }) {
  const meta = getCategoryMeta(place);
  const PlaceIcon = meta.icon;
  const [isExpanded, setIsExpanded] = useState(false);
  const description = getPlaceDescription(place);
  const address = getPlaceAddress(place);
  const phone = getPlacePhone(place);
  const website = getPlaceWebsite(place);
  const { startDate, endDate } = getPlaceDateRange(place);
  const formattedOpeningHours = formatOpeningHours(getPlaceOpeningHours(place));

  const previewStyle = {
    whiteSpace: 'normal',
    overflow: 'hidden',
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical',
    overflowWrap: 'anywhere',
    wordBreak: 'break-word',
  };

  const fullDescriptionStyle = {
    whiteSpace: 'pre-wrap',
    overflow: 'visible',
    display: 'block',
    height: 'auto',
    maxHeight: 'none',
    overflowWrap: 'anywhere',
    wordBreak: 'break-word',
  };

  return (
    <div
      className={`w-full text-left rounded-xl border p-4 shadow-sm transition ${
        isSelected
          ? 'border-slate-800 ring-2 ring-slate-200 bg-slate-50'
          : 'border-slate-200 bg-white hover:border-slate-300'
      }`}
    >
      <button type="button" onClick={onSelect} className="w-full text-left">
        <div className="flex gap-4">
          {selectionMode === 'multi' && (
            <div
              className={`mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border text-[11px] font-bold ${
                isChecked
                  ? 'border-slate-800 bg-slate-800 text-white'
                  : 'border-slate-300 bg-white text-transparent'
              }`}
            >
              ✓
            </div>
          )}

          <div className={`h-10 w-10 rounded-full flex items-center justify-center shrink-0 border ${meta.chip}`}>
            <PlaceIcon size={18} />
          </div>

          <div className="min-w-0 flex-1">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <h4 className="font-bold text-slate-800 text-sm">{place.name}</h4>
              <span className={`rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${meta.chip}`}>
                {meta.label}
              </span>
            </div>

            {!isExpanded && (
              <div className="text-xs text-slate-600 leading-5" style={previewStyle}>
                {description}
              </div>
            )}
          </div>
        </div>
      </button>

      {isExpanded && (
        <div className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-3 text-left">
          <div className="text-xs text-slate-600 leading-5" style={fullDescriptionStyle}>
            {description}
          </div>

          {(address || phone || website || startDate || endDate || formattedOpeningHours.length > 0) && (
            <div className="mt-3 space-y-1 border-t border-slate-200 pt-3 text-xs text-slate-600">
              {address && (
                <div>
                  <span className="font-semibold text-slate-700">Adresse:</span> {address}
                </div>
              )}

              {phone && (
                <div>
                  <span className="font-semibold text-slate-700">Telefon:</span> {phone}
                </div>
              )}

              {formattedOpeningHours.length > 0 && (
                <div>
                  <span className="font-semibold text-slate-700">Öffnungszeiten:</span>
                  <div className="mt-1 space-y-1">
                    {formattedOpeningHours.map((line, idx) => (
                      <div key={idx} className="text-xs text-slate-600">
                        {line}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {website && (
                <div>
                  <span className="font-semibold text-slate-700">Website:</span>{' '}
                  <a
                    href={website}
                    target="_blank"
                    rel="noreferrer"
                    className="text-blue-600 underline"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {website}
                  </a>
                </div>
              )}

              {(startDate || endDate) && (
                <div>
                  <span className="font-semibold text-slate-700">Zeitraum:</span>{' '}
                  {startDate || '?'}
                  {endDate ? ` – ${endDate}` : ''}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="mt-3 flex items-center justify-between gap-2 text-xs">
        <button
          type="button"
          onClick={() => setIsExpanded((prev) => !prev)}
          className="font-bold text-slate-500 hover:text-slate-700"
        >
          {isExpanded ? 'Beschreibung einklappen' : 'Beschreibung aufklappen'}
        </button>

        {Number.isFinite(place?.lat) && Number.isFinite(place?.lon) && (
          <span className="text-slate-400">
            {place.lat.toFixed(4)}, {place.lon.toFixed(4)}
          </span>
        )}
      </div>
    </div>
  );
}

function TripCard({
  data,
  title,
  isFocused,
  onFocusTrip,
  onFocusLeg,
  selection,
  messageId,
  dayIndex,
  stepIndex,
  onQuickAction,
}) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [openLegs, setOpenLegs] = useState({});
  if (!data?.legs) return null;

  const toggleLeg = (index) => setOpenLegs((prev) => ({ ...prev, [index]: !prev[index] }));

  return (
    <div className={`w-full max-w-md rounded-2xl border shadow-sm overflow-hidden my-3 ${isFocused ? 'border-slate-800 ring-2 ring-slate-200' : 'border-slate-200 bg-white'}`}>
      <div className="w-full bg-slate-50 p-4 border-b border-slate-100">
        <div className="flex justify-between items-start gap-3">
          <button onClick={onFocusTrip} className="flex-1 text-left hover:opacity-90">
            <div className="flex items-center gap-2 text-slate-800 font-bold text-sm">
              {data.start} <ArrowRight size={14} /> {data.end}
            </div>
            <div className="text-xs text-slate-500 mt-1 flex items-center gap-1">
              <Clock size={12} /> {data.date} • {data.total_duration} Min.
            </div>
            {title && <div className="text-xs mt-2 font-bold uppercase tracking-wider text-slate-400">{title}</div>}
          </button>
          <div className="flex flex-col items-end gap-2">
            <button type="button" onClick={onFocusTrip} className="bg-slate-200 text-slate-700 px-2 py-1 rounded-lg text-xs font-bold">Fokus</button>
            <button type="button" onClick={() => setIsExpanded((prev) => !prev)} className="text-[11px] font-bold text-slate-500 hover:text-slate-700">
              {isExpanded ? 'Trip einklappen' : 'Trip aufklappen'}
            </button>
          </div>
        </div>
      </div>
      {isExpanded && (
        <>
          <div className="px-4 pt-3 flex gap-2">
            <button type="button" onClick={() => onQuickAction?.({ operation: 'regenerate_trip', scope: 'trip' })} className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-bold text-slate-600 hover:border-slate-300">Neu berechnen</button>
          </div>
          <div className="p-4 relative">
            {data.legs.map((leg, index) => {
              const Icon = modeIcon(leg.mode);
              const isLegSelected =
                selection?.selection_type === 'leg' &&
                selection?.message_id === messageId &&
                selection?.day_index === dayIndex &&
                selection?.step_index === stepIndex &&
                selection?.leg_index === index;
              const isLast = index === data.legs.length - 1;
              return (
                <button
                  key={`${leg.from}-${leg.to}-${index}`}
                  onClick={() => onFocusLeg(leg, index)}
                  className={`flex w-full gap-3 relative pb-6 last:pb-0 text-left rounded-xl px-2 ${isLegSelected ? 'bg-slate-50 ring-1 ring-slate-200' : 'hover:bg-slate-50'}`}
                >
                  {!isLast && <div className="absolute left-[26px] top-8 bottom-0 w-0.5 bg-slate-200" />}
                  <div className="w-12 text-xs font-bold text-slate-500 pt-2 text-right">{leg.start_time}</div>
                  <div className="relative z-10">
                    <div className={`h-8 w-8 rounded-full border-2 flex items-center justify-center ${modeColor(leg.mode)}`}>
                      <Icon size={14} />
                    </div>
                  </div>
                  <div className="flex-1 pt-1">
                    <div className="mb-2 flex items-start justify-between gap-3">
                      <div>
                        <div className="font-bold text-sm text-slate-700">{leg.mode === 'WALK' ? 'Fußweg' : `${leg.mode} ${leg.line || ''}`}</div>
                        <div className="text-xs text-slate-500">{leg.from} <span className="text-slate-300">→</span> {leg.to}</div>
                        <div className="text-[11px] text-slate-400 mt-1">{leg.duration} Min.</div>
                      </div>
                      <div className="flex flex-col items-end gap-2">
                        <button type="button" onClick={(event) => { event.stopPropagation(); onQuickAction?.({ operation: 'regenerate_leg', scope: 'leg', legIndex: index }); }} className="rounded-md border border-slate-200 bg-white px-2 py-1 text-[10px] font-bold text-slate-500">Leg neu</button>
                        <button type="button" onClick={(event) => { event.stopPropagation(); toggleLeg(index); }} className="text-[10px] font-bold text-slate-500 hover:text-slate-700">{openLegs[index] ? 'Details ausblenden' : 'Details anzeigen'}</button>
                      </div>
                    </div>
                    {openLegs[index] && (
                      <div className="rounded-xl border border-slate-100 bg-slate-50 p-3 text-[11px] text-slate-600 space-y-1">
                        {leg.route_long_name && <div><span className="font-bold text-slate-700">Linie:</span> {leg.route_long_name}</div>}
                        {leg.headsign && <div><span className="font-bold text-slate-700">Richtung:</span> {leg.headsign}</div>}
                        <div><span className="font-bold text-slate-700">Start:</span> {leg.from}</div>
                        {leg.from_stop_name && leg.from_stop_name !== leg.from && <div><span className="font-bold text-slate-700">Station Start:</span> {leg.from_stop_name}</div>}
                        {leg.from_platform && <div><span className="font-bold text-slate-700">Gleis/Steig Start:</span> {leg.from_platform}</div>}
                        <div><span className="font-bold text-slate-700">Ziel:</span> {leg.to}</div>
                        {leg.to_stop_name && leg.to_stop_name !== leg.to && <div><span className="font-bold text-slate-700">Station Ziel:</span> {leg.to_stop_name}</div>}
                        {leg.to_platform && <div><span className="font-bold text-slate-700">Gleis/Steig Ziel:</span> {leg.to_platform}</div>}
                        {Array.isArray(leg.stops) && leg.stops.length > 0 && <div><span className="font-bold text-slate-700">Zwischenhalte:</span> {leg.stops.length}</div>}
                      </div>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

function ActivityList({ data, onSelectActivity, selectedActivityName, messageId, selectedActivities = [], onToggleActivitySelection, onStartTripPlanningFromPois }) {
  const selectedCount = selectedActivities.length;
  return (
    <div className="w-full mt-3 space-y-3">
      <p className="text-sm text-slate-500 font-medium">Ich habe {data.items.length} Vorschläge für {data.location} gefunden:</p>
      <div className="rounded-2xl border border-slate-200 bg-slate-50 p-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-sm font-bold text-slate-800">Mehrere POIs für die Reiseplanung auswählen</div>
            <div className="text-xs text-slate-500">Ausgewählt: {selectedCount}</div>
          </div>
          <button
            type="button"
            onClick={() => onStartTripPlanningFromPois?.()}
            disabled={!selectedCount}
            className={`rounded-xl px-3 py-2 text-xs font-bold ${selectedCount ? 'bg-slate-800 text-white hover:bg-slate-700' : 'bg-slate-200 text-slate-400 cursor-not-allowed'}`}
          >
            Mit Auswahl Reise planen
          </button>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3">
        {data.items.map((item, idx) => {
          const isChecked = selectedActivities.some((poi) => poi.name === item.name);
          return (
            <SinglePlaceCard
              key={`${item.name}-${idx}`}
              place={item}
              selectionMode="multi"
              isChecked={isChecked}
              isSelected={selectedActivityName === item.name || isChecked}
              onSelect={() => {
                onSelectActivity(
                  buildSelectionPayload({
                    kind: 'activity',
                    messageId,
                    activity: item,
                  }),
                );
                onToggleActivitySelection?.(item);
              }}
            />
          );
        })}
      </div>
    </div>
  );
}

function RequestStateCard({ parsed }) {
  const state = parsed?.request_state || {};
  const chips = [
    state.trip_type ? ['Typ', state.trip_type] : null,
    state.start ? ['Start', state.start] : null,
    state.end ? ['Ziel', state.end] : null,
    state.base_location ? ['Basis', state.base_location] : null,
    state.days ? ['Tage', String(state.days)] : null,
    state.pace ? ['Pace', state.pace] : null,
    state.activities_per_day ? ['Akt./Tag', String(state.activities_per_day)] : null,
    state.interest ? ['Interesse', state.interest] : null,
    state.date ? ['Datum', state.date] : null,
    Array.isArray(state.selected_pois) && state.selected_pois.length ? ['POIs', state.selected_pois.join(', ')] : null,
  ].filter(Boolean);

  return (
    <div className="mt-3 rounded-2xl border border-amber-200 bg-amber-50 p-4 text-slate-700 shadow-sm">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-full bg-amber-100 p-2 text-amber-700">
          <AlertCircle size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-xs font-bold uppercase tracking-wider text-amber-700">Rückfrage</div>
          <p className="mt-1 text-sm font-medium text-slate-800">{parsed?.question}</p>
          {!!chips.length && (
            <div className="mt-3 flex flex-wrap gap-2">
              {chips.map(([label, value]) => (
                <div key={`${label}-${value}`} className="rounded-full border border-amber-200 bg-white px-3 py-1 text-xs text-slate-700">
                  <span className="font-bold text-slate-800">{label}:</span> {value}
                </div>
              ))}
            </div>
          )}
          {Array.isArray(parsed?.missing_fields) && parsed.missing_fields.length > 0 && (
            <div className="mt-3 text-xs text-slate-600">
              Noch offen: {parsed.missing_fields.join(', ')}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ChatMessage({ msg, selection, onSelect, onChooseOperation, selectedPois, onTogglePoiSelection, onStartTripPlanningFromPois }) {
  const isAi = msg.sender === 'ai';
  const [isSaved, setIsSaved] = useState(false);
  const parsed = msg.parsed;
  const parsedError = parsed?.type === 'error' ? (parsed.message || parsed.error) : parsed?.error;
  const displayText = parsedError ? parsedError : (parsed?.type === 'clarification_question' ? '' : (parsed ? parsed.intro || '' : msg.text));

  const handleSaveTrip = async () => {
    const dataToSave = parsed;
    if (!dataToSave) return;
    try {
      const protocol = window.location.protocol;
      const host = window.location.hostname;
      const response = await fetch(`${protocol}//${host}:8000/api/save_trip`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(dataToSave),
      });
      const result = await response.json();
      if (result.status === 'success') setIsSaved(true);
    } catch (e) {
      console.error('Fehler beim Speichern der Reise:', e);
    }
  };

  const handleExportTrip = () => {
    if (!parsed) return;
    const blob = new Blob([JSON.stringify(parsed, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `KIRA_Reiseplan_${new Date().toISOString().split('T')[0]}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const isSelectedActivityMessage = selection?.message_id === msg.id && selection?.selection_type === 'activity';

  return (
    <div className={`flex w-full mb-4 ${isAi ? 'justify-start' : 'justify-end'}`}>
      <div className={`flex max-w-[95%] md:max-w-[85%] ${isAi ? 'flex-row' : 'flex-row-reverse'}`}>
        <div className={`shrink-0 h-8 w-8 rounded-full flex items-center justify-center mx-2 ${isAi ? 'bg-slate-200 text-slate-600' : 'bg-slate-300 text-slate-700'}`}>
          {isAi ? <Bot size={18} /> : <User size={18} />}
        </div>
        <div className="flex flex-col w-full">
          {(displayText || !parsed) && (
            <div className={`p-3 rounded-2xl text-sm shadow-sm w-fit ${parsedError ? 'bg-rose-50 border border-rose-200 text-rose-700' : (isAi ? 'bg-white border border-slate-100 text-slate-700 rounded-tl-none' : 'bg-slate-700 text-white rounded-tr-none')}`}>
              <p className="whitespace-pre-line">{displayText || msg.text}</p>
            </div>
          )}

          {parsed?.legs && (
            <TripCard
              data={parsed}
              messageId={msg.id}
              selection={selection}
              isFocused={selection?.message_id === msg.id && selection?.selection_type === 'trip'}
              onFocusTrip={() => onSelect(buildSelectionPayload({ kind: 'trip', messageId: msg.id, planData: parsed }))}
              onFocusLeg={(leg, legIndex) => onSelect(buildSelectionPayload({ kind: 'leg', messageId: msg.id, planData: parsed, leg, legIndex }))}
              onQuickAction={onChooseOperation}
            />
          )}

          {parsed?.type === 'clarification_question' && <RequestStateCard parsed={parsed} />}

          {(parsed?.type === 'error' || parsed?.error || parsed?.message) && !parsed?.legs && parsed?.type !== 'multi_step_plan' && parsed?.type !== 'activity_list' && parsed?.type !== 'clarification_question' && (
            <div className="mt-3 bg-red-50 p-3 rounded-xl border border-red-100 flex gap-3 items-center text-red-600">
              <AlertCircle size={18} className="shrink-0" />
              <div className="flex flex-col">
                <span className="text-xs font-medium">{parsed?.message || parsed?.error}</span>
              </div>
            </div>
          )}

          {parsed?.type === 'activity_list' && (
            <ActivityList
              data={parsed}
              messageId={msg.id}
              selectedActivityName={isSelectedActivityMessage ? selection?.name : null}
              selectedActivities={selectedPois?.[msg.id] || []}
              onSelectActivity={onSelect}
              onToggleActivitySelection={onTogglePoiSelection ? (item) => onTogglePoiSelection(msg.id, item, parsed) : undefined}
              onStartTripPlanningFromPois={onStartTripPlanningFromPois ? () => onStartTripPlanningFromPois(msg.id, parsed) : undefined}
            />
          )}

          {parsed?.type === 'multi_step_plan' && (
            <div className="mt-4 space-y-0 ml-1 border-l-2 border-slate-200 pl-4">
              {(() => {
                let currentDay = 1;
                return parsed.steps.map((step, idx) => {
                  if (step.type === 'header') currentDay += idx === 0 ? 0 : 1;
                  const dayIndex = currentDay;
                  const stepSelected = selection?.message_id === msg.id && selection?.selection_type === 'step' && selection?.step_index === idx;
                  const activitySelected = selection?.message_id === msg.id && selection?.selection_type === 'activity' && selection?.step_index === idx;
                  return (
                    <div key={`${step.type}-${idx}`} className="relative">
                      {step.type === 'header' && (
                        <button
                          onClick={() => onSelect(buildSelectionPayload({ kind: 'day', messageId: msg.id, dayIndex, planData: parsed }))}
                          className="mt-8 mb-4 first:mt-0 text-left"
                        >
                          <div className="absolute -left-[25px] mt-1.5 w-4 h-4 rounded-full bg-slate-800 border-2 border-white z-10" />
                          <h3 className="font-bold text-slate-800 text-lg ml-1">{step.title}</h3>
                        </button>
                      )}

                      {step.type === 'trip' && (
                        <TripCard
                          data={step.data}
                          title={step.label || 'Fahrt'}
                          messageId={msg.id}
                          dayIndex={dayIndex}
                          stepIndex={idx}
                          selection={selection}
                          isFocused={stepSelected}
                          onFocusTrip={() => onSelect(buildSelectionPayload({ kind: 'step', messageId: msg.id, planData: parsed, step, dayIndex, stepIndex: idx }))}
                          onFocusLeg={(leg, legIndex) => onSelect(buildSelectionPayload({ kind: 'leg', messageId: msg.id, planData: parsed, leg, dayIndex, stepIndex: idx, legIndex }))}
                          onQuickAction={onChooseOperation}
                        />
                      )}

                      {step.type === 'activity' && (
                        <div className="mb-6">
                          <div className="mb-2 flex items-center justify-between gap-2">
                            <div className="text-xs font-bold text-indigo-400 uppercase tracking-wider">Aktivität</div>
                            {activitySelected && (
                              <div className="flex flex-wrap gap-2">
                                <button
                                  type="button"
                                  onClick={() => onChooseOperation?.({ operation: 'replace_activity', scope: 'activity' })}
                                  className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-bold text-slate-600 hover:border-slate-300"
                                >
                                  Ersetzen
                                </button>
                                <button
                                  type="button"
                                  onClick={() => onChooseOperation?.({ operation: 'move_activity', scope: 'activity' })}
                                  className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] font-bold text-slate-600 hover:border-slate-300"
                                >
                                  Auf Karte verschieben
                                </button>
                              </div>
                            )}
                          </div>
                          <SinglePlaceCard
                            place={step.data}
                            isSelected={activitySelected}
                            onSelect={() =>
                              onSelect(
                                buildSelectionPayload({ kind: 'activity', messageId: msg.id, planData: parsed, activity: step.data, dayIndex, stepIndex: idx }),
                              )
                            }
                          />
                        </div>
                      )}

                      {step.type === 'error' && (
                        <div className="mb-6 bg-red-50 p-3 rounded-xl border border-red-100 flex gap-3 items-center text-red-600 mt-1">
                          <AlertCircle size={18} className="shrink-0" />
                          <div className="flex flex-col">
                            <span className="text-xs font-medium">{step.message}</span>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                });
              })()}
            </div>
          )}

          {parsed && (parsed.legs || parsed.type === 'multi_step_plan') && (
            <div className="flex flex-wrap gap-2 mt-4 ml-1">
              <button
                onClick={handleSaveTrip}
                disabled={isSaved}
                className={`px-4 py-2 w-fit rounded-xl text-sm font-bold flex items-center gap-2 transition-all ${isSaved ? 'bg-emerald-100 text-emerald-700 border border-emerald-200' : 'bg-slate-800 text-white hover:bg-slate-700 shadow-md hover:shadow-lg'}`}
              >
                {isSaved ? <Check size={16} /> : <Save size={16} />}
                {isSaved ? 'In Datenbank gespeichert' : 'In DB speichern'}
              </button>
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
}


function hasActiveEditIntent(selection, pendingOperation, dragOverride) {
  return Boolean(selection && (pendingOperation?.operation || dragOverride));
}

export default function App() {
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState([INITIAL_MESSAGE]);
  const [isLoading, setIsLoading] = useState(false);
  const socketRef = useRef(null);
  const [socket, setSocket] = useState(null);
  const [showMobileChat, setShowMobileChat] = useState(true);
  const [activeDay, setActiveDay] = useState(1);
  const [isMapReady, setIsMapReady] = useState(false);
  const [selection, setSelection] = useState(null);
  const [dragOverride, setDragOverride] = useState(null);
  const [pendingOperation, setPendingOperation] = useState(null);
  const [selectedPoisByMessage, setSelectedPoisByMessage] = useState({});
  const [sessionId] = useState(() => {
    // Always start a fresh backend session on every full page load.
    // This prevents old follow-up/question state from leaking into a new chat after F5.
    return window.crypto?.randomUUID?.() || `kira-${Date.now()}`;
  });

  const mapContainerRef = useRef(null);
  const messagesEndRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const routeLayerRef = useRef(null);
  const fileInputRef = useRef(null);
  const draggableMarkersRef = useRef([]);

  const parsedMessages = useMemo(() => getParsedMessages(messages), [messages]);
  const latestRenderable = useMemo(() => getLatestRenderablePlan(parsedMessages), [parsedMessages]);

  useEffect(() => {

    if (socketRef.current && (socketRef.current.readyState === WebSocket.OPEN || socketRef.current.readyState === WebSocket.CONNECTING)) {
      return;
    }

    const host = window.location.hostname;
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // Logic: add port 8000 if using docker-compose.dev.yml
    const isDev = import.meta.env.VITE_RUNNING_COMP === 'DEV';
    const port = isDev ? ':8000' : '';

    const wsUrl = `${wsProtocol}//${host}${port}/chat`;
    const ws = new WebSocket(wsUrl);

    socketRef.current = ws;

    ws.onopen = () => console.log(`✅ Connected to KIRA Backend at ${wsUrl}`);

    ws.onmessage = (event) => {
      setIsLoading(false);
      setPendingOperation(null);
      setDragOverride(null);
      try {
        const parsed = safeJsonParse(event.data);
        if (parsed?.selection) {
          setSelection(parsed.selection);
          if (typeof parsed.selection?.day_index === 'number') {
            setActiveDay(parsed.selection.day_index);
          }
        }
      } catch {
        // noop
      }
      
      const uniqueId = `${Date.now()}-${Math.random()}`;
      setMessages((prev) => [...prev, { id: uniqueId, sender: 'ai', text: event.data }]);
    };

    ws.onerror = (e) => {
      console.error('❌ WebSocket Error:', e);
      setIsLoading(false);
    };

    ws.onclose = (e) => {
      setIsLoading(false);
      setPendingOperation(null);
      // 3. Only show error message if it wasn't a deliberate close
      if (e.code !== 1000) {
        const errorId = `${Date.now()}-${Math.random()}`;
        setMessages((prev) => ([
          ...prev,
          {
            id: errorId,
            sender: 'ai',
            text: JSON.stringify({ type: 'error', message: 'Verbindung zum Backend verloren.' }),
          },
        ]));
      }
    };

    setSocket(ws);

    // 4. Cleanup: Close connection when component unmounts
    return () => {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close(1000); 
      }
    };
  }, []); // Empty array keeps the effect from re-running constantly
  
  useEffect(() => {
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

    const checkL = setInterval(() => {
      if (window.L && mapContainerRef.current) {
        clearInterval(checkL);
        if (mapInstanceRef.current) {
          mapInstanceRef.current.remove();
          mapInstanceRef.current = null;
        }
        const map = window.L.map(mapContainerRef.current).setView([47.5162, 10.1936], 11);
        window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png').addTo(map);
        mapInstanceRef.current = map;
        setIsMapReady(true);
        setTimeout(() => map.invalidateSize(), 200);
      }
    }, 100);

    return () => clearInterval(checkL);
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  useEffect(() => {
    if (!isMapReady || !mapInstanceRef.current || !window.L) return;
    const data = latestRenderable?.data;
    if (!data) return;

    if (!routeLayerRef.current) {
      routeLayerRef.current = window.L.layerGroup().addTo(mapInstanceRef.current);
    }
    routeLayerRef.current.clearLayers();
    draggableMarkersRef.current.forEach((m) => m.remove());
    draggableMarkersRef.current = [];

    const routesToDraw = [];
    const markers = [];
    const addRouteFromLeg = (leg, color) => {
      const rawGeo = leg.geometry || leg.legGeometry?.points;
      let points = [];
      if (typeof rawGeo === 'string') points = decodePolyline(rawGeo);
      else if (Array.isArray(rawGeo)) points = rawGeo;
      const resolvedColor = color || getLegRouteColor(leg, routesToDraw.length);
      if (points.length) routesToDraw.push({ points, color: resolvedColor, mode: leg?.mode });
      if (leg.from_coords) markers.push({ pos: leg.from_coords, label: leg.from, kind: 'leg-from', leg, color: resolvedColor });
      if (leg.to_coords) markers.push({ pos: leg.to_coords, label: leg.to, kind: 'leg-to', leg, color: resolvedColor });
    };

    if (data.legs) {
      data.legs.forEach((leg, index) => addRouteFromLeg(leg, getLegRouteColor(leg, index)));
    } else if (data.type === 'activity_list') {
      data.items.forEach((item) => {
        if (item.lat && item.lon) markers.push({ pos: [item.lat, item.lon], label: item.name, kind: 'activity', activity: item });
      });
    } else if (data.type === 'multi_step_plan') {
      let currentDay = 1;
      data.steps.forEach((step, idx) => {
        if (step.type === 'header') {
          currentDay += idx === 0 ? 0 : 1;
          return;
        }
        if (currentDay !== activeDay) return;
        if (step.type === 'trip' && step.data?.legs) {
          step.data.legs.forEach((leg, legIndex) => addRouteFromLeg(leg, getLegRouteColor(leg, legIndex)));
        }
        if (step.type === 'activity' && step.data?.lat && step.data?.lon) {
          markers.push({ pos: [step.data.lat, step.data.lon], label: step.data.name, kind: 'activity', activity: step.data, stepIndex: idx, dayIndex: currentDay });
        }
      });
    }

    routesToDraw.forEach((route) => {
      window.L.polyline(route.points, {
        color: route.color,
        weight: route.mode === 'WALK' ? 4 : 6,
        opacity: 0.9,
        lineCap: 'round',
        lineJoin: 'round',
        dashArray: route.mode === 'WALK' ? '8 8' : undefined,
      }).addTo(routeLayerRef.current);
    });

    markers.forEach((marker) => {
      let base;
      if (marker.kind === 'activity') {
        base = window.L.marker(marker.pos, { icon: createPoiMapIcon(window.L, marker.activity || {}) });
      } else {
        base = window.L.circleMarker(marker.pos, {
          radius: 6,
          fillColor: marker.color || '#2563eb',
          color: '#ffffff',
          weight: 2,
          fillOpacity: 1,
        });
      }
      base.bindPopup(marker.label).addTo(routeLayerRef.current);
      base.on('click', () => {
        if (marker.kind === 'activity') {
          setSelection(buildSelectionPayload({ kind: 'activity', messageId: latestRenderable?.message?.id, activity: marker.activity, dayIndex: marker.dayIndex, stepIndex: marker.stepIndex }));
        }
      });
    });

    const enableDragForSelection = selection?.selection_type === 'leg' || selection?.selection_type === 'activity';
    if (enableDragForSelection) {
      if (selection.selection_type === 'activity' && selection.coords) {
        const draggable = window.L.marker(selection.coords, { draggable: true }).addTo(routeLayerRef.current);
        draggable.on('dragend', (event) => {
          const latlng = event.target.getLatLng();
          setDragOverride({
            type: 'activity',
            target_label: selection.label || selection.name,
            coords: [latlng.lat, latlng.lng],
          });
        });
        draggableMarkersRef.current.push(draggable);
      }
      if (selection.selection_type === 'leg') {
        const latest = latestRenderable?.data;
        const sourceLeg = latest?.legs?.[selection.leg_index]
          || latest?.steps?.[selection.step_index]?.data?.legs?.[selection.leg_index];
        if (sourceLeg?.from_coords) {
          const startMarker = window.L.marker(sourceLeg.from_coords, { draggable: true }).addTo(routeLayerRef.current);
          startMarker.bindPopup('Start verschieben');
          startMarker.on('dragend', (event) => {
            const latlng = event.target.getLatLng();
            setDragOverride({
              type: 'leg-start',
              target_label: sourceLeg.from,
              coords: [latlng.lat, latlng.lng],
            });
          });
          draggableMarkersRef.current.push(startMarker);
        }
        if (sourceLeg?.to_coords) {
          const endMarker = window.L.marker(sourceLeg.to_coords, { draggable: true }).addTo(routeLayerRef.current);
          endMarker.bindPopup('Ziel verschieben');
          endMarker.on('dragend', (event) => {
            const latlng = event.target.getLatLng();
            setDragOverride({
              type: 'leg-end',
              target_label: sourceLeg.to,
              coords: [latlng.lat, latlng.lng],
            });
          });
          draggableMarkersRef.current.push(endMarker);
        }
      }
    }

    const allPoints = [...routesToDraw.flatMap((r) => r.points), ...markers.map((m) => m.pos)];
    if (allPoints.length) {
      mapInstanceRef.current.fitBounds(window.L.latLngBounds(allPoints), { padding: [50, 50] });
    }
  }, [latestRenderable, activeDay, isMapReady, selection]);

  const clearSelection = () => {
    setSelection(null);
    setDragOverride(null);
    setPendingOperation(null);
  };


  const togglePoiSelection = (messageId, poi, parsedData) => {
    setSelectedPoisByMessage((prev) => {
      const current = prev[messageId] || [];
      const exists = current.some((item) => item.name === poi.name);
      const nextItems = exists ? current.filter((item) => item.name !== poi.name) : [...current, { ...poi, source_location: parsedData?.location }];
      return { ...prev, [messageId]: nextItems };
    });
  };

  const startTripPlanningFromPois = (messageId, parsedData) => {
    const selectedPois = selectedPoisByMessage[messageId] || [];
    if (!selectedPois.length) return;

    const poiNames = selectedPois.map((poi) => poi.name).join(', ');
    const location = parsedData?.location || selectedPois[0]?.source_location || 'dem Zielort';
    const intentText = `Plane eine Reise mit diesen ausgewählten POIs in ${location}: ${poiNames}`;

    setMessages((prev) => [...prev, { id: Date.now(), sender: 'user', text: intentText }]);
    setIsLoading(true);

    const payload = {
      type: 'chat_request',
      session_id: sessionId,
      text: intentText,
      selected_pois: selectedPois,
      selection: null,
      edit_operation: null,
      drag_override: null,
      current_trip: null,
    };

    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
    } else {
      setMessages((prev) => [...prev, { id: Date.now(), sender: 'ai', text: '⚠️ Keine Verbindung zum Server. Läuft das Backend?' }]);
      setIsLoading(false);
    }
  };

  const handleFileChange = (event) => {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const content = e.target.result;
        JSON.parse(content);
        setMessages((prev) => [...prev, { id: Date.now(), sender: 'ai', text: content }]);
        setActiveDay(1);
      } catch {
        alert('Die hochgeladene Datei ist kein gültiger KIRA-Reiseplan.');
      }
    };
    reader.readAsText(file);
    event.target.value = '';
  };

  const handleSend = (e) => {
    e.preventDefault();
    const userText = input.trim();
    if (!userText) return;

    setMessages((prev) => [...prev, { id: Date.now(), sender: 'user', text: userText }]);
    setInput('');
    setIsLoading(true);

    const enrichedSelection = enrichSelectionWithPlanContext(selection, latestRenderable?.data || null);
    const effectiveOperation = pendingOperation || (dragOverride ? inferOperationFromSelection(enrichedSelection, userText, dragOverride) : null);
    const shouldSendSelectionContext = hasActiveEditIntent(enrichedSelection, effectiveOperation, dragOverride);
    const payload = {
      type: 'chat_request',
      session_id: sessionId,
      text: userText,
      selection: shouldSendSelectionContext ? enrichedSelection : null,
      selected_pois: Object.values(selectedPoisByMessage).flat(),
      edit_operation: effectiveOperation,
      drag_override: shouldSendSelectionContext ? dragOverride : null,
      current_trip: shouldSendSelectionContext ? (latestRenderable?.data || null) : null,
    };

    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(payload));
    } else {
      setMessages((prev) => [...prev, { id: Date.now(), sender: 'ai', text: '⚠️ Keine Verbindung zum Server. Läuft das Backend?' }]);
      setIsLoading(false);
      setPendingOperation(null);
    }
  };

  const totalDays = useMemo(() => {
    const data = latestRenderable?.data;
    if (data?.type !== 'multi_step_plan') return 0;
    return data.steps.filter((s) => s.type === 'header').length;
  }, [latestRenderable]);

  return (
    <div className="h-screen w-full bg-slate-50 flex flex-col md:flex-row overflow-hidden font-sans rounded-3xl">
      <div className={`${showMobileChat ? 'flex' : 'hidden'} md:flex flex-col w-full md:w-[34rem] bg-white border-r border-slate-200 z-20 h-full`}>
        <div className="p-4 border-b border-slate-100 flex items-center justify-between">
          <h1 className="font-bold text-slate-800 text-lg">KIRA</h1>
          <button onClick={() => setShowMobileChat(false)} className="md:hidden"><X size={24} /></button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 bg-slate-50 space-y-4">
          {parsedMessages.map((msg) => (
            <ChatMessage
              key={msg.id}
              msg={msg}
              selection={selection}
              selectedPois={selectedPoisByMessage}
              onTogglePoiSelection={togglePoiSelection}
              onStartTripPlanningFromPois={startTripPlanningFromPois}
              onSelect={(next) => { setSelection(next); setDragOverride(null); setPendingOperation(null); }}
              onChooseOperation={(operation) => setPendingOperation(operation)}
            />
          ))}
          {isLoading && <div className="text-slate-500 text-sm ml-4">KIRA denkt nach... <Loader2 className="inline animate-spin" /></div>}
          <div ref={messagesEndRef} />
        </div>

        <div className="p-4 bg-white border-t border-slate-100">
          <SelectionBanner selection={selection} dragOverride={dragOverride} pendingOperation={pendingOperation} onClear={clearSelection} />
          <SelectionActions selection={selection} pendingOperation={pendingOperation} onChooseOperation={setPendingOperation} />
          <form onSubmit={handleSend} className="flex items-center gap-2 mb-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={hasActiveEditIntent(selection, pendingOperation, dragOverride) ? `Änderung für ${selection?.label || selection?.selection_type} eingeben…` : 'Wohin möchtest du reisen?'}
              className="flex-1 bg-slate-100 rounded-2xl py-3 pl-5 pr-4 focus:outline-none"
            />
            <button type="submit" className="p-3 bg-slate-700 text-white rounded-xl">
              <Send size={18} />
            </button>
          </form>
          <div className="flex gap-2">
            <input type="file" accept=".json" ref={fileInputRef} onChange={handleFileChange} style={{ display: 'none' }} />
            <button onClick={() => fileInputRef.current?.click()} className="text-xs bg-slate-200 text-slate-700 px-3 py-1 rounded font-bold flex items-center gap-1 hover:bg-slate-300">
              <Upload size={14} /> Trip importieren
            </button>
          </div>
        </div>
      </div>

      <div className="flex-1 relative bg-slate-50 h-full flex flex-col p-6">
        <div className="rounded-3xl overflow-hidden shadow-2xl border border-slate-200 bg-white h-full relative z-0">
          <div ref={mapContainerRef} className="w-full h-full" />
        </div>

        {!showMobileChat && (
          <button onClick={() => setShowMobileChat(true)} className="absolute top-4 left-4 z-[1000] bg-white p-2 rounded-xl shadow-md border border-slate-100 hover:bg-slate-50 transition-colors">
            <Menu className="text-slate-600" />
          </button>
        )}

        {totalDays > 1 && (
          <div className="absolute top-8 left-1/2 -translate-x-1/2 z-[1000] bg-white/95 backdrop-blur-md p-1.5 rounded-2xl shadow-xl border border-slate-200/50 flex gap-1">
            {Array.from({ length: totalDays }, (_, i) => i + 1).map((day) => (
              <button
                key={day}
                onClick={() => {
                  setActiveDay(day);
                  setSelection({ selection_type: 'day', day_index: day, label: `Tag ${day}`, message_id: latestRenderable?.message?.id });
                  setDragOverride(null);
                  setPendingOperation({ operation: 'reroute_day', scope: 'day' });
                }}
                className={`px-4 py-2 rounded-xl text-sm font-bold transition-all shadow-sm ${activeDay === day ? 'bg-slate-800 text-white scale-105' : 'bg-transparent text-slate-500 hover:bg-slate-100 hover:text-slate-700'}`}
              >
                Tag {day}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
