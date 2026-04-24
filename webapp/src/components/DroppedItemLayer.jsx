import { getRadarPosition } from "../utilities/utilities";

// ── weapon registry ────────────────────────────────────────────────────────────
// Each entry: [label, tier]
// Tiers:  sniper | rifle | smg | shotgun | mg | pistol | zeus | nade
const WEAPONS = {
  // Snipers
  awp:        ["AWP",  "sniper"],
  ssg08:      ["SSG",  "sniper"],
  g3sg1:      ["G3",   "sniper"],
  scar20:     ["SC20", "sniper"],

  // Rifles
  ak47:       ["AK47", "rifle"],
  m4a1:       ["M4A1", "rifle"],
  m4a4:       ["M4A4", "rifle"],
  m4a1_silencer: ["M4S","rifle"],
  famas:      ["FAMAS","rifle"],
  galil:      ["GALIL","rifle"],
  aug:        ["AUG",  "rifle"],
  sg556:      ["SG5",  "rifle"],

  // SMGs
  mp9:        ["MP9",  "smg"],
  mp7:        ["MP7",  "smg"],
  mp5sd:      ["MP5",  "smg"],
  mac10:      ["MAC",  "smg"],
  ump45:      ["UMP",  "smg"],
  p90:        ["P90",  "smg"],
  bizon:      ["BIZ",  "smg"],

  // MGs
  m249:       ["M249", "mg"],
  negev:      ["NEG",  "mg"],

  // Shotguns
  nova:       ["NOVA", "shotgun"],
  xm1014:     ["XM",   "shotgun"],
  sawedoff:   ["SAW",  "shotgun"],
  mag7:       ["MAG7", "shotgun"],

  // Pistols
  deagle:     ["DEG",  "pistol"],
  revolver:   ["R8",   "pistol"],
  glock:      ["GLK",  "pistol"],
  usp_silencer: ["USP","pistol"],
  hkp2000:    ["P2K",  "pistol"],
  p250:       ["P250", "pistol"],
  tec9:       ["TEC9", "pistol"],
  fiveseven:  ["57",   "pistol"],
  cz75a:      ["CZ75", "pistol"],

  // Special
  taser:      ["ZEUS", "zeus"],

  // Throwables (dropped from inventory)
  smokegrenade: ["SMK", "nade"],
  hegrenade:    ["HE",  "nade"],
  molotov:      ["MOL", "nade"],
  incgrenade:   ["INC", "nade"],
  flashbang:    ["FLS", "nade"],
  decoy:        ["DCY", "nade"],
};

// ── tier colour palette ────────────────────────────────────────────────────────
const TIER = {
  sniper:  { bg: "rgba(140, 60, 210, 0.92)", border: "rgba(190,130,255,0.80)", text: "#f0e0ff" },
  rifle:   { bg: "rgba(200, 80,  20, 0.92)", border: "rgba(255,140, 60,0.80)", text: "#ffe8d0" },
  smg:     { bg: "rgba( 20,150,140, 0.92)", border: "rgba( 60,210,200,0.80)", text: "#d0fff8" },
  shotgun: { bg: "rgba(140, 90,  30, 0.92)", border: "rgba(200,150, 70,0.80)", text: "#ffeac8" },
  mg:      { bg: "rgba(160, 30,  30, 0.92)", border: "rgba(220, 80, 80,0.80)", text: "#ffd8d8" },
  pistol:  { bg: "rgba( 60, 90, 130, 0.92)", border: "rgba(100,150,200,0.80)", text: "#d8ecff" },
  zeus:    { bg: "rgba(190,170,  0, 0.92)", border: "rgba(255,240, 60,0.80)", text: "#fffff0" },
  nade:    { bg: "rgba( 20,150,180, 0.92)", border: "rgba( 60,210,240,0.80)", text: "#d0f8ff" },
  unknown: { bg: "rgba( 60, 60,  60, 0.88)", border: "rgba(120,120,120,0.70)", text: "#dddddd" },
};

// Higher-value tiers get a slightly larger badge
const TIER_SCALE = {
  sniper: 1.20,
  rifle:  1.10,
  mg:     1.05,
  zeus:   1.05,
};

const DroppedItemLayer = ({ items, mapData, radarImage }) => {
  if (!items?.length || !mapData || !radarImage) return null;

  const { width: imgW, height: imgH } =
    radarImage.getBoundingClientRect?.() ?? { width: 0, height: 0 };

  return (
    <>
      {items.map((item, i) => {
        const entry  = WEAPONS[item.name];
        const label  = entry ? entry[0] : item.name.slice(0, 5).toUpperCase();
        const tier   = entry ? entry[1] : "unknown";
        const colors = TIER[tier] ?? TIER.unknown;
        const scale  = TIER_SCALE[tier] ?? 1.0;

        const pos = getRadarPosition(mapData, item);
        const px  = imgW * pos.x;
        const py  = imgH * pos.y;
        const key = `${item.name}|${Math.round(item.x)}|${Math.round(item.y)}|${i}`;

        return (
          <div
            key={key}
            style={{
              position:      "absolute",
              left:          0,
              top:           0,
              transform:     `translate(${px}px, ${py}px) translate(-50%, -50%)`,
              pointerEvents: "none",
              zIndex:        2,
            }}
          >
            {/* Tier indicator dot */}
            <div style={{
              position:      "absolute",
              top:           "50%",
              left:          "50%",
              transform:     "translate(-50%, -50%)",
              width:         5,
              height:        5,
              borderRadius:  "50%",
              background:    colors.border,
              boxShadow:     `0 0 4px ${colors.border}`,
            }} />

            {/* Label badge */}
            <span style={{
              display:         "block",
              fontSize:        Math.round(8 * scale),
              fontWeight:      800,
              letterSpacing:   "0.05em",
              lineHeight:      1,
              color:           colors.text,
              background:      colors.bg,
              border:          `1px solid ${colors.border}`,
              borderRadius:    3,
              padding:         `${Math.round(2 * scale)}px ${Math.round(3 * scale + 1)}px`,
              whiteSpace:      "nowrap",
              textShadow:      "0 1px 2px rgba(0,0,0,0.7)",
              boxShadow:       "0 2px 5px rgba(0,0,0,0.55)",
              transform:       `translateY(-10px)`,
            }}>
              {label}
            </span>
          </div>
        );
      })}
    </>
  );
};

export default DroppedItemLayer;
