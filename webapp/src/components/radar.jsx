import { useRef, useState, useCallback } from "react";
import Player from "./player";
import Bomb from "./bomb";
import GrenadeLayer from "./GrenadeLayer";

const MIN_ZOOM = 1;
const MAX_ZOOM = 5;
const ZOOM_STEP = 0.25;

const Radar = ({
  playerArray,
  radarImage,
  mapData,
  localTeam,
  averageLatency,
  bombData,
  grenades,
  settings
}) => {
  const radarImageRef = useRef();
  const containerRef = useRef();

  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isPanning, setIsPanning] = useState(false);
  const [panStart, setPanStart] = useState({ x: 0, y: 0 });

  // Clamp pan so the map doesn't go out of bounds
  const clampPan = useCallback((x, y, z) => {
    const maxPan = ((z - 1) / z) * 50; // percentage-based limit
    return {
      x: Math.max(-maxPan, Math.min(maxPan, x)),
      y: Math.max(-maxPan, Math.min(maxPan, y)),
    };
  }, []);

  // Handle scroll wheel zoom
  const handleWheel = useCallback((e) => {
    e.preventDefault();
    setZoom((prev) => {
      const newZoom = e.deltaY < 0
        ? Math.min(prev + ZOOM_STEP, MAX_ZOOM)
        : Math.max(prev - ZOOM_STEP, MIN_ZOOM);

      // If zooming out to 1x, reset pan
      if (newZoom <= 1) {
        setPan({ x: 0, y: 0 });
      } else {
        // Clamp existing pan for new zoom level
        setPan((p) => clampPan(p.x, p.y, newZoom));
      }
      return newZoom;
    });
  }, [clampPan]);

  // Handle pan via mouse drag
  const handleMouseDown = useCallback((e) => {
    if (zoom <= 1) return; // no panning at 1x
    if (e.button !== 0) return; // left click only
    setIsPanning(true);
    setPanStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
  }, [zoom, pan]);

  const handleMouseMove = useCallback((e) => {
    if (!isPanning) return;
    const sensitivity = 0.5; // slow down panning for precision
    const rawX = (e.clientX - panStart.x) * sensitivity;
    const rawY = (e.clientY - panStart.y) * sensitivity;
    setPan(clampPan(rawX, rawY, zoom));
  }, [isPanning, panStart, zoom, clampPan]);

  const handleMouseUp = useCallback(() => {
    setIsPanning(false);
  }, []);

  // Double-click to reset zoom
  const handleDoubleClick = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  return (
    <div
      ref={containerRef}
      id="radar"
      className="relative overflow-hidden origin-center"
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      onDoubleClick={handleDoubleClick}
      style={{ cursor: zoom > 1 ? (isPanning ? "grabbing" : "grab") : "default" }}
    >
      {/* Zoom indicator */}
      {zoom > 1 && (
        <div
          style={{
            position: "absolute",
            top: 6,
            left: 6,
            zIndex: 10,
            background: "rgba(0,0,0,0.6)",
            color: "#fff",
            fontSize: 11,
            fontWeight: 600,
            padding: "2px 8px",
            borderRadius: 6,
            pointerEvents: "none",
            userSelect: "none",
          }}
        >
          {zoom.toFixed(1)}x
        </div>
      )}

      {/* Zoomable + pannable content wrapper */}
      <div
        style={{
          transform: `scale(${zoom}) translate(${pan.x / zoom}px, ${pan.y / zoom}px)`,
          transformOrigin: "center center",
          transition: isPanning ? "none" : "transform 0.15s ease-out",
          willChange: "transform",
        }}
      >
        <img ref={radarImageRef} className="w-full h-auto" src={radarImage} />

        {playerArray.map((player) => (
          <Player
            key={player.m_idx}
            playerData={player}
            mapData={mapData}
            radarImage={radarImageRef.current}
            localTeam={localTeam}
            averageLatency={averageLatency}
            settings={settings}
          />
        ))}

        {bombData && (
          <Bomb
            bombData={bombData}
            mapData={mapData}
            radarImage={radarImageRef.current}
            localTeam={localTeam}
            averageLatency={averageLatency}
            settings={settings}
          />
        )}

        <GrenadeLayer
          grenades={grenades}
          mapData={mapData}
          radarImage={radarImageRef.current}
          settings={settings}
        />
      </div>
    </div>
  );
};

export default Radar;