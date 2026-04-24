import { getRadarPosition } from "../utilities/utilities";

// Convert game units to rendered pixels:  units / (scale * 1024) * imgW
const gameUnitsToPx = (units, scale, imgW) =>
  (units / (scale * 1024)) * imgW;

const SMOKE_RADIUS_UNITS = 144;
const FLAME_RADIUS_UNITS = 22;
const MOLLY_RANGE_UNITS  = 120;   // outer boundary of the inferno danger zone

// Visual config per grenade type
const CFG = {
  smoke: {
    label: "SMK",
    bg:         "rgba(150,160,170,0.92)",
    border:     "rgba(200,210,220,0.80)",
    text:       "#e8eef2",
    areaBg:     "rgba(80, 90, 100, 0.88)",
    areaBorder: "rgba(160, 175, 190, 1.00)",
    areaAnim:   "grenadeSmokePulse 3s ease-in-out infinite",
    dotColor:   "rgba(190,200,210,0.95)",
  },
  molly: {
    label: "MOL",
    bg:         "rgba(210,70,0,0.92)",
    border:     "rgba(255,140,40,0.80)",
    text:       "#ffe4c4",
    areaBg:     "rgba(220, 70, 0, 0.75)",
    areaBorder: "rgba(255, 150, 40, 1.00)",
    areaAnim:   "grenadeMollyFlicker 0.6s ease-in-out infinite",
    rangeBg:     "rgba(200, 60, 0, 0.45)",
    rangeBorder: "rgba(255, 130, 20, 0.90)",
    dotColor:   "rgba(255,110,0,0.95)",
  },
  he: {
    label: "HE",
    bg:         "rgba(210,30,30,0.92)",
    border:     "rgba(255,80,80,0.75)",
    text:       "#ffe0e0",
    areaBg:     null,
    areaBorder: null,
    areaAnim:   "none",
    dotColor:   "rgba(255,70,70,0.95)",
  },
  flash: {
    label: "FLS",
    bg:         "rgba(200,190,50,0.92)",
    border:     "rgba(255,245,100,0.80)",
    text:       "#fff9e0",
    areaBg:     "rgba(255, 255, 160, 0.28)",
    areaBorder: "rgba(255, 250, 120, 0.70)",
    areaAnim:   "grenadeFlashBlink 0.4s ease-in-out infinite",
    dotColor:   "rgba(240,230,80,0.95)",
  },
  decoy: {
    label: "DCY",
    bg:         "rgba(110,70,200,0.92)",
    border:     "rgba(170,130,255,0.75)",
    text:       "#e8d8ff",
    areaBg:     null,
    areaBorder: null,
    areaAnim:   "none",
    dotColor:   "rgba(150,110,255,0.95)",
  },
};

const STYLES = `
  @keyframes grenadeSmokePulse {
    0%   { transform: translate(-50%,-50%) scale(0.97); opacity:0.95; }
    50%  { transform: translate(-50%,-50%) scale(1.03); opacity:0.80; }
    100% { transform: translate(-50%,-50%) scale(0.97); opacity:0.95; }
  }
  @keyframes grenadeMollyFlicker {
    0%   { transform: translate(-50%,-50%) scale(1.00); opacity:0.50; }
    20%  { transform: translate(-50%,-50%) scale(1.06); opacity:0.72; }
    40%  { transform: translate(-50%,-50%) scale(0.96); opacity:0.40; }
    70%  { transform: translate(-50%,-50%) scale(1.04); opacity:0.65; }
    100% { transform: translate(-50%,-50%) scale(1.00); opacity:0.50; }
  }
  @keyframes grenadeFlashBlink {
    0%   { transform: translate(-50%,-50%) scale(1.00); opacity:0.90; }
    50%  { transform: translate(-50%,-50%) scale(1.40); opacity:0.25; }
    100% { transform: translate(-50%,-50%) scale(1.00); opacity:0.90; }
  }
`;

// Shared badge style — small pill with coloured bg
const Badge = ({ label, cfg, style = {} }) => (
  <span style={{
    display:         "inline-block",
    fontSize:        9,
    fontWeight:      800,
    letterSpacing:   "0.06em",
    lineHeight:      1,
    color:           cfg.text,
    background:      cfg.bg,
    border:          `1px solid ${cfg.border}`,
    borderRadius:    3,
    padding:         "2px 4px",
    whiteSpace:      "nowrap",
    textShadow:      "0 1px 2px rgba(0,0,0,0.6)",
    boxShadow:       "0 1px 4px rgba(0,0,0,0.5)",
    position:        "relative",
    zIndex:          4,
    ...style,
  }}>
    {label}
  </span>
);

