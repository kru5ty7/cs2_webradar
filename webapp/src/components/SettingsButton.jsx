import { useState } from "react";

const Toggle = ({ checked, onToggle, label }) => (
  <div
    onClick={onToggle}
    className="flex items-center justify-between p-3 rounded-lg hover:bg-radar-secondary/20 transition-colors cursor-pointer select-none"
  >
    <span className="text-radar-secondary text-sm">{label}</span>
    <div style={{
      width: 36, height: 20, borderRadius: 10, flexShrink: 0,
      background: checked ? "#4ade80" : "rgba(255,255,255,0.18)",
      position: "relative", transition: "background 0.15s",
    }}>
      <div style={{
        position: "absolute", width: 14, height: 14, borderRadius: "50%",
        background: "#fff", top: 3, transition: "left 0.15s",
        left: checked ? 19 : 3,
      }} />
    </div>
  </div>
);

const SettingsButton = ({ settings, onSettingsChange }) => {
  const [isOpen, setIsOpen] = useState(false);
  const toggle = (key) => onSettingsChange({ ...settings, [key]: !settings[key] });

  return (
    <div className="z-50">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-1 transition-all rounded-xl"
      >
        <img className="w-[1.3rem]" src="./assets/icons/cog.svg" />
        <span className="text-radar-primary">Settings</span>
      </button>

      {isOpen && (
        <div
          className="absolute right-0 mt-2 w-64 bg-radar-panel/90 backdrop-blur-lg rounded-xl p-4 shadow-xl border border-radar-secondary/20 max-h-[80vh] overflow-y-auto"
          style={{ zIndex: 9999 }}
        >
          <h3 className="text-radar-primary text-lg font-semibold mb-4">Radar Settings</h3>

          <div className="space-y-3">
            {/* Dot size */}
            <div>
              <div className="flex justify-between items-center mb-2">
                <span className="text-radar-secondary text-sm">Dot Size</span>
                <span id="lbl-dotSize" className="text-radar-primary text-sm font-mono">{settings.dotSize}x</span>
              </div>
              <input
                type="range" min="0.5" max="2" step="0.1"
                defaultValue={settings.dotSize}
                onInput={e => {
                  const v = parseFloat(e.target.value);
                  document.getElementById("lbl-dotSize").textContent = v.toFixed(1) + "x";
                  onSettingsChange({ ...settings, dotSize: v });
                }}
                className="w-full h-2 rounded-lg appearance-none cursor-pointer accent-radar-primary"
              />
            </div>

            {/* Bomb size */}
            <div>
              <div className="flex justify-between items-center mb-2">
                <span className="text-radar-secondary text-sm">Bomb Size</span>
                <span id="lbl-bombSize" className="text-radar-primary text-sm font-mono">{settings.bombSize}x</span>
              </div>
              <input
                type="range" min="0.1" max="2" step="0.1"
                defaultValue={settings.bombSize}
                onInput={e => {
                  const v = parseFloat(e.target.value);
                  document.getElementById("lbl-bombSize").textContent = v.toFixed(1) + "x";
                  onSettingsChange({ ...settings, bombSize: v });
                }}
                className="w-full h-2 rounded-lg appearance-none cursor-pointer accent-radar-primary"
              />
            </div>

            {/* Toggles */}
            <div className="space-y-1">
              <Toggle label="Ally Names"   checked={!!settings.showAllNames}          onToggle={() => toggle("showAllNames")} />
              <Toggle label="Enemy Names"  checked={!!settings.showEnemyNames}         onToggle={() => toggle("showEnemyNames")} />
              <Toggle label="View Cones"   checked={!!settings.showViewCones}          onToggle={() => toggle("showViewCones")} />
              <Toggle label="💨 Smoke"     checked={!!settings.showSmoke}             onToggle={() => toggle("showSmoke")} />
              <Toggle label="🔥 Molly"     checked={!!settings.showMolly}             onToggle={() => toggle("showMolly")} />
              <Toggle label="⚡ Flash"     checked={!!settings.showFlash}             onToggle={() => toggle("showFlash")} />
              <Toggle label="Map Callouts" checked={!!(settings.showCallouts ?? true)} onToggle={() => toggle("showCallouts")} />
              <Toggle label="Death Cross"  checked={!!(settings.showDeathCross ?? true)} onToggle={() => toggle("showDeathCross")} />
              <Toggle label="Bomb Pulse"   checked={!!(settings.bombHighlight ?? true)}  onToggle={() => toggle("bombHighlight")} />
            </div>

            {/* Bomb color */}
            <div className="pt-1">
              <span className="text-radar-secondary text-sm block mb-2">Bomb Color</span>
              <div className="flex items-center gap-2 flex-wrap">
                {["#ff4500","#ffdd00","#ffffff","#00cfff","#c90b0b"].map(c => (
                  <button
                    key={c}
                    onClick={() => onSettingsChange({ ...settings, bombColor: c })}
                    style={{
                      background: c, width: 22, height: 22, borderRadius: "50%",
                      border: settings.bombColor === c ? "2px solid #fff" : "2px solid transparent",
                      cursor: "pointer", flexShrink: 0,
                    }}
                    title={c}
                  />
                ))}
                <input
                  type="color"
                  defaultValue={settings.bombColor ?? "#ff4500"}
                  onInput={e => onSettingsChange({ ...settings, bombColor: e.target.value })}
                  style={{ width: 22, height: 22, padding: 0, border: "none", borderRadius: "50%", cursor: "pointer", background: "none" }}
                  title="Custom color"
                />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SettingsButton;
