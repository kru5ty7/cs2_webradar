import { useEffect, useState } from "react";

// Callouts are bundled locally in public/data/{map}/callouts.json

const CalloutLayer = ({ mapName, radarImage, enabled = true }) => {
  if (!enabled) return null;
  const [callouts, setCallouts] = useState([]);

  useEffect(() => {
    if (!mapName) return;
    setCallouts([]);
    fetch(`./data/${mapName}/callouts.json`)
      .then((r) => r.json())
      .then((data) => setCallouts(data.callouts || []))
      .catch(() => setCallouts([])); // map not supported, silently hide
  }, [mapName]);

  if (!radarImage || callouts.length === 0) return null;

  // Use offsetWidth/offsetHeight — gives size relative to element itself,
  // which is what we need for absolute positioning inside the radar div.
  const w = radarImage.offsetWidth;
  const h = radarImage.offsetHeight;

  if (!w || !h) return null;

  return (
    <>
      {callouts.map((c) => (
        <div
          key={c.name}
          style={{
            position: "absolute",
            left: w * c.x,
            top: h * c.y,
            transform: "translate(-50%, -50%)",
            pointerEvents: "none",
            zIndex: 20,
          }}
        >
          <span
            style={{
              fontSize: "0.55rem",
              fontWeight: 700,
              color: "#fff",
              background: "rgba(0,0,0,0.55)",
              borderRadius: 3,
              padding: "1px 3px",
              whiteSpace: "nowrap",
              letterSpacing: "0.02em",
              textShadow: "0 1px 2px rgba(0,0,0,0.9)",
              userSelect: "none",
            }}
          >
            {c.name}
          </span>
        </div>
      ))}
    </>
  );
};

export default CalloutLayer;