const GrenadeLayer = ({ grenades, mapData, radarImage, settings }) => {
  if (!grenades || !mapData || !radarImage) return null;

  const { width: imgW, height: imgH } =
    radarImage.getBoundingClientRect?.() ?? { width: 0, height: 0 };
  const scale = mapData.scale;

  const filtered = grenades.filter((g) => {
    if (g.type === "smoke" && settings && !settings.showSmoke) return false;
    if (g.type === "molly" && settings && !settings.showMolly) return false;
    if (g.type === "flash" && settings && !settings.showFlash) return false;
    return true;
  });

  return (
    <>
      <style>{STYLES}</style>

      {filtered.map((g, i) => {
        const cfg = CFG[g.type];
        if (!cfg) return null;

        const pos = getRadarPosition(mapData, g);
        const px  = imgW * pos.x;
        const py  = imgH * pos.y;

        const inFlight = g.deployed === false;
        const key = inFlight
          ? `${g.type}|inflight|${i}`
          : `${g.type}|${Math.round(g.x)}|${Math.round(g.y)}`;

        // ── in-flight: moving dot + tiny label ─────────────────────────────
        if (inFlight) {
          return (
            <div key={key} style={{
              position: "absolute", left: 0, top: 0,
              transform: `translate(${px}px, ${py}px) translate(-50%,-50%)`,
              pointerEvents: "none", zIndex: 2,
              display: "flex", flexDirection: "column", alignItems: "center", gap: 2,
            }}>
              <div style={{
                width: 7, height: 7, borderRadius: "50%",
                background: cfg.dotColor,
                border: `1px solid ${cfg.border}`,
                boxShadow: `0 0 5px ${cfg.dotColor}`,
              }} />
              <Badge label={cfg.label} cfg={cfg} style={{ fontSize: 7, padding: "1px 3px" }} />
            </div>
          );
        }

        // ── molly with real fire positions ─────────────────────────────────
        if (g.type === "molly" && g.firePts?.length) {
          const flameDiam  = gameUnitsToPx(FLAME_RADIUS_UNITS * 2, scale, imgW);
          const rangeDiam  = gameUnitsToPx(MOLLY_RANGE_UNITS  * 2, scale, imgW);
          return (
            <div key={key} style={{ position: "absolute", left: 0, top: 0, pointerEvents: "none", zIndex: 2 }}>
              {/* Outer range boundary */}
              <div style={{
                position:     "absolute",
                left:         px,
                top:          py,
                width:        rangeDiam,
                height:       rangeDiam,
                borderRadius: "50%",
                transform:    "translate(-50%,-50%)",
                background:   cfg.rangeBg,
                border:       `1.5px dashed ${cfg.rangeBorder}`,
              }} />

              {/* Individual flame dots */}
              {g.firePts.map((fp, fi) => {
                const fpos = getRadarPosition(mapData, fp);
                return (
                  <div key={fi} style={{
                    position:     "absolute",
                    left:         imgW * fpos.x,
                    top:          imgH * fpos.y,
                    width:        flameDiam,
                    height:       flameDiam,
                    borderRadius: "50%",
                    transform:    "translate(-50%,-50%)",
                    background:   cfg.areaBg,
                    border:       `1px solid ${cfg.areaBorder}`,
                    animation:    cfg.areaAnim,
                  }} />
                );
              })}

              {/* Centre badge */}
              <div style={{
                position: "absolute", left: px, top: py,
                transform: "translate(-50%,-50%)",
                display: "flex", flexDirection: "column", alignItems: "center", gap: 2,
                zIndex: 4,
              }}>
                <Badge label={cfg.label} cfg={cfg} />
              </div>
            </div>
          );
        }

        // ── molly fallback: no fire positions yet — show range circle only ──
        if (g.type === "molly") {
          const rangeDiam = gameUnitsToPx(MOLLY_RANGE_UNITS * 2, scale, imgW);
          return (
            <div key={key} style={{
              position: "absolute", left: 0, top: 0,
              transform: `translate(${px}px, ${py}px) translate(-50%,-50%)`,
              pointerEvents: "none", zIndex: 2,
              display: "flex", flexDirection: "column", alignItems: "center",
            }}>
              <div style={{
                position:     "absolute",
                width:        rangeDiam,
                height:       rangeDiam,
                borderRadius: "50%",
                transform:    "translate(-50%,-50%)",
                background:   cfg.rangeBg,
                border:       `1.5px dashed ${cfg.rangeBorder}`,
                animation:    cfg.areaAnim,
                left: "50%", top: "50%",
              }} />
              <Badge label={cfg.label} cfg={cfg} style={{ position: "relative", zIndex: 4 }} />
            </div>
          );
        }

        // ── smoke: exact 144-unit radius circle ────────────────────────────
        if (g.type === "smoke") {
          const smokeDiam = gameUnitsToPx(SMOKE_RADIUS_UNITS * 2, scale, imgW);
          return (
            <div key={key} style={{
              position: "absolute", left: 0, top: 0,
              transform: `translate(${px}px, ${py}px) translate(-50%,-50%)`,
              pointerEvents: "none", zIndex: 2,
              display: "flex", flexDirection: "column", alignItems: "center",
            }}>
              <div style={{
                position:     "absolute",
                width:        smokeDiam,
                height:       smokeDiam,
                borderRadius: "50%",
                background:   cfg.areaBg,
                border:       `1.5px solid ${cfg.areaBorder}`,
                animation:    cfg.areaAnim,
                left: "50%", top: "50%",
              }} />
              <Badge label={cfg.label} cfg={cfg} style={{ position: "relative", zIndex: 4 }} />
            </div>
          );
        }

        // ── flash / he / decoy deployed ────────────────────────────────────
        const needsCircle = cfg.areaBg !== null && cfg.areaBorder !== null;
        const flashDiam   = needsCircle
          ? gameUnitsToPx(80, scale, imgW)   // flash blind radius ≈ 80 units
          : 0;

        return (
          <div key={key} style={{
            position: "absolute", left: 0, top: 0,
            transform: `translate(${px}px, ${py}px) translate(-50%,-50%)`,
            pointerEvents: "none", zIndex: 2,
            display: "flex", flexDirection: "column", alignItems: "center",
          }}>
            {flashDiam > 0 && (
              <div style={{
                position:     "absolute",
                width:        flashDiam,
                height:       flashDiam,
                borderRadius: "50%",
                background:   cfg.areaBg,
                border:       `1.5px solid ${cfg.areaBorder}`,
                animation:    cfg.areaAnim,
                left: "50%", top: "50%",
              }} />
            )}
            <Badge label={cfg.label} cfg={cfg} style={{ position: "relative", zIndex: 4 }} />
          </div>
        );
      })}
    </>
  );
};

export default GrenadeLayer;
