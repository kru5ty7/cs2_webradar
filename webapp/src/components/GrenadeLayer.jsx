import { getRadarPosition } from "../utilities/utilities";

const GRENADE_CONFIG = {
  smoke: {
    emoji: "💨",
    radius: 48,
    color: "rgba(180, 180, 180, 0.35)",
  },
  molly: {
    emoji: "🔥",
    radius: 40,
    color: "rgba(255, 120, 0, 0.35)",
  },
  he: {
    emoji: "💥",
    radius: 0,
    color: "transparent",
  },
  flash: {
    emoji: "⚡",
    radius: 0,
    color: "transparent",
  },
  bomb: {
    emoji: "💣",
    radius: 0,
    color: "transparent",
  },
};

const GrenadeLayer = ({ grenades, mapData, radarImage, settings }) => {
  if (!grenades || !mapData || !radarImage) return null;

  const radarImageBounding =
    radarImage.getBoundingClientRect?.() || { width: 0, height: 0 };

  // Filter grenades based on settings toggles
  const filteredGrenades = grenades.filter((g) => {
    if (g.type === "smoke" && settings && !settings.showSmoke) return false;
    if (g.type === "molly" && settings && !settings.showMolly) return false;
    if (g.type === "flash" && settings && !settings.showFlash) return false;
    return true;
  });

  return (
    <>
      <style>{`
        @keyframes bombPulse {
          0%   { transform: scale(1);   opacity: 1; }
          50%  { transform: scale(1.3); opacity: 0.7; }
          100% { transform: scale(1);   opacity: 1; }
        }
      `}</style>

      {filteredGrenades.map((g, idx) => {
        const cfg = GRENADE_CONFIG[g.type];
        if (!cfg) return null;

        const radarPos = getRadarPosition(mapData, g);
        const px = radarImageBounding.width * radarPos.x;
        const py = radarImageBounding.height * radarPos.y;

        return (
          <div
            key={`${g.type}-${idx}`}
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              transform: `translate(${px}px, ${py}px) translate(-50%, -50%)`,
              pointerEvents: "none",
              zIndex: 2,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
            }}
          >
            {/* Area-of-effect circle for smoke / molly */}
            {cfg.radius > 0 && (
              <div
                style={{
                  position: "absolute",
                  width: cfg.radius * 2,
                  height: cfg.radius * 2,
                  borderRadius: "50%",
                  background: cfg.color,
                  transform: "translate(-50%, -50%)",
                  left: "50%",
                  top: "50%",
                }}
              />
            )}

            {/* Emoji icon */}
            <span
              style={{
                fontSize: g.type === "bomb" && g.ticking ? 22 : 18,
                lineHeight: 1,
                animation:
                  g.type === "bomb" && g.ticking
                    ? "bombPulse 1s ease-in-out infinite"
                    : "none",
                filter:
                  g.type === "bomb" && g.ticking
                    ? "drop-shadow(0 0 6px red)"
                    : "none",
              }}
            >
              {cfg.emoji}
            </span>

            {/* Bomb-specific: timer + defusing indicator */}
            {g.type === "bomb" && g.ticking && (
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  color: "#ff4444",
                  textShadow: "0 0 4px rgba(0,0,0,0.9)",
                  marginTop: 2,
                  whiteSpace: "nowrap",
                }}
              >
                {g.timer > 0 ? `${g.timer.toFixed(1)}s` : "💥"}
                {g.defusing && " 🔧"}
              </span>
            )}
          </div>
        );
      })}
    </>
  );
};

export default GrenadeLayer;
